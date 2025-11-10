from typing import Any
import asyncio
import logging
from claude_agent_sdk import tool, ClaudeSDKClient, create_sdk_mcp_server
from claude_agent_sdk.types import ClaudeAgentOptions, ResultMessage, AssistantMessage, TextBlock
from github_action_triage.agent.ports import (
    RemediationAgent,
    FailureContext,
    RemediationProposal,
)
from github_action_triage.agent.config import Settings
from github_action_triage.agent.mcp import create_sourcegraph_mcp_server, MCP_SOURCEGRAPH_SERVER_NAME

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_BASE = """You are a GitHub Actions workflow failure analysis expert. Your objective is to diagnose the root cause of workflow failures and propose actionable remediation plans.

**IMPORTANT: You do not have a local checkout of the target repository.** All code inspection must be performed using the tools provided to you. Do not assume direct filesystem access or attempt to reference local files.

## Input Context

You will receive a FailureContext containing:
- Repository metadata (full name, branch reference, commit SHA)
- Workflow execution details (job name, run ID, HTML URL)
- Failure logs excerpt demonstrating the error condition
- Workflow file path (if available)
- Recent commit history"""

SYSTEM_PROMPT_MCP_TOOLS = """

## Remote Repository Access

**All repository code inspection must happen through the Sourcegraph MCP server.** You do not have local access to any files in the repository. Do not assume you can read files directly or that the repository is checked out on your filesystem.

You have access to a Sourcegraph MCP server (OAuth-authenticated) providing:
- Code search (keyword and semantic search across repositories)
- File reading (sg_read_file) — the ONLY way to read repository files
- Directory listing (sg_list_files) — the ONLY way to list repository contents
- Symbol navigation (sg_find_references, sg_go_to_definition)
- Commit and diff search

Use these MCP tools exclusively to investigate the codebase, examine workflow configurations, and analyze recent changes that may have introduced the failure."""

SYSTEM_PROMPT_WORKFLOW = """

## Analysis Workflow

1. Examine the logs_excerpt to identify the immediate failure symptom
2. Use available tools to investigate root cause (workflow YAML, recent commits, dependency files, code changes)
3. Form a hypothesis about the underlying issue
4. Once you have high confidence in your diagnosis, submit your remediation proposal

## Remediation Proposal Requirements

When confident in your analysis, invoke the submit_proposal tool with three parameters:

- **identified_issue**: Precise description of the root cause (not just the symptom)
- **fix_effort**: Estimated remediation effort based on the following criteria:
  - `small`: < 1 hour (configuration adjustments, dependency version updates, trivial fixes)
  - `medium`: 1-4 hours (logic corrections, test modifications, localized refactoring)
  - `large`: > 4 hours (architectural modifications, extensive refactoring, complex debugging)
- **remediation_plan**: Structured, step-by-step implementation plan with specific file paths and actions

## Constraints

- You may submit exactly one proposal per analysis session
- Ensure diagnosis accuracy before submission; there is no revision mechanism
- Focus on actionable, implementable fixes rather than speculative solutions
"""

# JSON Schema for submit_proposal tool input
SUBMIT_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "identified_issue": {
            "type": "string",
            "description": "Clear description of the issue causing the workflow failure"
        },
        "fix_effort": {
            "type": "string",
            "enum": ["small", "medium", "large"],
            "description": "Estimated effort to fix (small: <1h, medium: 1-4h, large: >4h)"
        },
        "remediation_plan": {
            "type": "string",
            "description": "Step-by-step plan for fixing the issue"
        }
    },
    "required": ["identified_issue", "fix_effort", "remediation_plan"]
}


