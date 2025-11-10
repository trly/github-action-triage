import pytest
from github_action_triage.agent.ai_agent import ActionTriageAgent
from github_action_triage.agent.ports import FailureContext
from github_action_triage.app.events.models import (
    WorkflowRunFailureEvent,
    RepositoryRef,
    WorkflowRef,
    FailureSummary,
)
from github_action_triage.app.config.settings import Settings


@pytest.fixture
def settings():
    return Settings(anthropic_api_key="test-key")


@pytest.fixture
def failure_context():
    event = WorkflowRunFailureEvent(
        installation_id=12345,
        repository=RepositoryRef(owner="test-org", name="test-repo"),
        workflow=WorkflowRef(
            run_id="123",
            job_id="456",
            workflow_name="CI",
            job_name="build",
            run_url="https://github.com/test-org/test-repo/actions/runs/123",
        ),
        failure=FailureSummary(
            conclusion="failure",
            logs_snippet="Error: npm install failed",
        ),
    )
    return FailureContext(
        event=event,
        repository_full_name="test-org/test-repo",
        head_commit_sha="abc123",
        branch_ref="refs/heads/main",
        job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
        logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
        logs_excerpt="Error: npm install failed",
        recent_commits=["abc123"],
    )


@pytest.mark.asyncio
async def test_prepare_stores_context_without_llm_invocation(settings, failure_context):
    agent = ActionTriageAgent(settings)
    
    # Initially no context
    assert agent._last_context is None
    
    # Prepare should store the context
    await agent.prepare(failure_context)
    
    assert agent._last_context is not None
    assert agent._last_context.repository_full_name == "test-org/test-repo"
    assert agent._last_context.head_commit_sha == "abc123"


@pytest.mark.asyncio
async def test_diagnose_and_propose_requires_proposal_submission(settings, failure_context):
    """Test that diagnose_and_propose raises error if agent doesn't submit a proposal."""
    from unittest.mock import patch
    from dataclasses import dataclass
    
    @dataclass
    class ResultMessage:
        subtype: str
        duration_ms: int
        duration_api_ms: int
        is_error: bool
        num_turns: int
        session_id: str
    
    # Mock client that completes without calling submit_proposal
    class MockClaudeSDKClientNoProposal:
        def __init__(self, options):
            self.options = options
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            # Immediately return ResultMessage without calling submit_proposal
            yield ResultMessage(
                subtype="success",
                duration_ms=1000,
                duration_api_ms=900,
                is_error=False,
                num_turns=1,
                session_id="test-session"
            )
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', MockClaudeSDKClientNoProposal):
        agent = ActionTriageAgent(settings)
        
        # Should raise RuntimeError since no proposal was submitted
        with pytest.raises(RuntimeError, match="no proposal was submitted"):
            await agent.diagnose_and_propose(failure_context)


@pytest.mark.asyncio
async def test_submit_proposal_validates_fix_effort(settings, failure_context):
    agent = ActionTriageAgent(settings)
    await agent.prepare(failure_context)
    
    # Create run-scoped storage for this test
    proposal_storage = {"proposal": None}
    tool = agent._create_submit_proposal_tool(proposal_storage)
    
    # Valid fix_effort values should succeed
    result = await tool.handler({
        "identified_issue": "npm install failed due to missing dependency",
        "fix_effort": "small",
        "remediation_plan": "Add missing dependency to package.json"
    })
    assert result["content"][0]["type"] == "text"
    assert "successfully" in result["content"][0]["text"].lower()
    
    # Invalid fix_effort should raise ValueError
    proposal_storage2 = {"proposal": None}
    tool2 = agent._create_submit_proposal_tool(proposal_storage2)
    with pytest.raises(ValueError, match="fix_effort must be one of"):
        await tool2.handler({
            "identified_issue": "Some issue",
            "fix_effort": "invalid",
            "remediation_plan": "Some plan"
        })


