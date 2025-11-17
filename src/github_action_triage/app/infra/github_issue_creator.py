import logging

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy

from github_action_triage.agent.ports import (
    IssueCreator,
    RemediationProposal,
    WorkflowRunFailureEvent,
)
from github_action_triage.app.config.settings import Settings

logger = logging.getLogger(__name__)


class GitHubIssueCreatorAdapter(IssueCreator):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = GitHub(
            AppAuthStrategy(
                app_id=settings.github_app_id,
                private_key=settings.github_private_key,
            )
        )

    async def create_issue_for_proposal(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> str:
        body = self._format_issue_body(event, proposal)
        
        # Check if issue creation is disabled (for testing)
        if self._settings.disable_issue_creation:
            logger.info(
                f"Issue creation disabled (TRIAGE_DISABLE_ISSUE_CREATION=true), "
                f"would have created issue:\n"
                f"Repository: {event.repository.owner}/{event.repository.name}\n"
                f"Title: {proposal.issue_title}\n"
                f"Labels: triage, ci"
            )
            logger.debug(f"Issue body:\n{body}")
            return f"https://github.com/{event.repository.owner}/{event.repository.name}/issues/0"
        
        response = await self._client.rest.apps.async_create_installation_access_token(
            installation_id=event.installation_id
        )
        token_response = response
        installation_client = GitHub(token_response.parsed_data.token)

        response = await installation_client.rest.issues.async_create(
            owner=event.repository.owner,
            repo=event.repository.name,
            title=proposal.issue_title,
            body=body,
            labels=["triage", "ci"],
        )

        return response.parsed_data.html_url

    def _format_issue_body(self, event: WorkflowRunFailureEvent, proposal: RemediationProposal) -> str:
        return f"""## Workflow Failure Detected

**Workflow**: {event.workflow.workflow_name}
**Job**: {event.workflow.job_name}
**Run**: [View Failed Run]({event.workflow.run_url})
**Fix Effort**: {proposal.fix_effort}

## Identified Issue

{proposal.identified_issue}

## Remediation Plan

{proposal.remediation_plan}

---
*This issue was automatically created by github-action-triage*
"""