class ActionTriageAgent(RemediationAgent):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._last_context: FailureContext | None = None

    async def prepare(self, context: FailureContext) -> None:
        """Store context for future LLM invocation without triggering it now."""
        self._last_context = context

    async def diagnose_and_propose(
        self, context: FailureContext
    ) -> RemediationProposal:
        """Diagnose workflow failure and propose remediation using Claude SDK.
        
        Creates ClaudeSDKClient with submit_proposal tool and optional MCP server,
        iterates message loop until ResultMessage, extracts proposal from storage.
        
        Args:
            context: FailureContext with logs, commits, and metadata
            
        Returns:
            RemediationProposal extracted from agent's submit_proposal call
            
        Raises:
            RuntimeError: If no proposal submitted on successful completion
            TimeoutError: If analysis exceeds max_turns or timeout
        """
        # Create run-scoped storage for this analysis
        proposal_storage: dict[str, RemediationProposal | None] = {"proposal": None}
        submit_tool = self._create_submit_proposal_tool(proposal_storage)
        
        # Create SDK MCP server for submit_proposal tool
        sdk_mcp_server = create_sdk_mcp_server(
            name="triage",
            version="1.0.0",
            tools=[submit_tool]
        )
        
        # Configure MCP servers (Sourcegraph + custom tools)
        mcp_servers = create_sourcegraph_mcp_server(self._settings) or {}
        mcp_servers["triage"] = sdk_mcp_server
        has_sourcegraph = MCP_SOURCEGRAPH_SERVER_NAME in mcp_servers
        
        # Build system prompt dynamically based on MCP availability
        system_prompt = SYSTEM_PROMPT_BASE
        if has_sourcegraph:
            system_prompt += SYSTEM_PROMPT_MCP_TOOLS
        system_prompt += SYSTEM_PROMPT_WORKFLOW
        
        # Format initial prompt with failure context
        initial_prompt = self._format_initial_prompt(context)
        
        # Configure allowed tools list using proper MCP server names
        allowed_tool_names = ["mcp__triage__submit_proposal"]
        if has_sourcegraph:
            # Add Sourcegraph MCP tools using the server name constant
            allowed_tool_names.extend([
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_read_file",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_list_files",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_list_repos",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_keyword_search",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_nls_search",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_go_to_definition",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_find_references",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_commit_search",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_diff_search",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_compare_revisions",
                f"mcp__{MCP_SOURCEGRAPH_SERVER_NAME}__sg_get_contributor_repos",
            ])
        
        # Configure Claude SDK client with model and API key from settings
        options = ClaudeAgentOptions(
            model=self._settings.claude_model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tool_names,
            mcp_servers=mcp_servers,
            max_turns=self._settings.claude_max_turns,
            env={"ANTHROPIC_API_KEY": self._settings.anthropic_api_key.get_secret_value()},
        )
        
        logger.info(
            f"Starting diagnosis for {context.repository_full_name} "
            f"(run_id={context.event.workflow.run_id}, model={self._settings.claude_model}, "
            f"MCP={'enabled' if has_sourcegraph else 'disabled'})"
        )
        
        # Run message loop with proper error handling
        final_result: ResultMessage | None = None
        
        async with ClaudeSDKClient(options) as client:
            await client.query(initial_prompt)
            
            async def iterate_messages():
                nonlocal final_result
                async for message in client.receive_response():
                    # Log assistant messages for debugging
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                logger.debug(f"Claude: {block.text[:500]}")
                    
                    # Check for final result message
                    elif isinstance(message, ResultMessage):
                        final_result = message
                        logger.info(
                            f"Analysis complete: turns={message.num_turns}, "
                            f"duration_ms={message.duration_ms}, error={message.is_error}"
                        )
                        break
            
            try:
                await asyncio.wait_for(
                    iterate_messages(),
                    timeout=self._settings.analysis_timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Analysis timed out after {self._settings.analysis_timeout_seconds}s "
                    f"for {context.repository_full_name} (run_id={context.event.workflow.run_id})"
                )
                raise
        
        # Check if the analysis completed with an error
        if final_result and final_result.is_error:
            error_msg = getattr(final_result, 'result', 'unknown error')
            raise RuntimeError(f"Claude agent analysis ended with error: {error_msg}")
        
        # Extract proposal from storage
        proposal = proposal_storage.get("proposal")
        if proposal is None:
            raise RuntimeError(
                "Analysis completed but no proposal was submitted. "
                "The agent did not call submit_proposal."
            )
        
        return proposal
    
    def _format_initial_prompt(self, context: FailureContext) -> str:
        """Format initial prompt with FailureContext data."""
        return f"""Analyze this GitHub Actions workflow failure and propose a remediation plan.

**Repository**: {context.repository_full_name}
**Branch**: {context.branch_ref}
**Commit**: {context.head_commit_sha}
**Workflow**: {context.event.workflow.workflow_name}
**Job**: {context.event.workflow.job_name}
**Run URL**: {context.job_html_url}

**Failure Logs**:
```
{context.logs_excerpt}
```

**Workflow File**: {context.workflow_file_path or "Unknown"}
**Recent Commits**: {", ".join(context.recent_commits) if context.recent_commits else "None available"}

Please investigate this failure and submit a remediation proposal once you have identified the root cause."""

    def _create_submit_proposal_tool(
        self, proposal_storage: dict[str, RemediationProposal | None]
    ):
        """Create a run-scoped submit_proposal tool with isolated storage.
        
        Args:
            proposal_storage: Dictionary to store proposal for this run (mutated by tool)
            
        Returns:
            Tool function decorated with @tool
        """
        @tool(
            name="submit_proposal",
            description="Submit a remediation proposal after diagnosing the workflow failure. Call this once you have high confidence in your diagnosis.",
            input_schema=SUBMIT_PROPOSAL_SCHEMA
        )
        async def submit_proposal_tool(args: dict[str, Any]) -> dict[str, Any]:
            """Tool for Claude to submit a remediation proposal.
            
            Args:
                args: Dictionary containing:
                    - identified_issue: Clear description of the issue causing the workflow failure
                    - fix_effort: Estimated effort to fix (small, medium, or large)
                    - remediation_plan: Step-by-step plan for fixing the issue
                
            Returns:
                SDK tool response with success message
                
            Raises:
                ValueError: If fix_effort is not one of the valid values
                RuntimeError: If a proposal has already been submitted in this run
            """
            identified_issue = args["identified_issue"]
            fix_effort = args["fix_effort"]
            remediation_plan = args["remediation_plan"]
            
            # Validate fix_effort first (before checking duplicate submission)
            valid_efforts = ["small", "medium", "large"]
            if fix_effort not in valid_efforts:
                raise ValueError(f"fix_effort must be one of {valid_efforts}, got '{fix_effort}'")
            
            # Check if proposal already submitted in this run
            if proposal_storage.get("proposal") is not None:
                raise RuntimeError("Proposal already submitted")
            
            # Store the proposal in run-scoped storage
            proposal_storage["proposal"] = RemediationProposal(
                identified_issue=identified_issue,
                fix_effort=fix_effort,  # type: ignore
                remediation_plan=remediation_plan,
            )
            
            return {
                "content": [{
                    "type": "text",
                    "text": "Proposal submitted successfully"
                }]
            }
        
        return submit_proposal_tool
