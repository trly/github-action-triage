import pytest
from unittest.mock import AsyncMock, MagicMock
from github_action_triage.app.infra.github_issue_creator import GitHubIssueCreatorAdapter
from github_action_triage.agent.ports import (
    WorkflowRunFailureEvent,
    RepositoryRef,
    WorkflowRef,
    FailureSummary,
    RemediationProposal,
)
from github_action_triage.app.config.settings import Settings


@pytest.fixture
def settings():
    return Settings(
        github_app_id="12345",
        github_private_key="test-key",
        github_webhook_secret="test-secret",
        anthropic_api_key="test-api-key",
    )


@pytest.fixture
def failure_event():
    return WorkflowRunFailureEvent(
        installation_id=67890,
        repository=RepositoryRef(owner="test-owner", name="test-repo"),
        workflow=WorkflowRef(
            run_id="9876",
            job_id="5432",
            workflow_name="Test CI",
            job_name="unit-tests",
            run_url="https://github.com/test-owner/test-repo/actions/runs/9876",
        ),
        failure=FailureSummary(
            conclusion="failure",
            logs_snippet="AssertionError: expected 5, got 3",
        ),
    )


@pytest.fixture
def remediation_proposal():
    return RemediationProposal(
        issue_title="Test failure in authentication module",
        identified_issue="Test failure in authentication module",
        fix_effort="small",
        remediation_plan="1. Update test assertion\n2. Verify expected value\n3. Run tests",
    )


@pytest.mark.asyncio
async def test_create_issue_formats_body_correctly(
    settings, failure_event, remediation_proposal, monkeypatch
):
    # Arrange
    mock_app_client = MagicMock()
    mock_installation_client = MagicMock()
    
    # Mock installation token response
    mock_token_response = MagicMock()
    mock_token_response.parsed_data.token = "ghs_installationToken123"
    mock_app_client.rest.apps.async_create_installation_access_token = AsyncMock(
        return_value=mock_token_response
    )
    
    # Mock issue creation response
    mock_issue_response = MagicMock()
    mock_issue_response.parsed_data.html_url = "https://github.com/test-owner/test-repo/issues/42"
    mock_installation_client.rest.issues.async_create = AsyncMock(
        return_value=mock_issue_response
    )
    
    # Mock GitHub constructor to return appropriate clients
    from githubkit import GitHub
    github_calls = []
    def mock_github_constructor(auth=None):
        github_calls.append(auth)
        if len(github_calls) == 1:
            return mock_app_client
        else:
            return mock_installation_client
    monkeypatch.setattr("github_action_triage.app.infra.github_issue_creator.GitHub", mock_github_constructor)
    
    creator = GitHubIssueCreatorAdapter(settings=settings)
    
    # Act
    issue_url = await creator.create_issue_for_proposal(failure_event, remediation_proposal)
    
    # Assert
    assert issue_url == "https://github.com/test-owner/test-repo/issues/42"
    
    # Verify installation token was requested
    mock_app_client.rest.apps.async_create_installation_access_token.assert_called_once_with(
        installation_id=67890
    )
    
    # Verify issue was created with correct parameters
    mock_installation_client.rest.issues.async_create.assert_called_once()
    call_kwargs = mock_installation_client.rest.issues.async_create.call_args.kwargs
    
    assert call_kwargs["owner"] == "test-owner"
    assert call_kwargs["repo"] == "test-repo"
    assert call_kwargs["title"] == "Test failure in authentication module"
    assert call_kwargs["labels"] == ["triage", "ci"]
    
    # Verify body formatting
    body = call_kwargs["body"]
    assert "## Workflow Failure Detected" in body
    assert "**Workflow**: Test CI" in body
    assert "**Job**: unit-tests" in body
    assert "**Fix Effort**: small" in body
    assert "[View Failed Run](https://github.com/test-owner/test-repo/actions/runs/9876)" in body
    assert "## Identified Issue" in body
    assert "Test failure in authentication module" in body
    assert "## Remediation Plan" in body
    assert "1. Update test assertion" in body
    assert "2. Verify expected value" in body
    assert "3. Run tests" in body
    assert "automatically created by github-action-triage" in body


