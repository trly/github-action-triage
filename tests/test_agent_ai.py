import pytest
from github_action_triage.agent.ai_agent import PydanticAIRemediationAgent
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
    return Settings(openai_api_key="test-key")


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
    agent = PydanticAIRemediationAgent(settings)
    
    # Initially no context
    assert agent._last_context is None
    
    # Prepare should store the context
    await agent.prepare(failure_context)
    
    assert agent._last_context is not None
    assert agent._last_context.repository_full_name == "test-org/test-repo"
    assert agent._last_context.head_commit_sha == "abc123"


@pytest.mark.asyncio
async def test_diagnose_and_propose_still_raises(settings, failure_context):
    agent = PydanticAIRemediationAgent(settings)
    
    with pytest.raises(NotImplementedError, match="LLM integration pending"):
        await agent.diagnose_and_propose(failure_context)
