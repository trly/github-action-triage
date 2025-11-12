from github_action_triage.agent.ports import FailureContext
from github_action_triage.app.events.models import (
    FailureSummary,
    RepositoryRef,
    WorkflowRef,
    WorkflowRunFailureEvent,
)


def test_failure_event_supports_run_metadata():
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
    assert event.workflow.run_id == "123"
    assert event.workflow.job_id == "456"
    assert event.installation_id == 12345
    assert event.repository.owner == "test-org"


def test_failure_summary_captures_logs():
    summary = FailureSummary(
        conclusion="failure",
        logs_snippet="TypeError: Cannot read property 'foo' of undefined",
    )
    assert "TypeError" in summary.logs_snippet
    assert summary.conclusion == "failure"


def test_repository_ref_immutability():
    repo = RepositoryRef(owner="acme", name="widget")
    assert repo.owner == "acme"
    assert repo.name == "widget"


def test_failure_context_captures_enriched_metadata():
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

    context = FailureContext(
        event=event,
        job_id=456,
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123def456",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
        logs_excerpt="Error: npm install failed\n  at install.js:42",
        workflow_file_path=None,
        recent_commits=["abc123def456"],
    )

    assert context.repository_full_name == "test-org/test-repo"
    assert context.head_commit_sha == "abc123def456"
    assert context.branch_ref == "refs/heads/main"
    assert context.job_html_url.endswith("/job/456")
    assert "Error: npm install failed" in context.logs_excerpt