@pytest.mark.asyncio
async def test_create_issue_uses_correct_repository(
    settings, failure_event, remediation_proposal, monkeypatch
):
    # Arrange
    mock_app_client = MagicMock()
    mock_installation_client = MagicMock()
    
    mock_token_response = MagicMock()
    mock_token_response.parsed_data.token = "ghs_token"
    mock_app_client.rest.apps.async_create_installation_access_token = AsyncMock(
        return_value=mock_token_response
    )
    
    mock_issue_response = MagicMock()
    mock_issue_response.parsed_data.html_url = "https://github.com/test-owner/test-repo/issues/1"
    mock_installation_client.rest.issues.async_create = AsyncMock(
        return_value=mock_issue_response
    )
    
    from githubkit import GitHub
    github_calls = []
    def mock_github_constructor(auth=None):
        github_calls.append(auth)
        return mock_app_client if len(github_calls) == 1 else mock_installation_client
    monkeypatch.setattr("github_action_triage.app.infra.github_issue_creator.GitHub", mock_github_constructor)
    
    # Create event with different repository
    different_event = WorkflowRunFailureEvent(
        installation_id=99999,
        repository=RepositoryRef(owner="different-org", name="different-repo"),
        workflow=WorkflowRef(
            run_id="111",
            job_id="222",
            workflow_name="Other Workflow",
            job_name="other-job",
            run_url="https://github.com/different-org/different-repo/actions/runs/111",
        ),
        failure=FailureSummary(
            conclusion="failure",
            logs_snippet="Error occurred",
        ),
    )
    
    creator = GitHubIssueCreatorAdapter(settings=settings)
    
    # Act
    await creator.create_issue_for_proposal(different_event, remediation_proposal)
    
    # Assert
    call_kwargs = mock_installation_client.rest.issues.async_create.call_args.kwargs
    assert call_kwargs["owner"] == "different-org"
    assert call_kwargs["repo"] == "different-repo"
    
    # Verify correct installation ID was used
    mock_app_client.rest.apps.async_create_installation_access_token.assert_called_once_with(
        installation_id=99999
    )


@pytest.mark.asyncio
async def test_create_issue_handles_api_failure(
    settings, failure_event, remediation_proposal, monkeypatch
):
    # Arrange
    mock_app_client = MagicMock()
    mock_installation_client = MagicMock()
    
    mock_token_response = MagicMock()
    mock_token_response.parsed_data.token = "ghs_token"
    mock_app_client.rest.apps.async_create_installation_access_token = AsyncMock(
        return_value=mock_token_response
    )
    
    # Simulate API failure
    mock_installation_client.rest.issues.async_create = AsyncMock(
        side_effect=Exception("GitHub API error: rate limit exceeded")
    )
    
    from githubkit import GitHub
    github_calls = []
    def mock_github_constructor(auth=None):
        github_calls.append(auth)
        return mock_app_client if len(github_calls) == 1 else mock_installation_client
    monkeypatch.setattr("github_action_triage.app.infra.github_issue_creator.GitHub", mock_github_constructor)
    
    creator = GitHubIssueCreatorAdapter(settings=settings)
    
    # Act & Assert
    with pytest.raises(Exception, match="GitHub API error: rate limit exceeded"):
        await creator.create_issue_for_proposal(failure_event, remediation_proposal)


@pytest.mark.asyncio
async def test_create_issue_handles_installation_token_failure(
    settings, failure_event, remediation_proposal, monkeypatch
):
    # Arrange
    mock_app_client = MagicMock()
    mock_app_client.rest.apps.async_create_installation_access_token = AsyncMock(
        side_effect=Exception("Installation not found")
    )
    
    from githubkit import GitHub
    monkeypatch.setattr(
        "github_action_triage.app.infra.github_issue_creator.GitHub",
        lambda auth=None: mock_app_client
    )
    
    creator = GitHubIssueCreatorAdapter(settings=settings)
    
    # Act & Assert
    with pytest.raises(Exception, match="Installation not found"):
        await creator.create_issue_for_proposal(failure_event, remediation_proposal)


@pytest.mark.asyncio
async def test_format_issue_body_includes_all_required_sections(
    settings, failure_event, remediation_proposal, monkeypatch
):
    # Arrange
    mock_app_client = MagicMock()
    mock_installation_client = MagicMock()
    
    mock_token_response = MagicMock()
    mock_token_response.parsed_data.token = "ghs_token"
    mock_app_client.rest.apps.async_create_installation_access_token = AsyncMock(
        return_value=mock_token_response
    )
    
    mock_issue_response = MagicMock()
    mock_issue_response.parsed_data.html_url = "https://github.com/test-owner/test-repo/issues/1"
    mock_installation_client.rest.issues.async_create = AsyncMock(
        return_value=mock_issue_response
    )
    
    from githubkit import GitHub
    github_calls = []
    def mock_github_constructor(auth=None):
        github_calls.append(auth)
        return mock_app_client if len(github_calls) == 1 else mock_installation_client
    monkeypatch.setattr("github_action_triage.app.infra.github_issue_creator.GitHub", mock_github_constructor)
    
    # Test with "large" fix effort
    large_effort_proposal = RemediationProposal(
        issue_title="Complex authentication refactor needed",
        identified_issue="Complex authentication refactor needed",
        fix_effort="large",
        remediation_plan="1. Audit current auth\n2. Design new system\n3. Implement\n4. Test thoroughly",
    )
    
    creator = GitHubIssueCreatorAdapter(settings=settings)
    
    # Act
    await creator.create_issue_for_proposal(failure_event, large_effort_proposal)
    
    # Assert
    call_kwargs = mock_installation_client.rest.issues.async_create.call_args.kwargs
    body = call_kwargs["body"]
    
    # Verify all required sections
    assert "## Workflow Failure Detected" in body
    assert "**Workflow**:" in body
    assert "**Job**:" in body
    assert "**Run**:" in body
    assert "**Fix Effort**: large" in body
    assert "## Identified Issue" in body
    assert "## Remediation Plan" in body
    
    # Verify markdown link syntax
    assert "[View Failed Run](" in body
    assert "](https://github.com/test-owner/test-repo/actions/runs/9876)" in body
