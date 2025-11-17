import io
import zipfile

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy

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


async def get_installation_client(settings: Settings, installation_id: int) -> GitHub:
    """Create GitHub App installation client with installation token."""
    auth = AppAuthStrategy(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )
    github_app_client = GitHub(auth=auth)

    token_response = await github_app_client.rest.apps.async_create_installation_access_token(
        installation_id=installation_id
    )
    installation_token = token_response.parsed_data.token

    return GitHub(installation_token)


async def fetch_job_logs(github_client: GitHub, owner: str, repo: str, job_id: int) -> str:
    """Fetch full logs for a GitHub Actions job.

    Args:
        github_client: Authenticated GitHub client
        owner: Repository owner
        repo: Repository name
        job_id: Job ID

    Returns:
        Full job logs as a string
    """
    try:
        logs_response = await github_client.rest.actions.async_download_job_logs_for_workflow_run(
            owner=owner,
            repo=repo,
            job_id=job_id,
        )
        logs_bytes = logs_response.content

        return extract_logs_from_archive(logs_bytes)
    except Exception as e:
        return f"[Logs unavailable: {e!s}]"


def extract_logs_from_archive(logs_bytes: bytes) -> str:
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
