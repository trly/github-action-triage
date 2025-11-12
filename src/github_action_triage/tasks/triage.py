import asyncio
import logging
from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from celery import Task

from github_action_triage.agent.ai_agent import ActionTriageAgent
from github_action_triage.agent.config import get_settings
from github_action_triage.agent.ports import FailureContext
from github_action_triage.app.celery_app import app
from github_action_triage.app.infra.github_issue_creator import GitHubIssueCreatorAdapter
from github_action_triage.app.infra.redis_client import set_if_not_exists

logger = logging.getLogger(__name__)


class TriageTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 300
    time_limit = 630
    soft_time_limit = 600

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ARG002
        delivery_id = kwargs.get("github_delivery_id", "unknown")
        context_dict = kwargs.get("context", {})
        repo = context_dict.get("repository_full_name", "unknown")
        logger.error(
            f"Task {task_id} failed for delivery_id={delivery_id}, repo={repo}: {exc}",
            exc_info=einfo,
        )


@app.task(base=TriageTask, bind=True)
def analyze_workflow_failure(
    self: Task, context: dict[str, Any], github_delivery_id: str | None = None
) -> dict[str, Any]:
    task_id = self.request.id
    delivery_id = github_delivery_id or "none"
    repo = context.get("repository_full_name", "unknown")

    logger.info(
        f"Starting triage analysis: task_id={task_id}, delivery_id={delivery_id}, repo={repo}"
    )

    if github_delivery_id:
        dedupe_key = f"triage:delivery:{github_delivery_id}"
        ttl_seconds = 86400
        if not set_if_not_exists(dedupe_key, task_id, ttl_seconds):
            logger.info(
                f"Skipping duplicate delivery: task_id={task_id}, "
                f"delivery_id={delivery_id}, repo={repo}"
            )
            return {"status": "skipped", "reason": "duplicate_delivery"}

    try:
        failure_context = FailureContext.model_validate(context)
        settings = get_settings()
        agent = ActionTriageAgent(settings)

        proposal = asyncio.run(agent.diagnose_and_propose(failure_context))

        logger.info(
            f"Triage analysis completed: task_id={task_id}, "
            f"delivery_id={delivery_id}, repo={repo}, issue_title={proposal.issue_title}"
        )

        issue_creator = GitHubIssueCreatorAdapter(settings)
        issue_url = asyncio.run(issue_creator.create_issue_for_proposal(failure_context, proposal))

        logger.info(
            f"GitHub issue created: task_id={task_id}, "
            f"delivery_id={delivery_id}, repo={repo}, issue_url={issue_url}"
        )

        return {**proposal.model_dump(), "issue_url": issue_url}

    except (SoftTimeLimitExceeded, TimeoutError) as e:
        logger.warning(
            f"Triage analysis timed out: task_id={task_id}, "
            f"delivery_id={delivery_id}, repo={repo}: {e}"
        )
        raise

    except Exception as e:
        logger.error(
            f"Triage analysis failed: task_id={task_id}, "
            f"delivery_id={delivery_id}, repo={repo}: {e}",
            exc_info=True,
        )
        raise
