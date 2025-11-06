# Agent Development Guide

This file contains instructions and preferences for AI agents working on the github-action-triage codebase.

## Project Overview

GitHub Action Triage is a FastAPI-based service that receives GitHub workflow failure webhooks, analyzes failures using AI, and proposes or applies automated fixes.

**Architecture Pattern**: Clean Architecture with Ports & Adapters (Hexagonal)

- `app/` package: Application layer (web, events, infra adapters)
- `agent/` package: Domain ports and AI integrations
- Protocol-based dependency injection for testability

## Essential Commands

### Testing

```bash
# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_app_events.py -v

# Run tests with coverage
uv run pytest --cov=src/github_action_triage
```

### Development Server

```bash
# Start development server with auto-reload
uv run poe dev

# Alternative
uv run uvicorn main:app --reload
```

### Dependency Management

```bash
# Sync dependencies (including dev)
uv sync --group dev

# Add new dependency
uv add <package-name>

# Install project in editable mode
uv pip install -e .
```

## Architecture Principles

### Clean Architecture

- **Separation of Concerns**: Keep web layer, domain logic, and infrastructure adapters separate
- **Dependency Rule**: Dependencies point inward (infra → app → agent ports)
- **Protocol-Based Ports**: Use `Protocol` classes to define interfaces for external services

### Module Organization

```
src/github_action_triage/
├── app/                      # Application layer
│   ├── web/                  # HTTP/FastAPI concerns
│   ├── events/               # Domain models and value objects
│   ├── config/               # Configuration management
│   ├── infra/                # External service adapters
│   └── api.py                # Service orchestration
└── agent/                    # Domain ports
    ├── ports.py              # Protocol definitions
    └── ai_agent.py           # AI integrations
```

### Key Patterns

1. **Ports & Adapters**
   - Define ports as `Protocol` classes in `agent/ports.py`
   - Implement adapters in `app/infra/` that conform to protocols
   - Enables testing with mocks and easy adapter swapping

2. **Immutable Models**
   - Use Pydantic models with `model_config = ConfigDict(frozen=True)`
   - Domain events and value objects should be immutable

3. **Dependency Injection**
   - Use FastAPI's `Depends()` for service injection
   - Constructor injection for services and adapters
   - See `app/web/api.py` for examples

4. **Factory Pattern**
   - FastAPI app created via `create_app()` factory in `app/factory.py`
   - Enables testing and configuration flexibility

## Code Style & Conventions

### General

- **Immutability**: Prefer frozen Pydantic models for domain objects
- **Type Hints**: Always use type hints for function signatures
- **Pydantic V2**: Use `ConfigDict` instead of class-based `Config`
- **No Comments**: Code should be self-documenting; avoid comments unless truly necessary

### Testing

- **Test-First Development**: Write tests before implementation
- **Test Public APIs**: Test through public interfaces, not implementation details
- **Async Tests**: Use `@pytest.mark.asyncio` for async test functions (automatically applied via pytest config)
- **Mocking**: Use `unittest.mock.AsyncMock` for protocol implementations

### Configuration

- **Environment Variables**: All config via environment variables with `TRIAGE_` prefix
- **Pydantic Settings**: Use `pydantic_settings.BaseSettings` for config classes
- **No Secrets in Code**: Never hardcode API keys, tokens, or secrets

### GitHubKit Types

- **Webhook Event Types**: GitHubKit's event types (e.g., `WorkflowJobEvent`) are `Annotated` union types, not concrete classes
- **Use Concrete Types**: For `isinstance()` checks, import concrete types from `githubkit.versions.latest.models`
  - Example: `WebhookWorkflowJobCompleted` instead of `WorkflowJobEvent`
  - Always use `.latest` to match the default behavior of `githubkit.webhooks.parse()`
- **Type Narrowing**: Use `TypeGuard` return type for type-checking functions that filter webhook events
  - This enables proper type narrowing within conditional blocks
  - Example: `def is_failure_workflow_job(event: WebhookEvent) -> TypeGuard[WebhookWorkflowJobCompleted]`

## Testing Philosophy

1. **Write tests first** to specify desired behavior
2. **Test the contract**, not the implementation
3. **Mock external dependencies** using Protocol types
4. **Use descriptive test names** that explain what is being tested

Example test structure:

```python
@pytest.mark.asyncio
async def test_service_handles_expected_input():
    # Arrange
    mock_port = AsyncMock(spec=MyProtocol)
    service = MyService(dependency=mock_port)

    # Act
    result = await service.do_something(input_data)

    # Assert
    assert result.outcome == ExpectedOutcome.SUCCESS
```

## Package Structure Notes

- **src/ layout**: Package code lives in `src/github_action_triage/`
- **Editable install**: Project must be installed with `uv pip install -e .` for imports to work
- **pytest discovery**: Tests in `tests/` directory, automatically discovered

## Common Tasks

### Adding a New Event Model

1. Define model in `app/events/models.py` with `ConfigDict(frozen=True)`
2. Add corresponding test in `tests/test_app_events.py`
3. Update relevant service methods to handle new event type

### Adding a New Port

1. Define `Protocol` in `agent/ports.py`
2. Create stub adapter in `app/infra/` that raises `NotImplementedError`
3. Add tests that verify the port contract
4. Implement adapter functionality when ready

### Adding a New Endpoint

1. Add route to `app/web/api.py` router
2. Create request/response models if needed
3. Wire dependencies via `Depends()`
4. Test via integration test or manual curl

## Dependencies

- **FastAPI**: Web framework
- **Pydantic**: Data validation and settings
- **PydanticAI**: AI agent framework (planned integration)
- **GitHubKit**: GitHub API client (planned integration)
- **pytest + pytest-asyncio**: Testing framework

## Environment Variables

Configuration uses `TRIAGE_` prefix:

- `TRIAGE_GITHUB_APP_ID`: GitHub App ID
- `TRIAGE_GITHUB_PRIVATE_KEY`: GitHub App private key
- `TRIAGE_GITHUB_WEBHOOK_SECRET`: Webhook verification secret
- `TRIAGE_OPENAI_API_KEY`: OpenAI API key for AI features

## Current Implementation Status

**Scaffold Phase Complete**

- ✅ Package structure established
- ✅ Domain models and protocols defined
- ✅ FastAPI routing configured
- ✅ Infrastructure adapter skeletons in place
- ⏳ GitHub API integration (stubbed)
- ⏳ AI-powered diagnosis (stubbed)
- ⏳ Automated fix application (stubbed)

## When Working on This Codebase

1. **Always run tests** after making changes: `uv run pytest`
2. **Follow the existing patterns** in the codebase
3. **Keep concerns separated** - don't mix web logic with domain logic
4. **Test through protocols** - use mocks for external dependencies
5. **Update this file** if you add new commands or patterns

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Pydantic V2 Documentation](https://docs.pydantic.dev/latest/)
- [GitHubKit Documentation](https://yanyongyu.github.io/githubkit/)
- [PydanticAI Documentation](https://ai.pydantic.dev/)

