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
