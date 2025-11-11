import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from github_action_triage.agent.ports import (
    FailureContext,
    RemediationProposal,
)
from github_action_triage.app.events.models import (
    FailureSummary,
    RepositoryRef,
    WorkflowRef,
    WorkflowRunFailureEvent,
)
from github_action_triage.app.factory import create_app


def compute_signature(payload: bytes, secret: str = "test-secret") -> str:
    computed_hmac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    return f"sha256={computed_hmac.hexdigest()}"


def workflow_job_payload(action: str = "completed", conclusion: str = "failure"):
    return {
        "action": action,
        "workflow_job": {
            "id": 12345,
            "run_id": 67890,
            "name": "build",
            "conclusion": conclusion,
            "run_url": "https://github.com/test-org/test-repo/actions/runs/67890",
        },
        "repository": {
            "full_name": "test-org/test-repo",
        },
    }


@pytest.fixture
def failure_event():
    return WorkflowRunFailureEvent(
        installation_id=12345,
        repository=RepositoryRef(owner="test-org", name="test-repo"),
        workflow=WorkflowRef(
            run_id="67890",
            job_id="12345",
            workflow_name="CI",
            job_name="build",
            run_url="https://github.com/test-org/test-repo/actions/runs/67890",
        ),
        failure=FailureSummary(
            conclusion="failure",
            logs_snippet="Error: npm install failed",
        ),
    )


@pytest.fixture
def failure_context(failure_event):
    return FailureContext(
        event=failure_event,
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/67890/job/12345",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/12345/logs",
        logs_excerpt="Error: npm install failed\nERROR: package-lock.json not found",
        workflow_file_path=".github/workflows/ci.yml",
        recent_commits=["abc123"],
    )


@pytest.fixture
def remediation_proposal():
    return RemediationProposal(
        issue_title="npm install failed",
        identified_issue="npm install failed due to missing package-lock.json",
        fix_effort="small",
        remediation_plan="1. Run npm install locally\n2. Commit package-lock.json\n3. Re-run workflow",
    )


@pytest.mark.asyncio
async def test_webhook_triggers_background_task(monkeypatch, failure_event, failure_context):
    """Verify that webhook endpoint triggers Celery task for workflow failures."""

    celery_task_calls = []

    class MockCeleryTask:
        def __init__(self, task_id):
            self.id = task_id

        def delay(self, **kwargs):
            celery_task_calls.append(kwargs)
            return self

    mock_task = MockCeleryTask("test-task-id-123")

    # Mock analyze_workflow_failure.delay
    import github_action_triage.app.web.api as api_module

    monkeypatch.setattr(api_module, "analyze_workflow_failure", mock_task)

    # Mock context provider to avoid real GitHub API calls
    from unittest.mock import AsyncMock

    from github_action_triage.agent.ports import GitHubContextProvider

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_context_provider.fetch_failure_context.return_value = failure_context

    # Setup githubkit parse stub
    import github_action_triage.app.web.api as api
    import github_action_triage.app.web.github_webhooks as wh

    class _Repo:
        def __init__(self, full_name):
            self.full_name = full_name

    class _Job:
        def __init__(self, id, run_id, name, conclusion, run_url):
            self.id = id
            self.run_id = run_id
            self.name = name
            self.conclusion = conclusion
            self.run_url = run_url

    class _Installation:
        def __init__(self, id):
            self.id = id

    class _WorkflowJobEvent:
        def __init__(self, action, repository, workflow_job, installation=None):
            self.action = action
            self.repository = repository
            self.workflow_job = workflow_job
            self.installation = installation or _Installation(12345)

    monkeypatch.setattr(wh, "WebhookWorkflowJobCompleted", _WorkflowJobEvent, raising=True)

    def _parse(event_name: str, body: bytes):
        data = json.loads(body or b"{}")
        if event_name != "workflow_job":
            return object()

        wf = data.get("workflow_job", {})
        repo = data.get("repository", {})
        action = data.get("action")

        if action != "completed":
            return object()

        return _WorkflowJobEvent(
            action=action,
            repository=_Repo(repo.get("full_name", "test-org/test-repo")),
            workflow_job=_Job(
                id=wf.get("id", 0),
                run_id=wf.get("run_id", 0),
                name=wf.get("name", "build"),
                conclusion=wf.get("conclusion"),
                run_url=wf.get("run_url", ""),
            ),
        )

    monkeypatch.setattr(api, "parse", _parse, raising=True)
    monkeypatch.setenv("TRIAGE_GITHUB_WEBHOOK_SECRET", "test-secret")

    # Create test client
    app = create_app()
    
    # Inject mocked context provider into app state
    app.state.triage_service._context_provider = mock_context_provider
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = json.dumps(
            workflow_job_payload(action="completed", conclusion="failure")
        ).encode()
        response = await client.post(
            "/github/webhook",
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-Hub-Signature-256": compute_signature(payload),
                "X-GitHub-Delivery": "test-delivery-123",
            },
            content=payload,
        )

    assert response.status_code == 202
    assert response.json()["task_id"] == "test-task-id-123"
    
    # Verify task was enqueued with correct parameters
    assert len(celery_task_calls) == 1
    task_call = celery_task_calls[0]
    assert task_call["github_delivery_id"] == "test-delivery-123"
    assert "context" in task_call
    assert task_call["context"]["repository_full_name"] == "test-org/test-repo"
    assert task_call["context"]["head_commit_sha"] == "abc123"


