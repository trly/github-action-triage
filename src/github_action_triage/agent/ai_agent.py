from github_action_triage.agent.ports import (
    RemediationAgent,
    FailureContext,
    RemediationProposal,
)
from github_action_triage.app.config.settings import Settings


class PydanticAIRemediationAgent(RemediationAgent):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._last_context: FailureContext | None = None

    async def prepare(self, context: FailureContext) -> None:
        """Store context for future LLM invocation without triggering it now."""
        self._last_context = context

    async def diagnose_and_propose(
        self, context: FailureContext
    ) -> RemediationProposal:
        raise NotImplementedError("LLM integration pending")
