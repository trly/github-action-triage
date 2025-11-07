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

    async def fetch_failure_context(
        self, event: WorkflowRunFailureEvent
    ) -> FailureContext:
        # Create installation-scoped client by getting installation access token
        token_response = await self._client.rest.apps.async_create_installation_access_token(
            installation_id=event.installation_id
        )
        installation_token = token_response.parsed_data.token

        # Create new client with installation token
        from githubkit import GitHub
        installation_client = GitHub(installation_token)
        job_id = int(event.workflow.job_id)
        
        # Fetch job details from GitHub API
        response = await installation_client.rest.actions.async_get_job_for_workflow_run(
            owner=event.repository.owner,
            repo=event.repository.name,
            job_id=job_id,
        )
        
        job_data = response.parsed_data
        
        # Download logs using GitHub API
        logs_response = await installation_client.rest.actions.async_download_job_logs_for_workflow_run(
            owner=event.repository.owner,
            repo=event.repository.name,
            job_id=job_id,
        )
        logs_bytes = logs_response.content
        logs_excerpt = extract_failure_excerpt(logs_bytes)
        
        return FailureContext(
            event=event,
            repository_full_name=f"{event.repository.owner}/{event.repository.name}",
            head_commit_sha=job_data.head_sha,
            branch_ref=f"refs/heads/{job_data.head_branch}",
            job_html_url=job_data.html_url,
            logs_url=job_data.html_url,
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
