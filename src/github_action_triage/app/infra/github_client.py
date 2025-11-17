import json
import logging

from githubkit import GitHub

from github_action_triage.agent.ports import (
    FailureContext,
    GitHubContextProvider,
    RemediationProposal,
    RepositoryActuator,
)
from github_action_triage.app.config.settings import Settings
from github_action_triage.app.events.models import WorkflowRunFailureEvent
from github_action_triage.app.infra.log_extraction import extract_failure_excerpt

logger = logging.getLogger(__name__)


class GitHubContextAdapter(GitHubContextProvider):
    def __init__(self, settings: Settings, github_client: GitHub):
        self._settings = settings
        self._client = github_client

    async def fetch_failure_context(self, event: WorkflowRunFailureEvent) -> FailureContext:
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

        # Construct logs download URL
        # GitHub API endpoint for downloading job logs
        logs_url = f"https://api.github.com/repos/{event.repository.owner}/{
            event.repository.name
        }/actions/jobs/{job_id}/logs"

        # Download logs using GitHub API
        try:
            logs_response = (
                await installation_client.rest.actions.async_download_job_logs_for_workflow_run(
                    owner=event.repository.owner,
                    repo=event.repository.name,
                    job_id=job_id,
                )
            )
            logs_bytes = logs_response.content
            logs_excerpt = extract_failure_excerpt(logs_bytes)
        except Exception as e:
            # Logs may not be available yet or have expired
            logs_excerpt = f"[Logs unavailable: {str(e)}]"
            logs_url = None

        # Extract workflow file path from run_url
        # run_url format: https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}
        # We'll fetch the run to get workflow_path
        run_id = int(event.workflow.run_id)
        run_response = await installation_client.rest.actions.async_get_workflow_run(
            owner=event.repository.owner,
            repo=event.repository.name,
            run_id=run_id,
        )
        workflow_path = run_response.parsed_data.path

        return FailureContext(
            event=event,
            job_id=event.workflow.job_id,
            repository_full_name=f"{event.repository.owner}/{event.repository.name}",
            head_commit_sha=job_data.head_sha,
            branch_ref=f"refs/heads/{job_data.head_branch}",
            job_html_url=job_data.html_url or "",
            logs_url=logs_url,
            logs_excerpt=logs_excerpt,
            workflow_file_path=workflow_path,
            recent_commits=[job_data.head_sha],
            job_steps=[
                {
                    "name": step.name,
                    "status": step.status,
                    "conclusion": step.conclusion,
                    "number": step.number,
                }
                for step in (job_data.steps or [])
            ],
        )


class GitHubRepositoryActuator(RepositoryActuator):
    def __init__(self, settings: Settings):
        self._settings = settings

    async def apply_fix(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> bool:
        logger.debug(
            "WorkflowRunFailureEvent: %s",
            json.dumps(event.model_dump(), indent=2, default=str),
        )
        logger.debug(
            "RemediationProposal: %s",
            json.dumps(proposal.model_dump(), indent=2, default=str),
        )

        raise NotImplementedError("Repository fix application not yet implemented")
