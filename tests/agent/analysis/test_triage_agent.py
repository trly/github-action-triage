import io
import zipfile
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from github_action_triage.agent.analysis.agent import TriageAgent
from github_action_triage.agent.analysis.tools.github import GitHubToolContext
from github_action_triage.agent.ports import (
    FailureContext,
    FailureSummary,
    RemediationProposal,
    RepositoryRef,
    WorkflowRef,
    WorkflowRunFailureEvent,
)


@pytest.fixture
def failure_context():
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
            logs_snippet="Error: npm install failed",
        ),
    )
    return FailureContext(
        event=event,
        job_id=456,
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
        logs_excerpt="Error: npm install failed\nExpected package-lock.json",
    )


@pytest.fixture
def mock_settings():
    with (
        patch("github_action_triage.agent.analysis.agent.get_settings") as mock_get_settings,
        patch(
            "github_action_triage.agent.analysis.agent.get_analysis_settings"
        ) as mock_get_analysis_settings,
    ):
        settings = Mock()
        settings.anthropic_api_key = Mock()
        settings.anthropic_api_key.get_secret_value.return_value = "test-api-key"
        settings.github_app_id = "12345"
        settings.github_private_key = "test-private-key"

        analysis_settings = Mock()
        analysis_settings.model = "anthropic:claude-sonnet-4-5"
        analysis_settings.timeout_seconds = 300

        mock_get_settings.return_value = settings
        mock_get_analysis_settings.return_value = analysis_settings

        yield settings


@pytest.mark.asyncio
async def test_triage_agent_initialization(mock_settings):
    agent = TriageAgent()

    assert agent.settings is not None
    assert agent.analysis_settings is not None
    assert agent.agent is not None


@pytest.mark.asyncio
async def test_diagnose_and_propose_returns_remediation_proposal(mock_settings, failure_context):
    expected_proposal = RemediationProposal(
        issue_title="npm install failed - missing package-lock.json",
        identified_issue="Workflow failed because package-lock.json is missing",
        fix_effort="small",
        remediation_plan="1. Run npm install locally\n2. Commit package-lock.json",
        job_metadata={
            "id": 456,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": "abc123",
            "head_branch": "main",
            "html_url": "https://github.com/test-org/test-repo/actions/runs/123/job/456",
            "steps": [],
        },
        involved_files=["package.json", ".github/workflows/ci.yml"],
    )

    mock_result = Mock()
    mock_result.output = expected_proposal

    agent = TriageAgent()
    agent.agent.run = AsyncMock(return_value=mock_result)

    result = await agent.diagnose_and_propose(failure_context)

    assert isinstance(result, RemediationProposal)
    assert result.issue_title == expected_proposal.issue_title
    assert result.identified_issue == expected_proposal.identified_issue
    assert result.fix_effort == expected_proposal.fix_effort
    assert result.remediation_plan == expected_proposal.remediation_plan
    assert result.job_metadata == expected_proposal.job_metadata
    assert result.involved_files == expected_proposal.involved_files

    agent.agent.run.assert_called_once()


@pytest.mark.asyncio
async def test_diagnose_and_propose_includes_context_in_prompt(mock_settings, failure_context):
    expected_proposal = RemediationProposal(
        issue_title="Test issue",
        identified_issue="Test issue",
        fix_effort="small",
        remediation_plan="Test plan",
    )

    mock_result = Mock()
    mock_result.output = expected_proposal

    agent = TriageAgent()
    agent.agent.run = AsyncMock(return_value=mock_result)

    await agent.diagnose_and_propose(failure_context)

    call_args = agent.agent.run.call_args
    prompt = call_args[0][0]

    assert "test-org/test-repo" in prompt
    assert "main" in prompt
    assert "abc123" in prompt
    assert str(failure_context.job_id) in prompt
    assert "CI" in prompt
    assert "build" in prompt


@pytest.mark.asyncio
async def test_diagnose_and_propose_passes_github_context_to_tools(mock_settings, failure_context):
    expected_proposal = RemediationProposal(
        issue_title="Test",
        identified_issue="Test",
        fix_effort="small",
        remediation_plan="Test",
    )

    mock_result = Mock()
    mock_result.output = expected_proposal

    agent = TriageAgent()
    agent.agent.run = AsyncMock(return_value=mock_result)

    await agent.diagnose_and_propose(failure_context)

    call_args = agent.agent.run.call_args
    github_context = call_args[1]["deps"]

    assert github_context.owner == "test-org"
    assert github_context.repo == "test-repo"
    assert github_context.installation_id == 12345
    assert github_context.settings is not None


@pytest.mark.asyncio
async def test_remediation_proposal_validates_fix_effort():
    with pytest.raises(ValidationError):
        RemediationProposal(
            issue_title="Test",
            identified_issue="Test issue",
            fix_effort="extra_large",  # type: ignore[arg-type]
            remediation_plan="Test plan",
        )

    valid_proposal = RemediationProposal(
        issue_title="Test",
        identified_issue="Test issue",
        fix_effort="small",
        remediation_plan="Test plan",
    )
    assert valid_proposal.fix_effort == "small"

    valid_proposal2 = RemediationProposal(
        issue_title="Test",
        identified_issue="Test issue",
        fix_effort="medium",
        remediation_plan="Test plan",
    )
    assert valid_proposal2.fix_effort == "medium"

    valid_proposal3 = RemediationProposal(
        issue_title="Test",
        identified_issue="Test issue",
        fix_effort="large",
        remediation_plan="Test plan",
    )
    assert valid_proposal3.fix_effort == "large"


