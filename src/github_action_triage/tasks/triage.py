import asyncio
import logging
from collections import Counter
from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from celery import Task

from github_action_triage.agent.analysis.agent import TriageAgent
from github_action_triage.agent.config import get_settings
from github_action_triage.agent.ports import FailureContext, RemediationProposal
from github_action_triage.app.celery_app import app
from github_action_triage.app.infra.github_issue_creator import (
    GitHubIssueCreatorAdapter,
)
from github_action_triage.app.infra.redis_client import set_if_not_exists

logger = logging.getLogger(__name__)


def _log_tool_usage(result: Any, task_id: str, delivery_id: str, repo: str) -> None:
    """Log tool usage statistics as a table when worker completes."""
    tool_calls = Counter()

    # Count tool calls from all messages in the conversation
    for message in result.all_messages():
        if hasattr(message, "parts"):
            for part in message.parts:
                if hasattr(part, "tool_name"):
                    tool_calls[part.tool_name] += 1

    if not tool_calls:
        logger.info(
            f"No tool calls made for task_id={task_id}, delivery_id={delivery_id}, repo={repo}"
        )
        return

    # Build markdown table
    total_calls = sum(tool_calls.values())
    table_rows = [
        "| Tool | Calls | % |",
        "|------|------:|--:|",
    ]

    for tool_name, count in sorted(tool_calls.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total_calls) * 100
        table_rows.append(f"| `{tool_name}` | {count} | {percentage:.1f}% |")

    table_rows.append(f"| **Total** | **{total_calls}** | **100.0%** |")

    tool_usage_table = "\n".join(table_rows)

    logger.info(
        f"Tool usage summary for task_id={task_id}, delivery_id={delivery_id}, repo={repo}:\n"
        f"{tool_usage_table}"
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


def _build_analysis_prompt(context: FailureContext) -> str:
    """Build analysis prompt for the agent."""
    job_steps_summary = "\n".join(
        f"  {step['number']}. {step['name']} - {step['status']} ({step['conclusion']})"
        for step in context.job_steps
    )

    return f"""Analyze the GitHub Actions workflow failure:

**Repository:** {context.repository_full_name}
**Branch:** {context.branch_ref}
**Commit:** {context.head_commit_sha}
**Job ID:** {context.job_id}
**Job URL:** {context.job_html_url}

**Workflow:** {context.event.workflow.workflow_name} / {context.event.workflow.job_name}

**Job Steps:**
{job_steps_summary}

**Logs Excerpt:**
```
{context.logs_excerpt}
```

Use get_job_logs() if you need the complete logs for deeper analysis.

Diagnose the failure and provide a comprehensive remediation proposal."""


def _build_github_context(agent: TriageAgent, context: FailureContext) -> Any:
    """Build GitHub tool context for the agent."""
    from github_action_triage.agent.analysis.github import GitHubToolContext

    return GitHubToolContext(
        settings=agent.settings,
        owner=context.event.repository.owner,
        repo=context.event.repository.name,
        installation_id=context.event.installation_id,
        failure=context,
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

        result = asyncio.run(
            agent.agent.run(
                _build_analysis_prompt(failure_context),
                deps=_build_github_context(agent, failure_context),
            )
        )

        proposal = result.output

        # Log tool usage statistics
        _log_tool_usage(result, task_id, delivery_id, repo)

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
