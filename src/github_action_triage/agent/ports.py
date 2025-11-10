from typing import Protocol, Literal
from pydantic import BaseModel, ConfigDict, Field


class RepositoryRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner: str = Field(...,
                       description="Repository owner (organization or user)")
    name: str = Field(..., description="Repository name")


class WorkflowRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(..., description="Workflow run ID")
    job_id: str = Field(..., description="Job ID that failed")
    workflow_name: str = Field(..., description="Workflow name")
    job_name: str = Field(..., description="Job name that failed")
    run_url: str = Field(..., description="URL to the workflow run")


class FailureSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    conclusion: str = Field(
        ..., description="Workflow run conclusion (e.g., 'failure', 'cancelled')"
    )
    logs_snippet: str = Field(
        ..., description="Relevant logs or error messages from the failure"
    )


class WorkflowRunFailureEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    installation_id: int = Field(..., description="GitHub App installation ID")
    repository: RepositoryRef = Field(
        ..., description="Repository where the workflow ran"
    )
    workflow: WorkflowRef = Field(..., description="Workflow run metadata")
    failure: FailureSummary = Field(...,
                                    description="Failure details and diagnostics")


class FailureContext(BaseModel):
    event: WorkflowRunFailureEvent
    repository_full_name: str = Field(
        ..., description="Full repository name (owner/repo)"
    )
    head_commit_sha: str = Field(..., description="Commit SHA of the failed run")
    branch_ref: str = Field(..., description="Branch reference (e.g., refs/heads/main)")
    job_html_url: str = Field(..., description="HTML URL to the job on GitHub")
    logs_url: str | None = Field(default=None, description="URL to download job logs (if available)")
    logs_excerpt: str = Field(..., description="Excerpt from failure logs")
    workflow_file_path: str | None = Field(
        default=None, description="Path to workflow YAML file in repository (e.g., .github/workflows/ci.yml)"
    )
    recent_commits: list[str] = Field(
        default_factory=list, description="Recent commit SHAs"
    )


class RemediationProposal(BaseModel):
    identified_issue: str = Field(
        ..., description="Clear description of the issue causing the workflow failure"
    )
    fix_effort: Literal["small", "medium", "large"] = Field(
        ..., description="Estimated effort to fix: small (< 1hr), medium (1-4hrs), large (> 4hrs)"
    )
    remediation_plan: str = Field(
        ..., description="Step-by-step plan for fixing the issue"
    )


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


class IssueCreator(Protocol):
    async def create_issue_for_proposal(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> str:
        """Create GitHub issue for remediation proposal.

        Returns:
            Issue URL
        """
        ...


class RepositoryActuator(Protocol):
    async def apply_fix(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> bool: ...
