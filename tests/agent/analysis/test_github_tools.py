import io
import zipfile
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic_ai import RunContext

from github_action_triage.agent.analysis.tools.github import (
    GitHubToolContext,
    _extract_logs_from_archive,
    get_job,
    get_job_logs,
)
from github_action_triage.agent.config import Settings


@pytest.fixture
def settings():
    return Settings(
        github_app_id="123456",
        github_private_key="test-private-key",
        github_webhook_secret="test-secret",
        anthropic_api_key="test-key",
    )


@pytest.fixture
def failure_context():
    from github_action_triage.agent.ports import (
        FailureContext,
        FailureSummary,
        RepositoryRef,
        WorkflowRef,
        WorkflowRunFailureEvent,
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
            logs_snippet="Error: test failure",
        ),
    )
    return FailureContext(
        event=event,
        job_id=123456,
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/123456/logs",
        logs_excerpt="Error: test failure",
    )


@pytest.fixture
def github_context(settings, failure_context):
    return GitHubToolContext(
        settings=settings,
        owner="test-org",
        repo="test-repo",
        installation_id=12345,
        failure=failure_context,
    )


@pytest.fixture
def run_context(github_context):
    ctx = Mock(spec=RunContext)
    ctx.deps = github_context
    return ctx


@pytest.mark.asyncio
async def test_get_job_returns_formatted_job_data(run_context, monkeypatch):
    mock_job_data = Mock()
    mock_job_data.id = 123456
    mock_job_data.status = "completed"
    mock_job_data.conclusion = "failure"
    mock_job_data.head_sha = "abc123def"
    mock_job_data.head_branch = "main"
    mock_job_data.html_url = "https://github.com/test-org/test-repo/actions/runs/123"

    step1 = Mock()
    step1.name = "Checkout"
    step1.status = "completed"
    step1.conclusion = "success"
    step1.number = 1

    step2 = Mock()
    step2.name = "Build"
    step2.status = "completed"
    step2.conclusion = "failure"
    step2.number = 2

    mock_job_data.steps = [step1, step2]

    mock_response = Mock()
    mock_response.parsed_data = mock_job_data

    mock_github = AsyncMock()
    mock_github.rest.actions.async_get_job_for_workflow_run.return_value = mock_response
    mock_github.rest.apps.async_create_installation_access_token.return_value = Mock(
        parsed_data=Mock(token="test-installation-token")
    )

    async def mock_get_client(ctx):
        return mock_github

    monkeypatch.setattr(
        "github_action_triage.agent.analysis.tools.github._get_installation_client",
        mock_get_client,
    )

    result = await get_job(run_context, job_id=123456)

    assert result["id"] == 123456
    assert result["status"] == "completed"
    assert result["conclusion"] == "failure"
    assert result["head_sha"] == "abc123def"
    assert result["head_branch"] == "main"
    assert result["html_url"] == "https://github.com/test-org/test-repo/actions/runs/123"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["name"] == "Checkout"
    assert result["steps"][0]["conclusion"] == "success"
    assert result["steps"][1]["name"] == "Build"
    assert result["steps"][1]["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_get_job_handles_no_steps(run_context, monkeypatch):
    mock_job_data = Mock()
    mock_job_data.id = 123456
    mock_job_data.status = "completed"
    mock_job_data.conclusion = "failure"
    mock_job_data.head_sha = "abc123"
    mock_job_data.head_branch = "main"
    mock_job_data.html_url = "https://github.com/test-org/test-repo/actions/runs/123"
    mock_job_data.steps = None

    mock_response = Mock()
    mock_response.parsed_data = mock_job_data

    mock_github = AsyncMock()
    mock_github.rest.actions.async_get_job_for_workflow_run.return_value = mock_response
    mock_github.rest.apps.async_create_installation_access_token.return_value = Mock(
        parsed_data=Mock(token="test-token")
    )

    async def mock_get_client(ctx):
        return mock_github

    monkeypatch.setattr(
        "github_action_triage.agent.analysis.tools.github._get_installation_client",
        mock_get_client,
    )

    result = await get_job(run_context, job_id=123456)

    assert result["steps"] == []


@pytest.mark.asyncio
async def test_get_job_logs_extracts_from_zip_archive(run_context, monkeypatch):
    log_content = "Step 1: Running tests\nStep 2: Build failed\nError: npm install failed"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("job.log", log_content)
    zip_bytes = zip_buffer.getvalue()

    mock_response = Mock()
    mock_response.content = zip_bytes

    mock_github = AsyncMock()
    mock_github.rest.actions.async_download_job_logs_for_workflow_run.return_value = mock_response
    mock_github.rest.apps.async_create_installation_access_token.return_value = Mock(
        parsed_data=Mock(token="test-token")
    )

    async def mock_get_client(ctx):
        return mock_github

    monkeypatch.setattr(
        "github_action_triage.agent.analysis.tools.github._get_installation_client",
        mock_get_client,
    )

    result = await get_job_logs(run_context, job_id=123456)

    assert result == log_content


@pytest.mark.asyncio
async def test_get_job_logs_handles_plain_text(run_context, monkeypatch):
    log_content = "Plain text logs without zip compression"

    mock_response = Mock()
    mock_response.content = log_content.encode("utf-8")

    mock_github = AsyncMock()
    mock_github.rest.actions.async_download_job_logs_for_workflow_run.return_value = mock_response
    mock_github.rest.apps.async_create_installation_access_token.return_value = Mock(
        parsed_data=Mock(token="test-token")
    )

    async def mock_get_client(ctx):
        return mock_github

    monkeypatch.setattr(
        "github_action_triage.agent.analysis.tools.github._get_installation_client",
        mock_get_client,
    )

    result = await get_job_logs(run_context, job_id=123456)

    assert result == log_content


@pytest.mark.asyncio
async def test_get_job_logs_handles_api_failure(run_context, monkeypatch):
    mock_github = AsyncMock()
    mock_github.rest.actions.async_download_job_logs_for_workflow_run.side_effect = Exception(
        "API rate limit exceeded"
    )
    mock_github.rest.apps.async_create_installation_access_token.return_value = Mock(
        parsed_data=Mock(token="test-token")
    )

    async def mock_get_client(ctx):
        return mock_github

    monkeypatch.setattr(
        "github_action_triage.agent.analysis.tools.github._get_installation_client",
        mock_get_client,
    )

    result = await get_job_logs(run_context, job_id=123456)

    assert "[Logs unavailable:" in result
    assert "API rate limit exceeded" in result


def test_extract_logs_from_archive_handles_zip():
    log_content = "Test log content from zip"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("log_file.txt", log_content)
    zip_bytes = zip_buffer.getvalue()

    result = _extract_logs_from_archive(zip_bytes)

    assert result == log_content


def test_extract_logs_from_archive_handles_non_zip():
    plain_content = b"Plain text logs"

    result = _extract_logs_from_archive(plain_content)

    assert result == "Plain text logs"


def test_extract_logs_from_archive_handles_utf8_errors():
    invalid_utf8 = b"Valid text \xff\xfe invalid UTF-8"

    result = _extract_logs_from_archive(invalid_utf8)

    assert "Valid text" in result
    assert "invalid UTF-8" in result
