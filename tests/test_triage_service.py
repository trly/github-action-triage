from unittest.mock import AsyncMock

import pytest

from github_action_triage.agent.ports import (
    GitHubContextProvider,
    IssueCreator,
    RemediationAgent,
)
from github_action_triage.app.api import TriageService
from github_action_triage.app.events.models import (
    FailureSummary,
    RepositoryRef,
    WorkflowRef,
    WorkflowRunFailureEvent,
)
from github_action_triage.app.events.outcomes import TriageOutcome


@pytest.mark.asyncio
async def test_triage_service_contract():
    from github_action_triage.agent.ports import FailureContext

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

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
        job_id="456",
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
        issue_creator=mock_issue_creator,
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
        issue_title="Test issue",
        identified_issue="Test issue",
        fix_effort="small",
        remediation_plan="Test plan",
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
    mock_issue_creator = AsyncMock(spec=IssueCreator)

    service = TriageService(
        context_provider=mock_context_provider,
        agent=mock_agent,
        issue_creator=mock_issue_creator,
    )

    assert service is not None


@pytest.mark.asyncio
async def test_process_failure_creates_issue_only():
    """Verify process_failure_async creates issue without applying fix."""
    from github_action_triage.agent.ports import FailureContext, RemediationProposal

    mock_context_provider = AsyncMock(spec=GitHubContextProvider)
    mock_agent = AsyncMock(spec=RemediationAgent)
    mock_issue_creator = AsyncMock(spec=IssueCreator)

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
        job_id="456",
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
        logs_excerpt="Error: build failed",
        recent_commits=["abc123"],
    )
    mock_context_provider.fetch_failure_context.return_value = mock_context

    mock_proposal = RemediationProposal(
        issue_title="Test failure in authentication",
        identified_issue="Test failure in authentication",
        fix_effort="small",
        remediation_plan="1. Fix test\n2. Verify",
    )
    mock_agent.diagnose_and_propose.return_value = mock_proposal

    mock_issue_creator.create_issue_for_proposal.return_value = (
        "https://github.com/test-org/test-repo/issues/123"
    )

    service = TriageService(
        context_provider=mock_context_provider, agent=mock_agent, issue_creator=mock_issue_creator
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

    await service.process_failure_async(event)

    mock_context_provider.fetch_failure_context.assert_called_once_with(event)
    mock_agent.diagnose_and_propose.assert_called_once_with(mock_context)
    mock_issue_creator.create_issue_for_proposal.assert_called_once_with(event, mock_proposal)
