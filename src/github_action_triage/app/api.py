from pydantic import BaseModel, Field
from github_action_triage.app.events.models import WorkflowRunFailureEvent
from github_action_triage.app.events.outcomes import TriageOutcome
from github_action_triage.agent.ports import (
    GitHubContextProvider,
    RemediationAgent,
    RepositoryActuator,
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
        actuator: RepositoryActuator,
    ):
        self._context_provider = context_provider
        self._agent = agent
        self._actuator = actuator

    async def handle_failure(self, event: WorkflowRunFailureEvent) -> TriageResult:
        context = await self._context_provider.fetch_failure_context(event)
        await self._agent.prepare(context)
        
        return TriageResult(
            outcome=TriageOutcome.DEFERRED,
            message="Failure context captured for AI triage",
        )
