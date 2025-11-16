import io
import zipfile
from typing import Any

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy
from pydantic_ai import FunctionToolset, RunContext

from github_action_triage.agent.config import Settings
from github_action_triage.agent.ports import FailureContext


class GitHubToolContext:
    """Context for GitHub tools - includes authentication info and failure context."""

    def __init__(
        self,
        settings: Settings,
        owner: str,
        repo: str,
        installation_id: int,
        failure: FailureContext,
    ):
        self.settings = settings
        self.owner = owner
        self.repo = repo
        self.installation_id = installation_id
        self.failure = failure


github_toolset = FunctionToolset()


async def _get_installation_client(ctx: RunContext[GitHubToolContext]) -> GitHub:
    """Create GitHub App installation client with installation token."""
    auth = AppAuthStrategy(
        app_id=ctx.deps.settings.github_app_id,
        private_key=ctx.deps.settings.github_private_key,
    )
    github_app_client = GitHub(auth=auth)

    token_response = await github_app_client.rest.apps.async_create_installation_access_token(
        installation_id=ctx.deps.installation_id
    )
    installation_token = token_response.parsed_data.token

    return GitHub(installation_token)


@github_toolset.tool
async def get_job(
    ctx: RunContext[GitHubToolContext],
    job_id: int,
) -> dict[str, Any]:
    """Get information about a specific GitHub Actions job.

    Args:
        job_id: The job ID from the webhook

    Returns:
        Dictionary containing job details including status, conclusion, steps, commit SHA, branch, etc.
    """
    github = await _get_installation_client(ctx)

    response = await github.rest.actions.async_get_job_for_workflow_run(
        owner=ctx.deps.owner,
        repo=ctx.deps.repo,
        job_id=job_id,
    )

    job_data = response.parsed_data
    return {
        "id": job_data.id,
        "status": job_data.status,
        "conclusion": job_data.conclusion,
        "steps": [
            {
                "name": step.name,
                "status": step.status,
                "conclusion": step.conclusion,
                "number": step.number,
            }
            for step in (job_data.steps or [])
        ],
        "head_sha": job_data.head_sha,
        "head_branch": job_data.head_branch,
        "html_url": job_data.html_url,
    }


@github_toolset.tool
async def get_job_logs(
    ctx: RunContext[GitHubToolContext],
    job_id: int,
) -> str:
    """Get logs for a specific GitHub Actions job.

    Args:
        job_id: The job ID from the webhook

    Returns:
        String containing the job logs
    """
    github = await _get_installation_client(ctx)

    try:
        logs_response = await github.rest.actions.async_download_job_logs_for_workflow_run(
            owner=ctx.deps.owner,
            repo=ctx.deps.repo,
            job_id=job_id,
        )
        logs_bytes = logs_response.content

        return _extract_logs_from_archive(logs_bytes)
    except Exception as e:
        return f"[Logs unavailable: {e!s}]"


def _extract_logs_from_archive(logs_bytes: bytes) -> str:
    """Extract logs from GitHub's zip archive format."""
    try:
        with zipfile.ZipFile(io.BytesIO(logs_bytes)) as zf:
            file_list = zf.namelist()
            if file_list:
                with zf.open(file_list[0]) as log_file:
                    logs_bytes = log_file.read()
    except zipfile.BadZipFile:
        pass

    return logs_bytes.decode("utf-8", errors="replace")