@pytest.mark.asyncio
async def test_submit_proposal_stores_in_run_scoped_storage(settings, failure_context):
    agent = ActionTriageAgent(settings)
    await agent.prepare(failure_context)
    
    # Create run-scoped storage
    proposal_storage = {"proposal": None}
    tool = agent._create_submit_proposal_tool(proposal_storage)
    
    # Initially no proposal stored
    assert proposal_storage["proposal"] is None
    
    # Submit a proposal
    await tool.handler({
        "identified_issue": "npm install failed",
        "fix_effort": "medium",
        "remediation_plan": "Update package.json and run npm install"
    })
    
    # Proposal should be stored in run-scoped storage
    assert proposal_storage["proposal"] is not None
    assert proposal_storage["proposal"].identified_issue == "npm install failed"
    assert proposal_storage["proposal"].fix_effort == "medium"
    assert proposal_storage["proposal"].remediation_plan == "Update package.json and run npm install"


@pytest.mark.asyncio
async def test_submit_proposal_errors_on_duplicate_call(settings, failure_context):
    agent = ActionTriageAgent(settings)
    await agent.prepare(failure_context)
    
    # Create run-scoped storage
    proposal_storage = {"proposal": None}
    tool = agent._create_submit_proposal_tool(proposal_storage)
    
    # First call succeeds
    await tool.handler({
        "identified_issue": "First issue",
        "fix_effort": "small",
        "remediation_plan": "First plan"
    })
    
    # Second call should raise error
    with pytest.raises(RuntimeError, match="Proposal already submitted"):
        await tool.handler({
            "identified_issue": "Second issue",
            "fix_effort": "large",
            "remediation_plan": "Second plan"
        })


@pytest.mark.asyncio
async def test_submit_proposal_returns_success_message(settings, failure_context):
    agent = ActionTriageAgent(settings)
    await agent.prepare(failure_context)
    
    # Create run-scoped storage
    proposal_storage = {"proposal": None}
    tool = agent._create_submit_proposal_tool(proposal_storage)
    
    result = await tool.handler({
        "identified_issue": "Test issue",
        "fix_effort": "medium",
        "remediation_plan": "Test plan"
    })
    
    assert isinstance(result, dict)
    assert "content" in result
    assert len(result["content"]) > 0
    assert result["content"][0]["type"] == "text"
    text = result["content"][0]["text"]
    assert "success" in text.lower() or "submitted" in text.lower()


@pytest.mark.asyncio
async def test_concurrent_diagnoses_have_isolated_proposal_storage(settings, failure_context):
    """Verify that multiple concurrent diagnose_and_propose calls don't interfere."""
    agent = ActionTriageAgent(settings)
    
    # Simulate two concurrent analysis runs with separate storage
    storage_run1 = {"proposal": None}
    storage_run2 = {"proposal": None}
    
    tool_run1 = agent._create_submit_proposal_tool(storage_run1)
    tool_run2 = agent._create_submit_proposal_tool(storage_run2)
    
    # Submit proposal in run 1
    await tool_run1.handler({
        "identified_issue": "Issue from run 1",
        "fix_effort": "small",
        "remediation_plan": "Plan for run 1"
    })
    
    # Submit proposal in run 2
    await tool_run2.handler({
        "identified_issue": "Issue from run 2",
        "fix_effort": "large",
        "remediation_plan": "Plan for run 2"
    })
    
    # Each storage should contain its own proposal
    assert storage_run1["proposal"] is not None
    assert storage_run1["proposal"].identified_issue == "Issue from run 1"
    assert storage_run1["proposal"].fix_effort == "small"
    
    assert storage_run2["proposal"] is not None
    assert storage_run2["proposal"].identified_issue == "Issue from run 2"
    assert storage_run2["proposal"].fix_effort == "large"
    
    # Verify they're different objects
    assert storage_run1["proposal"] is not storage_run2["proposal"]


