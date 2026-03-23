import asyncio
import logging
from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from celery import Task

from github_action_triage.agent.analysis.agent import TriageAgent
from github_action_triage.agent.analysis.tools.deepsearch import DeepSearchResult
from github_action_triage.agent.config import get_settings
from github_action_triage.agent.ports import FailureContext, RemediationProposal
from github_action_triage.app.celery_app import app
from github_action_triage.app.infra.github_issue_creator import (
    GitHubIssueCreatorAdapter,
)
from github_action_triage.app.infra.redis_client import set_if_not_exists

logger = logging.getLogger(__name__)


def _log_deep_search_telemetry(
    result: DeepSearchResult | None, task_id: str, delivery_id: str, repo: str
) -> None:
    """Log Deep Search conversation telemetry when analysis completes."""
    if result is None:
        return

    logger.info(
        f"Deep Search telemetry for task_id={task_id}, delivery_id={delivery_id}, repo={repo}: "
        f"conversation={result.conversation_name}, "
        f"url={result.conversation_url}, "
        f"polls={result.poll_count}, "
        f"elapsed={result.elapsed_seconds:.1f}s"
    )


def _log_proposal_markdown(
    proposal: RemediationProposal, task_id: str, delivery_id: str, repo: str
) -> None:
    """Log RemediationProposal as formatted markdown when not creating issues."""
    involved_files_md = (
        "\n".join(f"- `{f}`" for f in proposal.involved_files)
        if proposal.involved_files
        else "- None"
    )

    proposal_md = f"""
# Remediation Proposal

**Task ID:** {task_id}
**Delivery ID:** {delivery_id}
**Repository:** {repo}

## Issue Title

{proposal.issue_title}

## Identified Issue

{proposal.identified_issue}

## Fix Effort

**{proposal.fix_effort}**

## Remediation Plan

{proposal.remediation_plan}

## Involved Files

{involved_files_md}
"""

    logger.info(
        f"RemediationProposal (issue creation disabled) for task_id={task_id}, "
        f"delivery_id={delivery_id}, repo={repo}:\n{proposal_md}"
    )


class TriageTask(Task):
    autoretry_for = ()
    time_limit = 630
    soft_time_limit = 600

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ARG002
        from github_action_triage.tasks import dead_letter

        delivery_id = kwargs.get("github_delivery_id", "unknown")
        context_dict = kwargs.get("context", {})
        repo = context_dict.get("repository_full_name", "unknown")
        logger.error(
            f"Task {task_id} failed for delivery_id={delivery_id}, repo={repo}: {exc}",
            exc_info=einfo,
        )

        dead_letter.send_to_dead_letter_queue.delay(  # type: ignore[attr-defined]
            task_id=task_id,
            task_name=self.name,
            _args=args,
            _kwargs=kwargs,
            exception=str(exc),
            traceback=str(einfo),
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

    if github_delivery_id and self.request.retries == 0:
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
        agent = TriageAgent()

        proposal = asyncio.run(agent.diagnose_and_propose(failure_context))

        # Log Deep Search telemetry
        _log_deep_search_telemetry(agent._last_deep_search_result, task_id, delivery_id, repo)

        logger.info(
            f"Triage analysis completed: task_id={task_id}, "
            f"delivery_id={delivery_id}, repo={repo}, "
            f"issue_title={proposal.issue_title}"
        )

        issue_creator = GitHubIssueCreatorAdapter(settings)
        issue_url = asyncio.run(
            issue_creator.create_issue_for_proposal(failure_context.event, proposal)
        )

        if settings.disable_issue_creation:
            _log_proposal_markdown(proposal, task_id, delivery_id, repo)

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