@pytest.mark.asyncio
async def test_remediation_proposal_optional_fields_default():
    proposal = RemediationProposal(
        issue_title="Test",
        identified_issue="Test issue",
        fix_effort="small",
        remediation_plan="Test plan",
    )

    assert proposal.job_metadata == {}
    assert proposal.involved_files == []


@pytest.mark.asyncio
async def test_diagnose_and_propose_with_all_fields_populated(mock_settings, failure_context):
    expected_proposal = RemediationProposal(
        issue_title="Ruff linting errors",
        identified_issue="Multiple Python files have linting violations",
        fix_effort="medium",
        remediation_plan="1. Run ruff check --fix\n2. Review changes\n3. Commit fixes",
        job_metadata={
            "id": 456,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": "abc123",
            "head_branch": "main",
            "html_url": "https://github.com/test-org/test-repo/actions/runs/123/job/456",
            "steps": [
                {
                    "name": "Lint",
                    "status": "completed",
                    "conclusion": "failure",
                    "number": 3,
                }
            ],
        },
        involved_files=[
            "src/main.py",
            "src/utils.py",
            "tests/test_main.py",
        ],
    )

    mock_result = Mock()
    mock_result.output = expected_proposal

    agent = TriageAgent()
    agent.agent.run = AsyncMock(return_value=mock_result)

    result = await agent.diagnose_and_propose(failure_context)

    assert result.issue_title == "Ruff linting errors"
    assert result.job_metadata["head_sha"] == "abc123"
    assert result.job_metadata["head_branch"] == "main"
    assert len(result.job_metadata["steps"]) == 1
    assert len(result.involved_files) == 3
    assert "src/main.py" in result.involved_files


@pytest.mark.asyncio
async def test_tools_are_registered_with_correct_schema(mock_settings):
    """Validate that get_job and get_job_logs tools are registered with correct schemas."""
    agent = TriageAgent()

    # Access the function toolset tools dict
    toolset = agent.agent._function_toolset
    tools = list(toolset.tools.values())

    assert len(tools) == 2

    # Check get_job tool
    get_job_tool = next((t for t in tools if t.name == "get_job"), None)
    assert get_job_tool is not None
    assert get_job_tool.description is not None
    assert "GitHub Actions job" in str(get_job_tool.description)
    # Verify parameter description is in json_schema
    assert "job_id" in get_job_tool.function_schema.json_schema["properties"]
    assert (
        "job ID from the webhook"
        in get_job_tool.function_schema.json_schema["properties"]["job_id"]["description"]
    )

    # Check get_job_logs tool
    get_job_logs_tool = next((t for t in tools if t.name == "get_job_logs"), None)
    assert get_job_logs_tool is not None
    assert get_job_logs_tool.description is not None
    assert "logs" in str(get_job_logs_tool.description).lower()
    # Verify parameter description is in json_schema
    assert "job_id" in get_job_logs_tool.function_schema.json_schema["properties"]
    assert (
        "job ID from the webhook"
        in get_job_logs_tool.function_schema.json_schema["properties"]["job_id"]["description"]
    )


@pytest.mark.asyncio
async def test_get_installation_client_uses_context_deps(mock_settings):
    """Test that _get_installation_client properly uses RunContext deps."""

    agent = TriageAgent()

    # Create a mock context
    mock_ctx = Mock()
    mock_ctx.deps = Mock(spec=GitHubToolContext)
    mock_ctx.deps.settings = mock_settings
    mock_ctx.deps.installation_id = 12345

    # Mock GitHub client
    mock_token_response = Mock()
    mock_token_response.parsed_data = Mock()
    mock_token_response.parsed_data.token = "installation-token-123"

    with (
        patch("github_action_triage.agent.analysis.agent.GitHub") as MockGitHub,
        patch("github_action_triage.agent.analysis.agent.AppAuthStrategy") as MockAppAuthStrategy,
    ):
        mock_github_instance = AsyncMock()
        mock_github_instance.rest.apps.async_create_installation_access_token.return_value = (
            mock_token_response
        )
        MockGitHub.side_effect = [mock_github_instance, Mock()]

        await agent._get_installation_client(mock_ctx)

        # Verify AppAuthStrategy was called with settings from context
        MockAppAuthStrategy.assert_called_once_with(
            app_id=mock_settings.github_app_id,
            private_key=mock_settings.github_private_key,
        )

        # Verify installation token was requested
        mock_github_instance.rest.apps.async_create_installation_access_token.assert_called_once_with(
            installation_id=12345
        )

        # Verify GitHub client was created with token
        assert MockGitHub.call_count == 2
        MockGitHub.assert_any_call("installation-token-123")


def test_extract_logs_from_archive_handles_zip():
    """Test that _extract_logs_from_archive extracts from zip format."""
    # Create a zip archive with log content
    log_content = b"Test log line 1\nTest log line 2\n"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("job.log", log_content)
    zip_bytes = zip_buffer.getvalue()

    result = TriageAgent._extract_logs_from_archive(zip_bytes)

    assert result == "Test log line 1\nTest log line 2\n"


def test_extract_logs_from_archive_handles_non_zip():
    """Test that _extract_logs_from_archive handles non-zip bytes."""
    raw_bytes = b"Raw log content\n"

    result = TriageAgent._extract_logs_from_archive(raw_bytes)

    assert result == "Raw log content\n"


def test_extract_logs_from_archive_handles_utf8_errors():
    """Test that _extract_logs_from_archive handles invalid UTF-8."""
    invalid_bytes = b"Valid text\xff\xfeInvalid UTF-8"

    result = TriageAgent._extract_logs_from_archive(invalid_bytes)

    # Should decode with replacement characters
    assert "Valid text" in result
