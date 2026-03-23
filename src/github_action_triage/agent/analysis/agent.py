import json
import logging
import re

from github_action_triage.agent.analysis.config import get_analysis_settings
from github_action_triage.agent.analysis.tools.deepsearch import (
    DeepSearchResult,
    run_deep_search,
)
from github_action_triage.agent.config import get_settings
from github_action_triage.agent.ports import (
    FailureContext,
    RemediationAgent,
    RemediationProposal,
)

logger = logging.getLogger(__name__)


class TriageAgent(RemediationAgent):
    """GitHub Actions failure analysis agent using Sourcegraph Deep Search."""

    def __init__(self):
        self.settings = get_settings()
        self.analysis_settings = get_analysis_settings()
        self._last_deep_search_result: DeepSearchResult | None = None

    async def diagnose_and_propose(self, context: FailureContext) -> RemediationProposal:
        """Analyze workflow failure via Deep Search and produce remediation proposal."""
        question = self._build_question(context)

        logger.info(f"TriageAgent: Starting Deep Search analysis for job {context.job_id}")

        result = await run_deep_search(
            sourcegraph_url=self.settings.sourcegraph_url,
            token=self.settings.sourcegraph_token.get_secret_value(),
            question=question,
            timeout_seconds=self.analysis_settings.timeout_seconds,
        )
        self._last_deep_search_result = result

        logger.info(
            f"TriageAgent: Deep Search completed - "
            f"conversation={result.conversation_name}, "
            f"polls={result.poll_count}, "
            f"elapsed={result.elapsed_seconds:.1f}s"
        )

        # Parse structured proposal from Deep Search answer
        parsed = self._extract_json_from_markdown(result.answer_markdown)
        if parsed:
            try:
                proposal = RemediationProposal.model_validate(parsed)
                logger.info(f"TriageAgent: Parsed proposal - {proposal.issue_title}")
                return proposal
            except Exception as e:
                logger.warning(f"TriageAgent: JSON parsed but validation failed: {e}")

        # Fallback: construct proposal from raw markdown
        logger.warning("TriageAgent: Could not extract structured JSON, using markdown fallback")
        return RemediationProposal(
            issue_title=f"CI failure in {context.repository_full_name}",
            identified_issue=result.answer_markdown[:500] if result.answer_markdown else "Analysis completed but no structured output was returned.",
            fix_effort="medium",
            remediation_plan=result.answer_markdown or "See Deep Search analysis for details.",
            involved_files=[],
        )

    def _build_question(self, context: FailureContext) -> str:
        """Build the Deep Search analysis question from failure context."""
        job_steps_summary = "\n".join(
            f"  {step['number']}. {step['name']} - {step['status']} ({step['conclusion']})"
            for step in context.job_steps
        )

        return f"""Analyze this GitHub Actions workflow failure and provide a remediation plan.

Repository: {context.repository_full_name}
Branch: {context.branch_ref}
Commit: {context.head_commit_sha}
Job ID: {context.job_id}
Job URL: {context.job_html_url}

Workflow: {context.event.workflow.workflow_name} / {context.event.workflow.job_name}

Job Steps:
{job_steps_summary}

Logs Excerpt:
```
{context.logs_excerpt}
```

Instructions:
1. Examine the repository code at commit {context.head_commit_sha} to understand what changed
2. Analyze the logs to identify the root cause of the failure
3. Check recent commits and relevant source files for context
4. Provide your analysis as a JSON object with exactly these fields:

```json
{{
  "issue_title": "Short, actionable title for GitHub issue (< 80 characters)",
  "identified_issue": "Precise description of the root cause",
  "fix_effort": "small|medium|large",
  "remediation_plan": "Step-by-step markdown plan with file paths and code examples",
  "involved_files": ["list", "of", "file/paths", "investigated"]
}}
```

fix_effort values: small (< 1 hour), medium (1-4 hours), large (> 4 hours)

Return ONLY the JSON object in a ```json code block. Do not include any other text outside the code block."""

    @staticmethod
    def _extract_json_from_markdown(markdown: str) -> dict | None:
        """Extract a JSON object from markdown, trying code blocks first."""
        # Try ```json ... ``` blocks
        json_block_pattern = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)
        for match in json_block_pattern.finditer(markdown):
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

        # Try bare JSON object
        brace_pattern = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
        for match in brace_pattern.finditer(markdown):
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict) and "issue_title" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue

        return None
