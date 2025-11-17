import io
import logging
import os
import zipfile
from typing import Any

from githubkit import GitHub
from githubkit.auth import AppAuthStrategy
from pydantic_ai import Agent, RunContext

from github_action_triage.agent.analysis.config import get_analysis_settings
from github_action_triage.agent.analysis.instructions import (
    base_instructions,
    github_context_instructions,
    output_requirements_instructions,
    sourcegraph_mcp_instructions,
)
from github_action_triage.agent.analysis.tools.github import GitHubToolContext
from github_action_triage.agent.analysis.tools.sourcegraph import (
    create_sourcegraph_toolset,
)
from github_action_triage.agent.config import get_settings
from github_action_triage.agent.ports import (
    FailureContext,
    RemediationAgent,
    RemediationProposal,
)

logger = logging.getLogger(__name__)


class TriageAgent(RemediationAgent):
    """GitHub Actions failure analysis agent using pydantic-ai."""

    def __init__(self):
        self.settings = get_settings()
        self.analysis_settings = get_analysis_settings()

        if self.settings.anthropic_api_key and self.settings.anthropic_api_key.get_secret_value():
            os.environ["ANTHROPIC_API_KEY"] = self.settings.anthropic_api_key.get_secret_value()

        # Create Sourcegraph MCP toolset if configured
        self.sg_toolset = create_sourcegraph_toolset(self.settings)
        if self.sg_toolset:
            logger.info(f"TriageAgent: Sourcegraph MCP tools enabled - toolset type: {type(self.sg_toolset).__name__}")
        else:
            logger.info("TriageAgent: Running without Sourcegraph MCP tools")

        # Create agent with optional MCP toolset
        toolsets = [self.sg_toolset] if self.sg_toolset else None
        logger.info(f"TriageAgent: Creating agent with toolsets={toolsets is not None}")
        self.agent = Agent(
            self.analysis_settings.model,
            deps_type=GitHubToolContext,
            output_type=RemediationProposal,
            toolsets=toolsets,
        )
        logger.info("TriageAgent: Agent created successfully")

        self._register_tools()
        self._register_instructions()

    def _register_instructions(self) -> None:
        """Register agent instructions as separate methods."""
        self.agent.instructions(base_instructions)
        self.agent.instructions(github_context_instructions)

        if self.sg_toolset:
            logger.info("TriageAgent: Registering Sourcegraph MCP instructions")
            self.agent.instructions(sourcegraph_mcp_instructions)
        else:
            logger.info("TriageAgent: Skipping Sourcegraph MCP instructions (no toolset)")

        self.agent.instructions(output_requirements_instructions)

    def _register_tools(self) -> None:
        """Register agent tools."""

        @self.agent.tool(docstring_format="google", require_parameter_descriptions=True)
        async def get_job(ctx: RunContext[GitHubToolContext], job_id: int) -> dict[str, Any]:
            """Get information about a specific GitHub Actions job.

            Args:
                job_id: The job ID from the webhook

            Returns:
                Dictionary containing job details including status, conclusion,
                steps, commit SHA, branch, etc.
            """
            return await self._tool_get_job(ctx, job_id)

        @self.agent.tool(docstring_format="google", require_parameter_descriptions=True)
        async def get_job_logs(ctx: RunContext[GitHubToolContext], job_id: int) -> str:
            """Get logs for a specific GitHub Actions job.

            Args:
                job_id: The job ID from the webhook

            Returns:
                String containing the job logs
            """
            return await self._tool_get_job_logs(ctx, job_id)

    async def _tool_get_job(
        self, ctx: RunContext[GitHubToolContext], job_id: int
    ) -> dict[str, Any]:
        """Implementation of get_job tool."""
        github = await self._get_installation_client(ctx)

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

    async def _tool_get_job_logs(self, ctx: RunContext[GitHubToolContext], job_id: int) -> str:
        """Implementation of get_job_logs tool."""
        github = await self._get_installation_client(ctx)

        try:
            logs_response = await github.rest.actions.async_download_job_logs_for_workflow_run(
                owner=ctx.deps.owner,
                repo=ctx.deps.repo,
                job_id=job_id,
            )
            logs_bytes = logs_response.content

            return self._extract_logs_from_archive(logs_bytes)
        except Exception as e:
            return f"[Logs unavailable: {e!s}]"

    async def _get_installation_client(self, ctx: RunContext[GitHubToolContext]) -> GitHub:
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

    @staticmethod
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

    async def diagnose_and_propose(self, context: FailureContext) -> RemediationProposal:
        """Analyze workflow failure and produce structured remediation proposal."""
        # Build GitHub tool context with FailureContext included
        github_context = GitHubToolContext(
            settings=self.settings,
            owner=context.event.repository.owner,
            repo=context.event.repository.name,
            installation_id=context.event.installation_id,
            failure=context,
        )

        # Build analysis prompt - context available via deps
        prompt = f"""Analyze the GitHub Actions workflow failure:

**Repository:** {context.repository_full_name}
**Branch:** {context.branch_ref}
**Commit:** {context.head_commit_sha}
**Job ID:** {context.job_id}

**Workflow:** {context.event.workflow.workflow_name} / {context.event.workflow.job_name}

**Logs Excerpt:**
```
{context.logs_excerpt}
```

Use get_job() to retrieve full job metadata and get_job_logs() for complete logs.

Diagnose the failure and provide a comprehensive remediation proposal."""

        logger.info(f"TriageAgent: Starting analysis for job {context.job_id}")

        result = await self.agent.run(
            prompt,
            deps=github_context,
        )

        logger.info(
            f"TriageAgent: Analysis complete - {result.output.issue_title}")

        return result.output