@pytest.mark.asyncio
async def test_claude_agent_uses_configured_model_and_env(settings, failure_context):
    """Verify that ClaudeAgentOptions receives model and API key from settings."""
    from unittest.mock import patch
    
    # Create custom settings with specific model
    custom_settings = Settings(
        anthropic_api_key="test-api-key-123",
        claude_model="claude-3-opus-20240229",
        claude_max_turns=10
    )
    
    captured_options = None
    captured_tool = None
    
    # Patch _create_submit_proposal_tool to capture the tool
    original_create = ActionTriageAgent._create_submit_proposal_tool
    def patched_create(self, storage):
        nonlocal captured_tool
        captured_tool = original_create(self, storage)
        return captured_tool
    
    class MockClaudeSDKClient:
        def __init__(self, options):
            nonlocal captured_options
            captured_options = options
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            from dataclasses import dataclass
            @dataclass
            class ResultMessage:
                subtype: str = "success"
                duration_ms: int = 1000
                duration_api_ms: int = 900
                is_error: bool = False
                num_turns: int = 1
                session_id: str = "test"
            
            # Call the captured tool directly
            if captured_tool:
                await captured_tool.handler({
                    "identified_issue": "Test issue",
                    "fix_effort": "small",
                    "remediation_plan": "Test plan"
                })
            
            yield ResultMessage()
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch.object(ActionTriageAgent, '_create_submit_proposal_tool', patched_create):
        with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', MockClaudeSDKClient):
            agent = ActionTriageAgent(custom_settings)
            proposal = await agent.diagnose_and_propose(failure_context)
            
            # Verify ClaudeAgentOptions was configured correctly
            assert captured_options is not None
            assert captured_options.max_turns == 10
            assert captured_options.model == "claude-3-opus-20240229"
            
            # Verify API key is passed via env
            assert hasattr(captured_options, 'env')
            assert captured_options.env.get('ANTHROPIC_API_KEY') == "test-api-key-123"
            
            # Verify proposal was extracted
            assert proposal is not None
            assert proposal.identified_issue == "Test issue"


@pytest.mark.asyncio
async def test_tool_schema_is_valid_json_schema(settings, failure_context):
    """Verify that submit_proposal tool uses proper JSON Schema format."""
    from unittest.mock import patch
    
    captured_options = None
    captured_tool = None
    
    # Patch _create_submit_proposal_tool to capture the tool
    original_create = ActionTriageAgent._create_submit_proposal_tool
    def patched_create(self, storage):
        nonlocal captured_tool
        captured_tool = original_create(self, storage)
        return captured_tool
    
    class MockClaudeSDKClient:
        def __init__(self, options):
            nonlocal captured_options
            captured_options = options
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            from dataclasses import dataclass
            @dataclass
            class ResultMessage:
                subtype: str = "success"
                duration_ms: int = 1000
                duration_api_ms: int = 900
                is_error: bool = False
                num_turns: int = 1
                session_id: str = "test"
            
            # Call the captured tool directly
            if captured_tool:
                await captured_tool.handler({
                    "identified_issue": "Test",
                    "fix_effort": "small",
                    "remediation_plan": "Test plan"
                })
            yield ResultMessage()
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch.object(ActionTriageAgent, '_create_submit_proposal_tool', patched_create):
        with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', MockClaudeSDKClient):
            agent = ActionTriageAgent(settings)
            await agent.diagnose_and_propose(failure_context)
            
            # Verify the captured tool has proper JSON Schema structure
            assert captured_tool is not None
            assert hasattr(captured_tool, 'input_schema')
            schema = captured_tool.input_schema
            
            # Should have type and properties keys, not just parameter types
            assert 'type' in schema
            assert schema['type'] == 'object'
            assert 'properties' in schema
            assert 'required' in schema


