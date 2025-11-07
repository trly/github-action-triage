import pytest
from unittest.mock import AsyncMock
from github_action_triage.app.api import TriageService
from github_action_triage.app.events.models import (
    WorkflowRunFailureEvent,
    RepositoryRef,
    WorkflowRef,
    FailureSummary,
)
from github_action_triage.app.events.outcomes import TriageOutcome
from github_action_triage.agent.ports import (
    GitHubContextProvider,
    RemediationAgent,
    RepositoryActuator,
)


@pytest.mark.asyncio
async def test_triage_service_contract():
    from github_action_triage.agent.ports import FailureContext
    
    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_actuator = AsyncMock(spec=RepositoryActuator)

    # Mock the context provider to return a failure context
    mock_context = FailureContext(
        event=WorkflowRunFailureEvent(
            installation_id=12345,
            repository=RepositoryRef(owner="test-org", name="test-repo"),
            workflow=WorkflowRef(
                run_id="123",
                job_id="456",
                workflow_name="CI",
                job_name="build",
                run_url="https://github.com/test-org/test-repo/actions/runs/123",
            ),
            failure=FailureSummary(
                conclusion="failure",
                logs_snippet="Error: build failed",
            ),
        ),
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
        logs_excerpt="Error: build failed",
        recent_commits=["abc123"],
    )
    mock_context_provider.fetch_failure_context.return_value = mock_context

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        actuator=mock_actuator,
    )

    event = WorkflowRunFailureEvent(
        installation_id=12345,
        repository=RepositoryRef(owner="test-org", name="test-repo"),
        workflow=WorkflowRef(
            run_id="123",
            job_id="456",
            workflow_name="CI",
            job_name="build",
            run_url="https://github.com/test-org/test-repo/actions/runs/123",
        ),
        failure=FailureSummary(
            conclusion="failure",
            logs_snippet="Error: build failed",
        ),
    )

    # Mock the agent to return a proposal
    from github_action_triage.agent.ports import RemediationProposal
    mock_proposal = RemediationProposal(
        identified_issue="Test issue",
        fix_effort="small",
        remediation_plan="Test plan"
    )
    mock_agent.diagnose_and_propose.return_value = mock_proposal

    result = await service.handle_failure(event)
    
    # Verify context provider was called
    mock_context_provider.fetch_failure_context.assert_called_once_with(event)
    
    # Verify agent diagnose_and_propose was called with context
    mock_agent.diagnose_and_propose.assert_called_once_with(mock_context)
    
    # Verify outcome is ANALYZED
    assert result.outcome == TriageOutcome.ANALYZED
    assert "Test issue" in result.message


@pytest.mark.asyncio
async def test_triage_service_accepts_ports():
    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_actuator = AsyncMock(spec=RepositoryActuator)

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        actuator=mock_actuator,
    )

    assert service is not None
