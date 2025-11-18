"""Unit tests for Celery triage task."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from github_action_triage.agent.ports import FailureContext, RemediationProposal
from github_action_triage.tasks.triage import TriageTask, analyze_workflow_failure


@pytest.fixture
def failure_context_dict():
    """Sample FailureContext as dict for Celery serialization."""
    return {
        "event": {
            "installation_id": 12345,
            "repository": {"owner": "test-org", "name": "test-repo"},
            "workflow": {
                "run_id": "67890",
                "job_id": "12345",
                "workflow_name": "CI",
                "job_name": "build",
                "run_url": "https://github.com/test-org/test-repo/actions/runs/67890",
            },
            "failure": {
                "conclusion": "failure",
                "logs_snippet": "Error: npm install failed",
            },
        },
        "job_id": 12345,
        "repository_full_name": "test-org/test-repo",
        "head_commit_sha": "abc123",
        "branch_ref": "refs/heads/main",
        "job_html_url": "https://github.com/test-org/test-repo/actions/runs/67890/job/12345",
        "logs_url": "https://api.github.com/repos/test-org/test-repo/actions/jobs/12345/logs",
        "logs_excerpt": "Error: npm install failed\nERROR: package-lock.json not found",
        "workflow_file_path": ".github/workflows/ci.yml",
        "recent_commits": ["abc123"],
    }


@pytest.fixture
def remediation_proposal():
    """Sample RemediationProposal."""
    return RemediationProposal(
        issue_title="npm install failed",
        identified_issue="npm install failed due to missing package-lock.json",
        fix_effort="small",
        remediation_plan="1. Run npm install locally\n2. Commit package-lock.json\n3. Re-run workflow",
    )


def test_task_successfully_analyzes_failure(failure_context_dict, remediation_proposal):
    """Verify task successfully calls agent and returns proposal."""
    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch("github_action_triage.tasks.triage.GitHubIssueCreatorAdapter") as mock_creator_class,
        patch("github_action_triage.tasks.triage.set_if_not_exists", return_value=True),
    ):
        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.name = "get_job_logs"

        # Create mock result
        mock_result = MagicMock()
        mock_result.all_messages.return_value = []
        mock_result.output = remediation_proposal

        # Mock agent.agent.run() to be async and return mock_result
        mock_run = AsyncMock(return_value=mock_result)

        mock_agent = AsyncMock()
        mock_agent.diagnose_and_propose.return_value = remediation_proposal
        mock_agent._last_result = mock_result
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = mock_run
        mock_agent.agent.tools = [mock_tool]
        mock_agent_class.return_value = mock_agent

        mock_settings.return_value.disable_issue_creation = False
        mock_creator = AsyncMock()
        mock_creator.create_issue_for_proposal.return_value = (
            "https://github.com/test-org/test-repo/issues/1"
        )
        mock_creator_class.return_value = mock_creator

        # Call task.run() to bypass Celery infrastructure
        result = analyze_workflow_failure.run(
            context=failure_context_dict, github_delivery_id="delivery-456"
        )

        assert result["issue_title"] == "npm install failed"
        assert result["identified_issue"] == "npm install failed due to missing package-lock.json"
        assert result["fix_effort"] == "small"
        assert result["issue_url"] == "https://github.com/test-org/test-repo/issues/1"

        # Verify agent.agent.run() was called
        mock_run.assert_called_once()

        # Verify issue creator was called
        mock_creator.create_issue_for_proposal.assert_called_once()


def test_task_idempotency_prevents_duplicate_processing(failure_context_dict):
    """Verify task skips processing for duplicate delivery IDs."""
    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch(
            "github_action_triage.tasks.triage.set_if_not_exists", return_value=False
        ) as mock_setnx,
    ):
        result = analyze_workflow_failure.run(
            context=failure_context_dict, github_delivery_id="delivery-456"
        )

        # Verify task returned skip status
        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate_delivery"

        # Verify Redis was checked with correct key and TTL
        assert mock_setnx.call_count == 1
        call_args = mock_setnx.call_args[0]
        assert call_args[0] == "triage:delivery:delivery-456"
        assert call_args[2] == 86400  # TTL is 24 hours

        # Verify agent was NOT called
        mock_agent_class.assert_not_called()


def test_task_processes_when_no_delivery_id(failure_context_dict, remediation_proposal):
    """Verify task processes normally when github_delivery_id is None."""
    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch("github_action_triage.tasks.triage.GitHubIssueCreatorAdapter") as mock_creator_class,
        patch("github_action_triage.tasks.triage.set_if_not_exists") as mock_setnx,
    ):
        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.name = "get_job_logs"

        # Create mock result
        mock_result = MagicMock()
        mock_result.all_messages.return_value = []
        mock_result.output = remediation_proposal

        # Mock agent.agent.run() to be async and return mock_result
        mock_run = AsyncMock(return_value=mock_result)

        mock_agent = AsyncMock()
        mock_agent.diagnose_and_propose.return_value = remediation_proposal
        mock_agent._last_result = mock_result
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = mock_run
        mock_agent.agent.tools = [mock_tool]
        mock_agent_class.return_value = mock_agent

        mock_settings.return_value.disable_issue_creation = False
        mock_creator = AsyncMock()
        mock_creator.create_issue_for_proposal.return_value = (
            "https://github.com/test-org/test-repo/issues/1"
        )
        mock_creator_class.return_value = mock_creator

        result = analyze_workflow_failure.run(context=failure_context_dict, github_delivery_id=None)

        # Verify task completed successfully
        assert result["issue_title"] == "npm install failed"
        assert result["issue_url"] == "https://github.com/test-org/test-repo/issues/1"

        # Verify Redis was NOT checked (no delivery ID)
        mock_setnx.assert_not_called()

        # Verify agent.agent.run() was called
        mock_run.assert_called_once()

        # Verify issue creator was called
        mock_creator.create_issue_for_proposal.assert_called_once()


def test_task_handles_soft_timeout(failure_context_dict):
    """Verify task propagates SoftTimeLimitExceeded for retry logic."""
    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch("github_action_triage.tasks.triage.set_if_not_exists", return_value=True),
    ):
        # Mock agent.agent.run() to raise timeout
        mock_run = AsyncMock(side_effect=SoftTimeLimitExceeded())
        
        mock_agent = AsyncMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = mock_run
        mock_agent_class.return_value = mock_agent

        with pytest.raises(SoftTimeLimitExceeded):
            analyze_workflow_failure.run(
                context=failure_context_dict, github_delivery_id="delivery-456"
            )


def test_task_handles_generic_exception(failure_context_dict):
    """Verify task propagates generic exceptions for retry logic."""
    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch("github_action_triage.tasks.triage.set_if_not_exists", return_value=True),
    ):
        # Mock agent.agent.run() to raise error
        mock_run = AsyncMock(side_effect=RuntimeError("AI service unavailable"))
        
        mock_agent = AsyncMock()
        mock_agent.agent = MagicMock()
        mock_agent.agent.run = mock_run
        mock_agent_class.return_value = mock_agent

        with pytest.raises(RuntimeError, match="AI service unavailable"):
            analyze_workflow_failure.run(
                context=failure_context_dict, github_delivery_id="delivery-456"
            )


def test_task_configuration():
    """Verify TriageTask has correct retry and timeout configuration."""
    assert TriageTask.autoretry_for == ()
    assert TriageTask.time_limit == 630
    assert TriageTask.soft_time_limit == 600


def test_task_on_failure_callback(caplog):
    """Verify on_failure callback logs task failures correctly."""
    import logging

    caplog.set_level(logging.ERROR)

    task = TriageTask()
    exc = RuntimeError("Test error")
    task_id = "task-123"
    kwargs = {
        "github_delivery_id": "delivery-456",
        "context": {"repository_full_name": "test-org/test-repo"},
    }

    class FakeEinfo:
        pass

    with patch("github_action_triage.tasks.dead_letter.send_to_dead_letter_queue"):
        task.on_failure(exc, task_id, [], kwargs, FakeEinfo())

    assert "Task task-123 failed" in caplog.text
    assert "delivery_id=delivery-456" in caplog.text
    assert "repo=test-org/test-repo" in caplog.text


def test_task_validates_failure_context(failure_context_dict, remediation_proposal):
    """Verify task validates FailureContext from dict before processing."""
    # Introduce invalid data (missing required field)
    invalid_context = failure_context_dict.copy()
    del invalid_context["repository_full_name"]

    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch("github_action_triage.tasks.triage.set_if_not_exists", return_value=True),
    ):
        mock_request = MagicMock()
        mock_request.id = "task-123"

        with pytest.raises(Exception):  # noqa: B017
            analyze_workflow_failure(
                mock_request, context=invalid_context, github_delivery_id="delivery-456"
            )


def test_task_redis_error_propagates(failure_context_dict):
    """Verify Redis errors are propagated for retry handling."""
    import redis

    with (
        patch("github_action_triage.tasks.triage.get_settings") as mock_settings,
        patch("github_action_triage.tasks.triage.TriageAgent") as mock_agent_class,
        patch("github_action_triage.tasks.triage.set_if_not_exists") as mock_setnx,
    ):
        mock_setnx.side_effect = redis.RedisError("Connection failed")

        with pytest.raises(redis.RedisError, match="Connection failed"):
            analyze_workflow_failure.run(
                context=failure_context_dict, github_delivery_id="delivery-456"
            )
