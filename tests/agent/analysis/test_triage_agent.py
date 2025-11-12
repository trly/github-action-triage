import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, Mock, patch

from github_action_triage.agent.analysis.agent import TriageAgent
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
    with patch("github_action_triage.agent.analysis.agent.get_settings") as mock_get_settings, \
         patch("github_action_triage.agent.analysis.agent.get_analysis_settings") as mock_get_analysis_settings:
        
        settings = Mock()
        settings.anthropic_api_key = Mock()
        settings.anthropic_api_key.get_secret_value.return_value = "test-api-key"
        settings.sourcegraph_token = None
        settings.sourcegraph_mcp_url = None
        
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
async def test_triage_agent_initialization_without_sourcegraph(mock_settings):
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_sg.return_value = None
        
        agent = TriageAgent()
        
        assert agent.agent is not None
        assert mock_sg.call_count == 2


@pytest.mark.asyncio
async def test_triage_agent_initialization_with_sourcegraph(mock_settings):
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_toolset = Mock()
        mock_sg.return_value = mock_toolset
        
        agent = TriageAgent()
        
        assert agent.agent is not None
        assert mock_sg.call_count == 2


@pytest.mark.asyncio
async def test_prepare_does_nothing(mock_settings, failure_context):
    agent = TriageAgent()
    
    await agent.prepare(failure_context)


@pytest.mark.asyncio
async def test_diagnose_and_propose_returns_remediation_proposal(mock_settings, failure_context):
    expected_proposal = RemediationProposal(
        issue_title="npm install failed - missing package-lock.json",
        identified_issue="Workflow failed because package-lock.json is missing from repository",
        fix_effort="small",
        remediation_plan="1. Run npm install locally\n2. Commit package-lock.json\n3. Push to repository",
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
    
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_sg.return_value = None
        
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
    
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_sg.return_value = None
        
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
    
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_sg.return_value = None
        
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
async def test_system_prompt_includes_sourcegraph_instructions_when_enabled(mock_settings):
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_toolset = Mock()
        mock_sg.return_value = mock_toolset
        
        agent = TriageAgent()
        system_prompt = agent._build_system_prompt()
        
        assert "Sourcegraph MCP" in system_prompt
        assert "sg_read_file" in system_prompt
        assert "sg_keyword_search" in system_prompt
        assert "sg_go_to_definition" in system_prompt
        assert "revision parameter" in system_prompt


@pytest.mark.asyncio
async def test_system_prompt_excludes_sourcegraph_when_disabled(mock_settings):
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_sg.return_value = None
        
        agent = TriageAgent()
        system_prompt = agent._build_system_prompt()
        
        assert "Sourcegraph MCP Tools Available" not in system_prompt
        assert "Use Sourcegraph MCP tools to explore" not in system_prompt


@pytest.mark.asyncio
async def test_system_prompt_requires_all_output_fields():
    with patch("github_action_triage.agent.analysis.agent.get_settings") as mock_get_settings, \
         patch("github_action_triage.agent.analysis.agent.get_analysis_settings") as mock_get_analysis_settings, \
         patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        
        settings = Mock()
        settings.anthropic_api_key = Mock()
        settings.anthropic_api_key.get_secret_value.return_value = "test-key"
        
        analysis_settings = Mock()
        analysis_settings.model = "anthropic:claude-sonnet-4-5"
        
        mock_get_settings.return_value = settings
        mock_get_analysis_settings.return_value = analysis_settings
        mock_sg.return_value = None
        
        agent = TriageAgent()
        system_prompt = agent._build_system_prompt()
        
        assert "issue_title" in system_prompt
        assert "identified_issue" in system_prompt
        assert "fix_effort" in system_prompt
        assert "remediation_plan" in system_prompt
        assert "job_metadata" in system_prompt
        assert "involved_files" in system_prompt


@pytest.mark.asyncio
async def test_remediation_proposal_validates_fix_effort():
    with pytest.raises(ValidationError):
        RemediationProposal(
            issue_title="Test",
            identified_issue="Test issue",
            fix_effort="invalid",
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
                {"name": "Lint", "status": "completed", "conclusion": "failure", "number": 3}
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
    
    with patch("github_action_triage.agent.analysis.agent.create_sourcegraph_toolset") as mock_sg:
        mock_sg.return_value = None
        
        agent = TriageAgent()
        agent.agent.run = AsyncMock(return_value=mock_result)
        
        result = await agent.diagnose_and_propose(failure_context)
        
        assert result.issue_title == "Ruff linting errors"
        assert result.job_metadata["head_sha"] == "abc123"
        assert result.job_metadata["head_branch"] == "main"
        assert len(result.job_metadata["steps"]) == 1
        assert len(result.involved_files) == 3
        assert "src/main.py" in result.involved_files
