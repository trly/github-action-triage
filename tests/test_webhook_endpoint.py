import json
import hmac
import hashlib
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
async def test_client(monkeypatch):
    monkeypatch.setenv("TRIAGE_GITHUB_WEBHOOK_SECRET", "test-secret")
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


def compute_signature(payload: bytes, secret: str = "test-secret") -> str:
    """Compute GitHub webhook signature."""
    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    )
    return f"sha256={computed_hmac.hexdigest()}"


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

    payload = json.dumps(workflow_job_payload(action="completed", conclusion="failure")).encode()
    response = await test_client.post(
    "/github/webhook",
    headers={
            "X-GitHub-Event": "workflow_job",
            "X-Hub-Signature-256": compute_signature(payload),
        },
        content=payload,
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" in caplog.text


@pytest.mark.asyncio
async def test_invokes_failure_handler_for_job_failure(caplog, test_client, monkeypatch):
    caplog.set_level("INFO")
    
    # Mock the triage service to avoid real API calls
    from github_action_triage.app.api import TriageService
    
    async def mock_process_failure_async(self, event):
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Background triage processing started")
    
    # Patch the TriageService process_failure_async method
    monkeypatch.setattr(TriageService, "process_failure_async", mock_process_failure_async)

    payload = json.dumps(workflow_job_payload(action="completed", conclusion="failure")).encode()
    response = await test_client.post(
    "/github/webhook",
    headers={
            "X-GitHub-Event": "workflow_job",
            "X-Hub-Signature-256": compute_signature(payload),
        },
        content=payload,
    )
    assert response.status_code == 202
    assert "Background triage processing started" in caplog.text


@pytest.mark.asyncio
async def test_ignores_non_matching_action(caplog, test_client):
    caplog.set_level("INFO")
    payload = json.dumps(workflow_job_payload(action="queued", conclusion="failure")).encode()
    response = await test_client.post(
        "/github/webhook",
        headers={
            "X-GitHub-Event": "workflow_job",
            "X-Hub-Signature-256": compute_signature(payload),
        },
        content=payload,
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" not in caplog.text


@pytest.mark.asyncio
async def test_ignores_non_failure_conclusion(caplog, test_client):
    caplog.set_level("INFO")
    payload = json.dumps(workflow_job_payload(action="completed", conclusion="success")).encode()
    response = await test_client.post(
        "/github/webhook",
        headers={
            "X-GitHub-Event": "workflow_job",
            "X-Hub-Signature-256": compute_signature(payload),
        },
        content=payload,
    )
    assert response.status_code == 202
    assert "workflow_job.completed.failure" not in caplog.text


@pytest.mark.asyncio
async def test_ignores_different_event_type(caplog, test_client):
    caplog.set_level("INFO")
    payload = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "test-org/test-repo"}}).encode()
    response = await test_client.post(
        "/github/webhook",
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": compute_signature(payload),
        },
        content=payload,
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
async def test_rejects_invalid_signature(test_client):
    payload = json.dumps(workflow_job_payload(action="completed", conclusion="failure")).encode()
    response = await test_client.post(
        "/github/webhook",
        headers={
            "X-GitHub-Event": "workflow_job",
            "X-Hub-Signature-256": "sha256=invalid_signature",
        },
        content=payload,
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rejects_missing_signature(test_client):
    payload = json.dumps(workflow_job_payload(action="completed", conclusion="failure")).encode()
    response = await test_client.post(
        "/github/webhook",
        headers={
            "X-GitHub-Event": "workflow_job",
        },
        content=payload,
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rejects_invalid_payload(test_client):
    payload = json.dumps({"invalid": "payload"}).encode()
    response = await test_client.post(
        "/github/webhook",
        headers={
            "X-GitHub-Event": "workflow_job",
            "X-Hub-Signature-256": compute_signature(payload),
        },
        content=payload,
    )
    assert response.status_code == 400
    assert "Invalid" in response.json()["detail"] or "payload" in response.json()["detail"]