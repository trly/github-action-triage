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
    client.rest.apps.async_create_installation_access_token = AsyncMock()
    client.rest.actions.async_get_job_for_workflow_run = AsyncMock()
    client.rest.actions.async_download_job_logs_for_workflow_run = AsyncMock()
    return client


@pytest.fixture
def settings():
    return Settings(
        github_app_id="12345",
        github_private_key="test-key",
        github_webhook_secret="test-secret",
        anthropic_api_key="test-api-key",
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
    # Mock the installation token response
    mock_token_response = MagicMock()
    mock_token_response.parsed_data.token = "installation_token_123"
    mock_github_client.rest.apps.async_create_installation_access_token.return_value = (
        mock_token_response
    )

    # Mock the new GitHub client creation
    mock_installation_client = MagicMock()
    mock_installation_client.rest.actions.async_get_job_for_workflow_run = AsyncMock()
    mock_installation_client.rest.actions.async_download_job_logs_for_workflow_run = AsyncMock()
    mock_installation_client.rest.actions.async_get_workflow_run = AsyncMock()

    # Mock GitHub constructor
    from githubkit import GitHub
    def mock_github_constructor(token):
        return mock_installation_client
    monkeypatch.setattr("githubkit.GitHub", mock_github_constructor)

    # Mock the GitHub API response for job
    mock_response = MagicMock()
    mock_response.parsed_data = MagicMock(
        head_sha="abc123def456",
        head_branch="main",
        html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
    )
    mock_installation_client.rest.actions.async_get_job_for_workflow_run.return_value = (
        mock_response
    )

    # Mock the log download
    mock_logs = b"Step 1: Install dependencies\nError: npm install failed\nExiting with code 1"
    mock_logs_response = MagicMock()
    mock_logs_response.content = mock_logs
    mock_installation_client.rest.actions.async_download_job_logs_for_workflow_run.return_value = (
        mock_logs_response
    )
    
    # Mock the workflow run response for workflow path
    mock_run_response = MagicMock()
    mock_run_response.parsed_data = MagicMock(
        path=".github/workflows/ci.yml"
    )
    mock_installation_client.rest.actions.async_get_workflow_run.return_value = (
        mock_run_response
    )

    adapter = GitHubContextAdapter(settings, mock_github_client)
    context = await adapter.fetch_failure_context(failure_event)

    # Verify the GitHub API was called correctly
    mock_installation_client.rest.actions.async_get_job_for_workflow_run.assert_called_once_with(
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
    assert context.workflow_file_path == ".github/workflows/ci.yml"
    assert context.recent_commits == ["abc123def456"]


@pytest.mark.asyncio
async def test_handles_api_errors_gracefully(
    mock_github_client, settings, failure_event, monkeypatch
):
    # Mock the installation token response
    mock_token_response = MagicMock()
    mock_token_response.parsed_data.token = "installation_token_123"
    mock_github_client.rest.apps.async_create_installation_access_token.return_value = (
        mock_token_response
    )

    # Mock the new GitHub client creation
    mock_installation_client = MagicMock()
    mock_installation_client.rest.actions.async_get_job_for_workflow_run = AsyncMock()

    # Mock GitHub constructor
    from githubkit import GitHub
    def mock_github_constructor(token):
        return mock_installation_client
    monkeypatch.setattr("githubkit.GitHub", mock_github_constructor)

    # Simulate an API error
    mock_installation_client.rest.actions.async_get_job_for_workflow_run.side_effect = (
        Exception("API error")
    )

    adapter = GitHubContextAdapter(settings, mock_github_client)

    with pytest.raises(Exception, match="API error"):
        await adapter.fetch_failure_context(failure_event)
