import logging
import os

from pydantic_ai import Agent

from github_action_triage.agent.analysis.config import get_analysis_settings
from github_action_triage.agent.analysis.tools.github import GitHubToolContext, github_toolset
from github_action_triage.agent.analysis.tools.sourcegraph import create_sourcegraph_toolset
from github_action_triage.agent.config import get_settings
from github_action_triage.agent.ports import FailureContext, RemediationAgent, RemediationProposal

logger = logging.getLogger(__name__)


class TriageAgent(RemediationAgent):
    """GitHub Actions failure analysis agent using pydantic-ai."""

    def __init__(self):
        self.settings = get_settings()
        self.analysis_settings = get_analysis_settings()

        if self.settings.anthropic_api_key and self.settings.anthropic_api_key.get_secret_value():
            os.environ["ANTHROPIC_API_KEY"] = self.settings.anthropic_api_key.get_secret_value()

        self.sg_toolset = create_sourcegraph_toolset(self.settings)
        if self.sg_toolset:
            logger.info("TriageAgent: Sourcegraph MCP tools enabled")
        else:
            logger.info("TriageAgent: Running without Sourcegraph MCP tools")

        system_prompt = self._build_system_prompt()

        toolsets = [github_toolset]
        if self.sg_toolset:
            toolsets.append(self.sg_toolset)

        self.agent = Agent(
            self.analysis_settings.model,
            deps_type=GitHubToolContext,
            output_type=RemediationProposal,
            toolsets=toolsets,
            system_prompt=system_prompt,
        )

    def _build_system_prompt(self) -> str:
        """Build system prompt with conditional MCP tools section."""
        base_prompt = """You are a GitHub Actions workflow failure analysis expert.
Your objective is to diagnose the root cause of workflow failures and propose actionable remediation plans.

## Analysis Workflow

1. Use get_job to retrieve job metadata (this includes the commit SHA and branch)
2. Use get_job_logs to retrieve the failure logs
3. Identify the root cause of the failure"""

        if self.sg_toolset:
            base_prompt += """

**CRITICAL:** You do not have a local checkout of the target repository. Code inspection MUST be performed using Sourcegraph MCP tools.
Use sg_read_file to validate proposed fixes. Even if it appears clear from the job log.

**When analyzing failures:**
1. Extract the commit SHA from the job metadata (from get_job)
2. Use revision parameter to read/search code at that exact commit
3. Examine the actual code that failed, not just guess from logs
4. Look for recent changes using sg_commit_search or sg_compare_revisions
5. Track all files you investigate in the involved_files field
6. Provide specific fixes with line numbers and code references"""
        else:
            base_prompt += """
4. Suggest a fix based on the logs and your knowledge"""

        base_prompt += """

## Output Requirements

You MUST populate ALL fields in the RemediationProposal output:

- **issue_title**: Short, actionable title for GitHub issue (< 80 characters)
  Example: "Ruff linting errors in source files"

- **identified_issue**: Precise description of the root cause (not just the symptom)

- **fix_effort**: Estimated remediation effort:
  - `small`: < 1 hour (configuration adjustments, dependency version updates, trivial fixes)
  - `medium`: 1-4 hours (logic corrections, test modifications, localized refactoring)
  - `large`: > 4 hours (architectural modifications, extensive refactoring, complex debugging)

- **remediation_plan**: Structured, step-by-step implementation plan (markdown format)
  - Use clear headers, code blocks, and bullet points
  - Include specific file paths and line numbers
  - Provide concrete code examples where applicable

- **job_metadata**: The full job metadata dict returned from get_job()
  - MUST include: head_sha, head_branch, status, conclusion, steps, html_url

- **involved_files**: List of all file paths you investigated during analysis
  - Include files read via sg_read_file, sg_list_files, or mentioned in searches
  - Use repository-relative paths (e.g., "src/main.go", not full URLs)
  - This helps track investigation scope and plan remediation

## Output Format

- Use clean, professional markdown formatting
- DO NOT use emojis
- Focus on technical accuracy and implementability
- Ensure output is suitable for engineers and AI agents to implement fixes"""

        return base_prompt

    async def prepare(self, context: FailureContext) -> None:
        """Prepare the agent with failure context without invoking LLM."""
        pass

    async def diagnose_and_propose(self, context: FailureContext) -> RemediationProposal:
        """Analyze workflow failure and produce structured remediation proposal."""
        # Build GitHub tool context from FailureContext
        github_context = GitHubToolContext(
            settings=self.settings,
            owner=context.event.repository.owner,
            repo=context.event.repository.name,
            installation_id=context.event.installation_id,
        )

        # Build analysis prompt
        prompt = f"""Analyze the following GitHub Actions workflow failure:

**Repository:** {context.repository_full_name}
**Branch:** {context.branch_ref}
**Commit SHA:** {context.head_commit_sha}
**Job ID:** {context.job_id}
**Job URL:** {context.job_html_url}

**Workflow Details:**
- Workflow: {context.event.workflow.workflow_name}
- Job: {context.event.workflow.job_name}
- Run ID: {context.event.workflow.run_id}

**Logs Excerpt:**
```
{context.logs_excerpt}
```

Use get_job({context.job_id}) to retrieve full job metadata and get_job_logs({context.job_id}) for complete logs.

Diagnose the failure and provide a comprehensive remediation proposal."""

        logger.info(f"TriageAgent: Starting analysis for job {context.job_id}")

        result = await self.agent.run(
            prompt,
            deps=github_context,
        )

        logger.info(
            f"TriageAgent: Analysis complete - {result.output.issue_title}")

        return result.output

