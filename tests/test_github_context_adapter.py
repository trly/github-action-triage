import pytest
from unittest.mock import AsyncMock, MagicMock
from github_action_triage.app.infra.github_client import GitHubContextAdapter
from github_action_triage.app.events.models import (
    WorkflowRunFailureEvent,
    RepositoryRef,
    WorkflowRef,
    FailureSummary,
)
from github_action_triage.app.config.settings import Settings


@pytest.fixture
def mock_github_client():
    client = MagicMock()
    client.rest.actions.async_get_job_for_workflow_run = AsyncMock()
    return client


@pytest.fixture
def settings():
    return Settings(
        github_app_id="12345",
        github_private_key="test-key",
        github_webhook_secret="test-secret",
        openai_api_key="test-api-key",
    )


@pytest.fixture
def failure_event():
    return WorkflowRunFailureEvent(
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
            logs_snippet="Error: npm install failed",
        ),
    )


@pytest.mark.asyncio
async def test_fetches_job_details_and_constructs_context(
    mock_github_client, settings, failure_event, monkeypatch
):
    # Mock the GitHub API response
    mock_response = MagicMock()
    mock_response.parsed_data = MagicMock(
        head_sha="abc123def456",
        head_branch="main",
        html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
    )
    mock_github_client.rest.actions.async_get_job_for_workflow_run.return_value = (
        mock_response
    )

    # Mock the log download
    mock_logs = b"Step 1: Install dependencies\nError: npm install failed\nExiting with code 1"

    async def mock_download_logs(self, logs_url: str) -> bytes:
        return mock_logs

    monkeypatch.setattr(
        GitHubContextAdapter, "_download_logs", mock_download_logs
    )

    adapter = GitHubContextAdapter(settings, mock_github_client)
    context = await adapter.fetch_failure_context(failure_event)

    # Verify the GitHub API was called correctly
    mock_github_client.rest.actions.async_get_job_for_workflow_run.assert_called_once_with(
        owner="test-org",
        repo="test-repo",
        job_id=456,
    )

    # Verify the context is constructed correctly
    assert context.repository_full_name == "test-org/test-repo"
    assert context.head_commit_sha == "abc123def456"
    assert context.branch_ref == "refs/heads/main"
    assert context.job_html_url == "https://github.com/test-org/test-repo/actions/runs/123/job/456"
    assert "npm install failed" in context.logs_excerpt
    assert context.recent_commits == ["abc123def456"]


@pytest.mark.asyncio
async def test_handles_api_errors_gracefully(
    mock_github_client, settings, failure_event
):
    # Simulate an API error
    mock_github_client.rest.actions.async_get_job_for_workflow_run.side_effect = (
        Exception("API error")
    )

    adapter = GitHubContextAdapter(settings, mock_github_client)

    with pytest.raises(Exception, match="API error"):
        await adapter.fetch_failure_context(failure_event)
