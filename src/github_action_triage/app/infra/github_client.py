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
        
        # Construct logs download URL
        # GitHub API endpoint for downloading job logs
        logs_url = f"https://api.github.com/repos/{event.repository.owner}/{event.repository.name}/actions/jobs/{job_id}/logs"
        
        # Download logs using GitHub API
        try:
            logs_response = await installation_client.rest.actions.async_download_job_logs_for_workflow_run(
                owner=event.repository.owner,
                repo=event.repository.name,
                job_id=job_id,
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
            repository_full_name=f"{event.repository.owner}/{event.repository.name}",
            head_commit_sha=job_data.head_sha,
            branch_ref=f"refs/heads/{job_data.head_branch}",
            job_html_url=job_data.html_url or "",
            logs_url=logs_url,
            logs_excerpt=logs_excerpt,
            workflow_file_path=workflow_path,
            recent_commits=[job_data.head_sha],
        )


class GitHubRepositoryActuator(RepositoryActuator):
    def __init__(self, settings: Settings, github_client: GitHub | None = None):
        self._settings = settings
        self._client = github_client or GitHub(settings.github_app_id, settings.github_private_key)

    async def apply_fix(
        self, event: WorkflowRunFailureEvent, proposal: RemediationProposal
    ) -> bool:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Get installation access token
            token_response = await self._client.rest.apps.async_create_installation_access_token(
                installation_id=event.installation_id
            )
            installation_token = token_response.parsed_data.token
            
            # Create installation-scoped client
            installation_client = GitHub(installation_token)
            
            # Get job details to fetch commit SHA
            job_id = int(event.workflow.job_id)
            job_response = await installation_client.rest.actions.async_get_job_for_workflow_run(
                owner=event.repository.owner,
                repo=event.repository.name,
                job_id=job_id,
            )
            commit_sha = job_response.parsed_data.head_sha
            
            # Format the comment body
            comment_body = f"""## 🤖 AI-Powered Triage Report

**Identified Issue:**
{proposal.identified_issue}

**Estimated Fix Effort:** `{proposal.fix_effort}`

**Remediation Plan:**
{proposal.remediation_plan}

---
*This analysis was generated automatically by github-action-triage.*
"""
            
            # Post comment on the commit
            await installation_client.rest.repos.async_create_commit_comment(
                owner=event.repository.owner,
                repo=event.repository.name,
                commit_sha=commit_sha,
                body=comment_body,
            )
            
            logger.info(
                "Posted remediation proposal as commit comment",
                extra={
                    "repo": f"{event.repository.owner}/{event.repository.name}",
                    "commit": commit_sha,
                }
            )
            return True
            
        except Exception as exc:
            logger.error(
                "Failed to post remediation proposal",
                exc_info=exc,
                extra={
                    "repo": f"{event.repository.owner}/{event.repository.name}",
                }
            )
            return False
