import json
import pytest
from httpx import AsyncClient, ASGITransport
from github_action_triage.app.factory import create_app


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


@pytest.fixture(autouse=True)
def stub_githubkit_parse(monkeypatch):
    import github_action_triage.app.web.github_webhooks as wh
    monkeypatch.setattr(wh, "WebhookWorkflowJobCompleted", _WorkflowJobEvent, raising=True)

    import github_action_triage.app.web.api as api

    def _parse(event_name: str, body: bytes):
        data = json.loads(body or b"{}")
        if "invalid" in data:
            raise ValueError("invalid payload")

        if event_name != "workflow_job":
            return object()

        wf = data.get("workflow_job", {})
        repo = data.get("repository", {})
        action = data.get("action")
        
        # Only return WebhookWorkflowJobCompleted for completed actions
        if action != "completed":
            return object()
        
        return _WorkflowJobEvent(
            action=action,
            repository=_Repo(repo.get("full_name", "test-org/test-repo")),
            workflow_job=_Job(
                id=wf.get("id", 0),
                run_id=wf.get("run_id", 0),
                name=wf.get("name", wf.get("workflow_name", "build")),
                conclusion=wf.get("conclusion"),
                run_url=wf.get("run_url", ""),
            ),
        )

    monkeypatch.setattr(api, "parse", _parse, raising=True)


@pytest.fixture
async def test_client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


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


@pytest.mark.asyncio
async def test_logs_failure_workflow_job(caplog, test_client, monkeypatch):
    caplog.set_level("INFO")
    
    # Mock the triage service to avoid real API calls
    from github_action_triage.app.api import TriageService, TriageResult
    from github_action_triage.app.events.outcomes import TriageOutcome
    
    async def mock_handle_failure(self, event):
        return TriageResult(
            outcome=TriageOutcome.DEFERRED,
            message="Failure context captured for AI triage",
        )
    
    monkeypatch.setattr(TriageService, "handle_failure", mock_handle_failure)
    
    response = await test_client.post(
        "/github/webhook",
        headers={"X-GitHub-Event": "workflow_job"},
        json=workflow_job_payload(action="completed", conclusion="failure"),
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" in caplog.text


@pytest.mark.asyncio
async def test_invokes_failure_handler_for_job_failure(caplog, test_client, monkeypatch):
    caplog.set_level("INFO")
    
    # Mock the triage service to avoid real API calls
    from github_action_triage.app.api import TriageService, TriageResult
    from github_action_triage.app.events.outcomes import TriageOutcome
    
    async def mock_handle_failure(self, event):
        return TriageResult(
            outcome=TriageOutcome.DEFERRED,
            message="Failure context captured for AI triage",
        )
    
    # Patch the TriageService handle_failure method
    monkeypatch.setattr(TriageService, "handle_failure", mock_handle_failure)
    
    response = await test_client.post(
        "/github/webhook",
        headers={"X-GitHub-Event": "workflow_job"},
        json=workflow_job_payload(action="completed", conclusion="failure"),
    )
    assert response.status_code == 202
    assert "Starting failure analysis and remediation" in caplog.text
    assert "AI remediation result" in caplog.text


@pytest.mark.asyncio
async def test_ignores_non_matching_action(caplog, test_client):
    caplog.set_level("INFO")
    response = await test_client.post(
        "/github/webhook",
        headers={"X-GitHub-Event": "workflow_job"},
        json=workflow_job_payload(action="queued", conclusion="failure"),
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" not in caplog.text


@pytest.mark.asyncio
async def test_ignores_non_failure_conclusion(caplog, test_client):
    caplog.set_level("INFO")
    response = await test_client.post(
        "/github/webhook",
        headers={"X-GitHub-Event": "workflow_job"},
        json=workflow_job_payload(action="completed", conclusion="success"),
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" not in caplog.text


@pytest.mark.asyncio
async def test_ignores_different_event_type(caplog, test_client):
    caplog.set_level("INFO")
    response = await test_client.post(
        "/github/webhook",
        headers={"X-GitHub-Event": "push"},
        json={"ref": "refs/heads/main", "repository": {"full_name": "test-org/test-repo"}},
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" not in caplog.text


@pytest.mark.asyncio
async def test_rejects_missing_header(test_client):
    response = await test_client.post(
        "/github/webhook",
        json=workflow_job_payload(),
    )
    assert response.status_code == 400
    assert "X-GitHub-Event" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rejects_invalid_payload(test_client):
    response = await test_client.post(
        "/github/webhook",
        headers={"X-GitHub-Event": "workflow_job"},
        json={"invalid": "payload"},
    )
    assert response.status_code == 400
    assert "Invalid" in response.json()["detail"] or "payload" in response.json()["detail"]
