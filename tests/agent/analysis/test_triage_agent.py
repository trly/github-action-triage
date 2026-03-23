import io
import json
import zipfile
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from github_action_triage.agent.analysis.agent import TriageAgent
from github_action_triage.agent.analysis.github import extract_logs_from_archive
from github_action_triage.agent.analysis.tools.deepsearch import DeepSearchResult
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
        settings.sourcegraph_url = "https://sourcegraph.example.com"
        settings.sourcegraph_token = Mock()
        settings.sourcegraph_token.get_secret_value.return_value = "sgp_test"

        analysis_settings = Mock()
        analysis_settings.model = "anthropic:claude-sonnet-4-5"
        analysis_settings.timeout_seconds = 300

        mock_get_settings.return_value = settings
        mock_get_analysis_settings.return_value = analysis_settings

        yield settings


def _make_deep_search_result(answer_markdown: str) -> DeepSearchResult:
    """Helper to create a DeepSearchResult with given markdown."""
    return DeepSearchResult(
        conversation_name="users/test/conversations/conv-123",
        conversation_url="https://sourcegraph.example.com/deepsearch/conv-123",
        answer_markdown=answer_markdown,
        poll_count=3,
        elapsed_seconds=15.0,
    )


@pytest.mark.asyncio
async def test_triage_agent_initialization(mock_settings):
    agent = TriageAgent()

    assert agent.settings is not None
    assert agent.analysis_settings is not None


@pytest.mark.asyncio
async def test_diagnose_and_propose_returns_remediation_proposal(mock_settings, failure_context):
    proposal_json = json.dumps({
        "issue_title": "npm install failed - missing package-lock.json",
        "identified_issue": "Workflow failed because package-lock.json is missing",
        "fix_effort": "small",
        "remediation_plan": "1. Run npm install locally\n2. Commit package-lock.json",
        "involved_files": ["package.json", ".github/workflows/ci.yml"],
    })
    answer_md = f"Here is my analysis:\n\n```json\n{proposal_json}\n```"
    ds_result = _make_deep_search_result(answer_md)

    with patch(
        "github_action_triage.agent.analysis.agent.run_deep_search",
        new_callable=AsyncMock,
        return_value=ds_result,
    ):
        agent = TriageAgent()
        result = await agent.diagnose_and_propose(failure_context)

    assert isinstance(result, RemediationProposal)
    assert result.issue_title == "npm install failed - missing package-lock.json"
    assert result.identified_issue == "Workflow failed because package-lock.json is missing"
    assert result.fix_effort == "small"
    assert result.involved_files == ["package.json", ".github/workflows/ci.yml"]


@pytest.mark.asyncio
async def test_diagnose_and_propose_includes_context_in_question(mock_settings, failure_context):
    proposal_json = json.dumps({
        "issue_title": "Test issue",
        "identified_issue": "Test issue",
        "fix_effort": "small",
        "remediation_plan": "Test plan",
        "involved_files": [],
    })
    answer_md = f"```json\n{proposal_json}\n```"
    ds_result = _make_deep_search_result(answer_md)

    with patch(
        "github_action_triage.agent.analysis.agent.run_deep_search",
        new_callable=AsyncMock,
        return_value=ds_result,
    ) as mock_ds:
        agent = TriageAgent()
        await agent.diagnose_and_propose(failure_context)

    # Verify the question passed to Deep Search contains context
    question = mock_ds.call_args[1]["question"]
    assert "test-org/test-repo" in question
    assert "main" in question
    assert "abc123" in question
    assert str(failure_context.job_id) in question
    assert "CI" in question
    assert "build" in question


@pytest.mark.asyncio
async def test_diagnose_and_propose_falls_back_on_invalid_json(mock_settings, failure_context):
    answer_md = "The build failed because of a missing dependency. Check package.json."
    ds_result = _make_deep_search_result(answer_md)

    with patch(
        "github_action_triage.agent.analysis.agent.run_deep_search",
        new_callable=AsyncMock,
        return_value=ds_result,
    ):
        agent = TriageAgent()
        result = await agent.diagnose_and_propose(failure_context)

    assert isinstance(result, RemediationProposal)
    assert "test-org/test-repo" in result.issue_title
    assert result.fix_effort == "medium"
    assert "missing dependency" in result.remediation_plan


@pytest.mark.asyncio
async def test_diagnose_stores_deep_search_result(mock_settings, failure_context):
    proposal_json = json.dumps({
        "issue_title": "Test",
        "identified_issue": "Test",
        "fix_effort": "small",
        "remediation_plan": "Test",
        "involved_files": [],
    })
    answer_md = f"```json\n{proposal_json}\n```"
    ds_result = _make_deep_search_result(answer_md)

    with patch(
        "github_action_triage.agent.analysis.agent.run_deep_search",
        new_callable=AsyncMock,
        return_value=ds_result,
    ):
        agent = TriageAgent()
        await agent.diagnose_and_propose(failure_context)

    assert agent._last_deep_search_result is not None
    assert agent._last_deep_search_result.conversation_name == "users/test/conversations/conv-123"
    assert agent._last_deep_search_result.poll_count == 3


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


@pytest.mark.asyncio
async def test_remediation_proposal_optional_fields_default():
    proposal = RemediationProposal(
        issue_title="Test",
        identified_issue="Test issue",
        fix_effort="small",
        remediation_plan="Test plan",
    )
    assert proposal.involved_files == []


def test_extract_json_from_markdown_code_block():
    markdown = '```json\n{"issue_title": "test", "identified_issue": "x", "fix_effort": "small", "remediation_plan": "y", "involved_files": []}\n```'
    result = TriageAgent._extract_json_from_markdown(markdown)
    assert result is not None
    assert result["issue_title"] == "test"


def test_extract_json_from_markdown_no_json():
    markdown = "This is just regular text with no JSON."
    result = TriageAgent._extract_json_from_markdown(markdown)
    assert result is None


def test_extract_logs_from_archive_handles_zip():
    log_content = b"Test log line 1\nTest log line 2\n"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("job.log", log_content)
    zip_bytes = zip_buffer.getvalue()

    result = extract_logs_from_archive(zip_bytes)
    assert result == "Test log line 1\nTest log line 2\n"


def test_extract_logs_from_archive_handles_non_zip():
    raw_bytes = b"Raw log content\n"
    result = extract_logs_from_archive(raw_bytes)
    assert result == "Raw log content\n"


def test_extract_logs_from_archive_handles_utf8_errors():
    invalid_bytes = b"Valid text\xff\xfeInvalid UTF-8"
    result = extract_logs_from_archive(invalid_bytes)
    assert "Valid text" in result
