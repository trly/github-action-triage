import logging
import os

from pydantic_ai import Agent, RunContext

from github_action_triage.agent.analysis.config import get_analysis_settings
from github_action_triage.agent.analysis.github import (
    GitHubToolContext,
    fetch_job_logs,
    get_installation_client,
)
from github_action_triage.agent.analysis.instructions import (
    base_instructions,
    github_context_instructions,
    output_requirements_instructions,
    sourcegraph_mcp_instructions,
)
from github_action_triage.agent.analysis.tools.sourcegraph import (
    create_sourcegraph_tool,
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
        self._last_result = None

        if self.settings.anthropic_api_key and self.settings.anthropic_api_key.get_secret_value():
            os.environ["ANTHROPIC_API_KEY"] = self.settings.anthropic_api_key.get_secret_value()

        # Create Sourcegraph MCP builtin tool if configured
        self.sg_tool = create_sourcegraph_tool(self.settings)
        if self.sg_tool:
            logger.info("TriageAgent: Sourcegraph MCP builtin tool enabled")
        else:
            logger.info("TriageAgent: Running without Sourcegraph MCP tools")

        # Create agent with optional MCP builtin tool
        builtin_tools = [self.sg_tool] if self.sg_tool else None
        logger.info(f"TriageAgent: Creating agent with builtin_tools={builtin_tools is not None}")
        self.agent = Agent(
            self.analysis_settings.model,
            deps_type=GitHubToolContext,
            output_type=RemediationProposal,
            builtin_tools=builtin_tools,
        )
        logger.info("TriageAgent: Agent created successfully")

        self._register_tools()
        self._register_instructions()

    def _register_instructions(self) -> None:
        """Register agent instructions as separate methods."""
        self.agent.instructions(base_instructions)
        self.agent.instructions(github_context_instructions)

        if self.sg_tool:
            logger.info("TriageAgent: Registering Sourcegraph MCP instructions")
            self.agent.instructions(sourcegraph_mcp_instructions)
        else:
            logger.info("TriageAgent: Skipping Sourcegraph MCP instructions (no tool)")

        self.agent.instructions(output_requirements_instructions)

    def _register_tools(self) -> None:
        """Register agent tools."""

        @self.agent.tool(docstring_format="google", require_parameter_descriptions=True)
        async def get_job_logs(ctx: RunContext[GitHubToolContext], job_id: int) -> str:
            """Get logs for a specific GitHub Actions job.

            Args:
                job_id: The job ID from the webhook

            Returns:
                String containing the job logs
            """
            github_client = await get_installation_client(
                ctx.deps.settings, ctx.deps.installation_id
            )
            return await fetch_job_logs(github_client, ctx.deps.owner, ctx.deps.repo, job_id)

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
        job_steps_summary = "\n".join(
            f"  {step['number']}. {step['name']} - {step['status']} ({step['conclusion']})"
            for step in context.job_steps
        )

        prompt = f"""Analyze the GitHub Actions workflow failure:

**Repository:** {context.repository_full_name}
**Branch:** {context.branch_ref}
**Commit:** {context.head_commit_sha}
**Job ID:** {context.job_id}
**Job URL:** {context.job_html_url}

**Workflow:** {context.event.workflow.workflow_name} / {context.event.workflow.job_name}

**Job Steps:**
{job_steps_summary}

**Logs Excerpt:**
```
{context.logs_excerpt}
```

Use get_job_logs() if you need the complete logs for deeper analysis.

Diagnose the failure and provide a comprehensive remediation proposal."""

        logger.info(f"TriageAgent: Starting analysis for job {context.job_id}")

        self._last_result = await self.agent.run(
            prompt,
            deps=github_context,
        )

        logger.info(f"TriageAgent: Analysis complete - {self._last_result.output.issue_title}")

        return self._last_result.output