@pytest.mark.asyncio
async def test_agent_diagnose_called_with_context(
    failure_event, failure_context, remediation_proposal
):
    """Verify that end-to-end flow calls agent.diagnose_and_propose with correct FailureContext."""
    from github_action_triage.agent.ports import (
        GitHubContextProvider,
        IssueCreator,
        RemediationAgent,
    )
    from github_action_triage.app.api import TriageService

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

    mock_context_provider.fetch_failure_context.return_value = failure_context
    mock_agent.diagnose_and_propose.return_value = remediation_proposal

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        issue_creator=mock_issue_creator,
    )

    result = await service.handle_failure(failure_event)

    mock_context_provider.fetch_failure_context.assert_called_once_with(failure_event)
    mock_agent.diagnose_and_propose.assert_called_once()

    called_context = mock_agent.diagnose_and_propose.call_args[0][0]
    assert isinstance(called_context, FailureContext)
    assert called_context.repository_full_name == "test-org/test-repo"
    assert called_context.head_commit_sha == "abc123"
    assert (
        called_context.logs_excerpt
        == "Error: npm install failed\nERROR: package-lock.json not found"
    )


@pytest.mark.asyncio
async def test_actuator_apply_fix_called(failure_event, failure_context, remediation_proposal):
    """Verify that background processing calls issue_creator.create_issue_for_proposal."""
    from github_action_triage.agent.ports import (
        GitHubContextProvider,
        IssueCreator,
        RemediationAgent,
    )
    from github_action_triage.app.api import TriageService

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

    mock_context_provider.fetch_failure_context.return_value = failure_context
    mock_agent.diagnose_and_propose.return_value = remediation_proposal
    mock_issue_creator.create_issue_for_proposal.return_value = (
        "https://github.com/test-org/test-repo/issues/1"
    )

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        issue_creator=mock_issue_creator,
    )

    await service.process_failure_async(failure_event)

    mock_context_provider.fetch_failure_context.assert_called_once_with(failure_event)
    mock_agent.diagnose_and_propose.assert_called_once_with(failure_context)
    mock_issue_creator.create_issue_for_proposal.assert_called_once()

    call_args = mock_issue_creator.create_issue_for_proposal.call_args
    assert call_args[0][0] == failure_event
    assert isinstance(call_args[0][1], RemediationProposal)
    assert call_args[0][1].identified_issue == "npm install failed due to missing package-lock.json"
    assert call_args[0][1].fix_effort == "small"


