import httpx
from githubkit import GitHub
from github_action_triage.agent.ports import (
    GitHubContextProvider,
    FailureContext,
    RepositoryActuator,
    RemediationProposal,
)
from github_action_triage.app.events.models import WorkflowRunFailureEvent
from github_action_triage.app.config.settings import Settings
from github_action_triage.app.infra.log_extraction import extract_failure_excerpt


class GitHubContextAdapter(GitHubContextProvider):
    def __init__(self, settings: Settings, github_client: GitHub):
        self._settings = settings
        self._client = github_client

    async def _download_logs(self, logs_url: str) -> bytes:
        """Download job logs from GitHub."""
        async with httpx.AsyncClient() as client:
            # GitHub requires authentication for private repos
            headers = {}
            if self._settings.github_app_id:
                # Use the same auth as the GitHub client
                # For now, we'll use the installation token from the client
                # TODO: Implement proper token retrieval
                pass
            
            response = await client.get(logs_url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            return response.content

    async def fetch_failure_context(
        self, event: WorkflowRunFailureEvent
    ) -> FailureContext:
        job_id = int(event.workflow.job_id)
        
        # Fetch job details from GitHub API
        response = await self._client.rest.actions.async_get_job_for_workflow_run(
            owner=event.repository.owner,
            repo=event.repository.name,
            job_id=job_id,
        )
        
        job_data = response.parsed_data
        
        # Download and extract logs
        logs_bytes = await self._download_logs(job_data.logs_url)
        logs_excerpt = extract_failure_excerpt(logs_bytes)
        
        return FailureContext(
            event=event,
            repository_full_name=f"{event.repository.owner}/{event.repository.name}",
            head_commit_sha=job_data.head_sha,
            branch_ref=f"refs/heads/{job_data.head_branch}",
            job_html_url=job_data.html_url,
            logs_url=job_data.logs_url,
            logs_excerpt=logs_excerpt,
            workflow_file=None,
            recent_commits=[job_data.head_sha],
        )


class GitHubRepositoryActuator(RepositoryActuator):
    def __init__(self, settings: Settings):
        self._settings = settings

    async def apply_fix(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> bool:
        raise NotImplementedError("Repository fix application not yet implemented")