@pytest.mark.asyncio
async def test_analysis_timeout_raises_asyncio_timeout_error(settings, failure_context):
    """Verify that analysis enforces timeout and raises asyncio.TimeoutError."""
    import asyncio
    from unittest.mock import patch
    
    # Create settings with very short timeout
    timeout_settings = Settings(
        anthropic_api_key="test-key",
        analysis_timeout_seconds=1  # 1 second timeout
    )
    
    class SlowMockClaudeSDKClient:
        def __init__(self, options):
            pass
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            # Simulate slow response that exceeds timeout
            await asyncio.sleep(5)
            yield None
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', SlowMockClaudeSDKClient):
        agent = ActionTriageAgent(timeout_settings)
        
        # Should raise asyncio.TimeoutError
        with pytest.raises(asyncio.TimeoutError):
            await agent.diagnose_and_propose(failure_context)


@pytest.mark.asyncio
async def test_diagnose_and_propose_multi_turn_conversation(settings, failure_context, monkeypatch):
    """Integration test verifying multi-turn conversation with ClaudeSDKClient.
    
    Simulates Claude asking follow-up questions before submitting proposal:
    1. Initial analysis question (TextBlock)
    2. Request for more context (TextBlock)
    3. Final submit_proposal tool call (ToolUseBlock)
    """
    from unittest.mock import AsyncMock, MagicMock, patch
    from dataclasses import dataclass
    
    # Define mock message types matching claude_agent_sdk structure
    @dataclass
    class TextBlock:
        text: str
    
    @dataclass
    class ToolUseBlock:
        id: str
        name: str
        input: dict
    
    @dataclass
    class AssistantMessage:
        content: list
        model: str = "claude-3-5-sonnet-20241022"
    
    @dataclass
    class ResultMessage:
        subtype: str
        duration_ms: int
        duration_api_ms: int
        is_error: bool
        num_turns: int
        session_id: str
        total_cost_usd: float | None = None
        usage: dict | None = None
        result: str | None = None
    
    # Create mock messages simulating multi-turn conversation
    turn1_message = AssistantMessage(content=[
        TextBlock(text="I'm analyzing the npm install failure. Let me check the workflow file.")
    ])
    
    turn2_message = AssistantMessage(content=[
        TextBlock(text="I see the issue. The workflow is missing a dependency specification.")
    ])
    
    turn3_message = AssistantMessage(content=[
        ToolUseBlock(
            id="toolu_123",
            name="submit_proposal",
            input={
                "identified_issue": "npm install failed due to missing package-lock.json",
                "fix_effort": "small",
                "remediation_plan": "1. Run npm install locally\n2. Commit package-lock.json\n3. Re-run workflow"
            }
        )
    ])
    
    result_message = ResultMessage(
        subtype="success",
        duration_ms=5000,
        duration_api_ms=4500,
        is_error=False,
        num_turns=3,
        session_id="test-session-123"
    )
    
    # Capture the tool so we can invoke it in the mock
    captured_tool = None
    
    # Patch _create_submit_proposal_tool to capture the tool
    original_create = ActionTriageAgent._create_submit_proposal_tool
    def patched_create(self, storage):
        nonlocal captured_tool
        captured_tool = original_create(self, storage)
        return captured_tool
    
    # Create a custom mock client that simulates multi-turn conversation
    class MockClaudeSDKClient:
        def __init__(self, options):
            self.options = options
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            # Turn 1: Initial analysis
            yield turn1_message
            
            # Turn 2: Follow-up analysis
            yield turn2_message
            
            # Turn 3: Invoke submit_proposal tool directly
            if captured_tool:
                await captured_tool.handler({
                    "identified_issue": "npm install failed due to missing package-lock.json",
                    "fix_effort": "small",
                    "remediation_plan": "1. Run npm install locally\n2. Commit package-lock.json\n3. Re-run workflow"
                })
            
            # Yield the tool use message and final result
            yield turn3_message
            yield result_message
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    # Patch both the tool creation and ClaudeSDKClient
    with patch.object(ActionTriageAgent, '_create_submit_proposal_tool', patched_create):
        with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', MockClaudeSDKClient):
            # Create agent and run diagnose_and_propose
            agent = ActionTriageAgent(settings)
            
            # Should now successfully complete without NotImplementedError
            proposal = await agent.diagnose_and_propose(failure_context)
            
            # Verify proposal extracted from submit_proposal tool call
            assert proposal is not None
            assert proposal.identified_issue == "npm install failed due to missing package-lock.json"
            assert proposal.fix_effort == "small"
            assert proposal.remediation_plan == "1. Run npm install locally\n2. Commit package-lock.json\n3. Re-run workflow"


