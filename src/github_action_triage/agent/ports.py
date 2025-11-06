from typing import Protocol
from pydantic import BaseModel, Field
from github_action_triage.app.events.models import WorkflowRunFailureEvent


class FailureContext(BaseModel):
    event: WorkflowRunFailureEvent
    repository_full_name: str = Field(
        ..., description="Full repository name (owner/repo)"
    )
    head_commit_sha: str = Field(..., description="Commit SHA of the failed run")
    branch_ref: str = Field(..., description="Branch reference (e.g., refs/heads/main)")
    job_html_url: str = Field(..., description="HTML URL to the job on GitHub")
    logs_url: str = Field(..., description="URL to download job logs")
    logs_excerpt: str = Field(..., description="Excerpt from failure logs")
    workflow_file: str | None = Field(
        default=None, description="Workflow YAML content if available"
    )
    recent_commits: list[str] = Field(
        default_factory=list, description="Recent commit SHAs"
    )


class RemediationProposal(BaseModel):
    description: str = Field(..., description="Description of proposed fix")
    patch: str | None = Field(
        default=None, description="Git patch if applicable")
    instructions: str = Field(...,
                              description="Instructions for applying the fix")


class GitHubContextProvider(Protocol):
    async def fetch_failure_context(
        self, event: WorkflowRunFailureEvent
    ) -> FailureContext: ...


class RemediationAgent(Protocol):
    async def prepare(self, context: FailureContext) -> None:
        """Prepare the agent with failure context without invoking LLM."""
        ...

    async def diagnose_and_propose(
        self, context: FailureContext
    ) -> RemediationProposal: ...


class RepositoryActuator(Protocol):
    async def apply_fix(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> bool: ...
