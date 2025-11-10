import logging
from typing import TypeGuard
from githubkit.versions.latest.models import WebhookWorkflowJobCompleted
from githubkit.versions.latest.webhooks import WebhookEvent
from github_action_triage.app.events.models import (
    WorkflowRunFailureEvent,
    RepositoryRef,
    WorkflowRef,
    FailureSummary,
)

logger = logging.getLogger("github_action_triage.webhooks")


def is_failure_workflow_job(
    event: WebhookEvent,
) -> TypeGuard[WebhookWorkflowJobCompleted]:
    return (
        isinstance(event, WebhookWorkflowJobCompleted)
        and event.workflow_job.conclusion == "failure"
    )


def log_workflow_job_failure(event: WebhookWorkflowJobCompleted) -> None:
    logger.info(
        "workflow_job.completed.failure",
        extra={
            "repository": event.repository.full_name,
            "run_id": event.workflow_job.run_id,
            "job_id": event.workflow_job.id,
            "job_name": event.workflow_job.name,
            "conclusion": event.workflow_job.conclusion,
            "run_url": event.workflow_job.run_url,
        },
    )


def map_workflow_job_event(
    event: WebhookWorkflowJobCompleted,
) -> WorkflowRunFailureEvent:
    """Convert GitHub webhook event to domain event."""
    owner, repo = event.repository.full_name.split("/")
    
    # Extract workflow name from event or use job name as fallback
    workflow_name = getattr(event.workflow_job, "workflow_name", event.workflow_job.name)
    
    return WorkflowRunFailureEvent(
        installation_id=event.installation.id if event.installation else 0,
        repository=RepositoryRef(owner=owner, name=repo),
        workflow=WorkflowRef(
            run_id=str(event.workflow_job.run_id),
            job_id=str(event.workflow_job.id),
            workflow_name=workflow_name,
            job_name=event.workflow_job.name,
            run_url=event.workflow_job.run_url,
        ),
        failure=FailureSummary(
            conclusion=event.workflow_job.conclusion or "failure",
            logs_snippet=f"Job {event.workflow_job.name} failed",
        ),
    )

