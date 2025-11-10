from pydantic import BaseModel, Field
from github_action_triage.app.events.models import WorkflowRunFailureEvent
from github_action_triage.app.events.outcomes import TriageOutcome
from github_action_triage.agent.ports import (
    GitHubContextProvider,
    RemediationAgent,
    IssueCreator,
)


class TriageResult(BaseModel):
    outcome: TriageOutcome = Field(..., description="Outcome of the triage process")
    message: str = Field(
        default="", description="Human-readable message about the outcome"
    )


class TriageService:
    def __init__(
        self,
        context_provider: GitHubContextProvider,
        agent: RemediationAgent,
        issue_creator: IssueCreator,
    ):
        self._context_provider = context_provider
        self._agent = agent
        self._issue_creator = issue_creator

    async def handle_failure(self, event: WorkflowRunFailureEvent) -> TriageResult:
        context = await self._context_provider.fetch_failure_context(event)
        proposal = await self._agent.diagnose_and_propose(context)
        
        return TriageResult(
            outcome=TriageOutcome.ANALYZED,
            message=f"Root cause identified: {proposal.identified_issue}. Fix effort: {proposal.fix_effort}",
        )

    async def process_failure_async(self, event: WorkflowRunFailureEvent) -> None:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            context = await self._context_provider.fetch_failure_context(event)
            proposal = await self._agent.diagnose_and_propose(context)
            
            issue_url = await self._issue_creator.create_issue_for_proposal(
                event, proposal
            )
            logger.info(
                "Created issue for failure",
                extra={"issue_url": issue_url, "repository": event.repository}
            )
            
        except Exception as exc:
            logger.exception("Error during background triage processing", exc_info=exc)