@pytest.mark.asyncio
async def test_system_prompt_states_no_local_access_without_mcp(settings, failure_context):
    """Verify system prompt warns about no local access even when Sourcegraph MCP is disabled."""
    from unittest.mock import patch
    
    # Settings without Sourcegraph token (MCP disabled)
    settings_no_mcp = Settings(
        anthropic_api_key="test-key",
        sourcegraph_token="",  # Empty token = no MCP
        sourcegraph_mcp_url=""
    )
    
    captured_options = None
    
    class MockClaudeSDKClient:
        def __init__(self, options):
            nonlocal captured_options
            captured_options = options
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            from dataclasses import dataclass
            @dataclass
            class ResultMessage:
                subtype: str = "success"
                duration_ms: int = 1000
                duration_api_ms: int = 900
                is_error: bool = False
                num_turns: int = 1
                session_id: str = "test"
            
            # Just yield result without calling tool (we'll check for the expected error)
            yield ResultMessage()
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', MockClaudeSDKClient):
        agent = ActionTriageAgent(settings_no_mcp)
        
        # We expect this to raise RuntimeError because we don't submit a proposal
        # But we can still check the prompt was configured correctly
        with pytest.raises(RuntimeError, match="no proposal was submitted"):
            await agent.diagnose_and_propose(failure_context)
        
        # Verify system prompt contains warning about no local access
        assert captured_options is not None
        system_prompt = captured_options.system_prompt
        assert "do not have a local checkout" in system_prompt.lower()
        assert "do not assume direct filesystem access" in system_prompt.lower()


@pytest.mark.asyncio
async def test_system_prompt_emphasizes_sourcegraph_mcp_when_enabled(settings, failure_context):
    """Verify system prompt emphasizes Sourcegraph MCP usage when configured."""
    from unittest.mock import patch
    
    # Settings with Sourcegraph configured (MCP enabled)
    settings_with_mcp = Settings(
        anthropic_api_key="test-key",
        sourcegraph_token="test-sg-token",
        sourcegraph_mcp_url="https://sourcegraph.example.com/mcp"
    )
    
    captured_options = None
    
    class MockClaudeSDKClient:
        def __init__(self, options):
            nonlocal captured_options
            captured_options = options
        
        async def query(self, prompt):
            pass
        
        async def receive_response(self):
            from dataclasses import dataclass
            @dataclass
            class ResultMessage:
                subtype: str = "success"
                duration_ms: int = 1000
                duration_api_ms: int = 900
                is_error: bool = False
                num_turns: int = 1
                session_id: str = "test"
            
            # Just yield result without calling tool (we'll check for the expected error)
            yield ResultMessage()
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    with patch('github_action_triage.agent.ai_agent.ClaudeSDKClient', MockClaudeSDKClient):
        agent = ActionTriageAgent(settings_with_mcp)
        
        # We expect this to raise RuntimeError because we don't submit a proposal
        # But we can still check the prompt was configured correctly
        with pytest.raises(RuntimeError, match="no proposal was submitted"):
            await agent.diagnose_and_propose(failure_context)
        
        # Verify system prompt emphasizes Sourcegraph MCP as exclusive access method
        assert captured_options is not None
        system_prompt = captured_options.system_prompt
        
        # Should contain base warning
        assert "do not have a local checkout" in system_prompt.lower()
        
        # Should contain MCP-specific emphasis
        assert "Remote Repository Access" in system_prompt
        assert "All repository code inspection must happen through the Sourcegraph MCP server" in system_prompt
        assert "the ONLY way to read repository files" in system_prompt
        assert "the ONLY way to list repository contents" in system_prompt
        assert "Use these MCP tools exclusively" in system_prompt