@pytest.mark.asyncio
async def test_submit_proposal_tool_returns_remediation():
    """Test the submit_proposal tool directly to verify proper RemediationProposal construction."""
    from github_action_triage.agent.ai_agent import ActionTriageAgent
    from github_action_triage.app.config.settings import Settings

    settings = Settings(anthropic_api_key="test-key")
    agent = ActionTriageAgent(settings)

    proposal_storage = {"proposal": None}
    submit_tool = agent._create_submit_proposal_tool(proposal_storage)

    result = await submit_tool.handler(
        {
            "issue_title": "Dependency version conflict",
            "identified_issue": "Dependency version conflict in package.json",
            "fix_effort": "medium",
            "remediation_plan": "1. Update conflicting dependencies\n2. Run npm audit fix\n3. Test locally\n4. Commit changes",
        }
    )

    assert result is not None
    assert "content" in result
    assert result["content"][0]["type"] == "text"
    assert "success" in result["content"][0]["text"].lower()

    stored_proposal = proposal_storage["proposal"]
    assert stored_proposal is not None
    assert isinstance(stored_proposal, RemediationProposal)
    assert stored_proposal.issue_title == "Dependency version conflict"
    assert stored_proposal.identified_issue == "Dependency version conflict in package.json"
    assert stored_proposal.fix_effort == "medium"
    assert (
        stored_proposal.remediation_plan
        == "1. Update conflicting dependencies\n2. Run npm audit fix\n3. Test locally\n4. Commit changes"
    )


@pytest.mark.asyncio
async def test_end_to_end_integration_flow(
    failure_event, failure_context, remediation_proposal, caplog
):
    """Integration test verifying complete webhook → background processing → agent → issue creation flow."""
    import logging

    from github_action_triage.agent.ports import (
        GitHubContextProvider,
        IssueCreator,
        RemediationAgent,
    )
    from github_action_triage.app.api import TriageService

    caplog.set_level(logging.INFO)

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

    mock_context_provider.fetch_failure_context.return_value = failure_context
    mock_agent.diagnose_and_propose.return_value = remediation_proposal
    mock_issue_creator.create_issue_for_proposal.return_value = (
        "https://github.com/test-org/test-repo/issues/1"
    )

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        issue_creator=mock_issue_creator,
    )

    await service.process_failure_async(failure_event)

    mock_context_provider.fetch_failure_context.assert_called_once()
    mock_agent.diagnose_and_propose.assert_called_once()
    mock_issue_creator.create_issue_for_proposal.assert_called_once()

    assert "Created issue for failure" in caplog.text


@pytest.mark.asyncio
async def test_background_processing_handles_errors_gracefully(
    failure_event, failure_context, caplog
):
    """Verify that errors in background processing are caught and logged."""
    import logging

    from github_action_triage.agent.ports import (
        GitHubContextProvider,
        IssueCreator,
        RemediationAgent,
    )
    from github_action_triage.app.api import TriageService

    caplog.set_level(logging.ERROR)

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

    mock_context_provider.fetch_failure_context.return_value = failure_context
    mock_agent.diagnose_and_propose.side_effect = RuntimeError("AI analysis failed")

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        issue_creator=mock_issue_creator,
    )

    await service.process_failure_async(failure_event)

    mock_context_provider.fetch_failure_context.assert_called_once()
    mock_agent.diagnose_and_propose.assert_called_once()
    mock_issue_creator.create_issue_for_proposal.assert_not_called()

    assert "Error during background triage processing" in caplog.text


@pytest.mark.asyncio
async def test_actuator_failure_is_logged(
    failure_event, failure_context, remediation_proposal, caplog
):
    """Verify that issue creator failure is logged but doesn't crash the flow."""
    import logging

    from github_action_triage.agent.ports import (
        GitHubContextProvider,
        IssueCreator,
        RemediationAgent,
    )
    from github_action_triage.app.api import TriageService

    caplog.set_level(logging.ERROR)

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

    mock_context_provider.fetch_failure_context.return_value = failure_context
    mock_agent.diagnose_and_propose.return_value = remediation_proposal
    mock_issue_creator.create_issue_for_proposal.side_effect = RuntimeError("GitHub API failed")

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        issue_creator=mock_issue_creator,
    )

    await service.process_failure_async(failure_event)

    mock_issue_creator.create_issue_for_proposal.assert_called_once()
    assert "Error during background triage processing" in caplog.text
