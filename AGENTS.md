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

## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Auto-syncs to JSONL for version control
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" -t bug|feature|task -p 0-4 --json
bd create "Issue title" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update bd-42 --status in_progress --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready --json` shows unblocked issues
2. **Claim your task**: `bd update <id> --status in_progress`
3. **Create a work change**: `jj new 'Descriptive commit message for your work'`
   - This creates a new empty change with your description
   - All your work will go into this change
   - Use a clear, imperative commit message (e.g., "Add GitHub API authentication", "Fix webhook parsing bug")
   - Include context about what problem is being solved or feature is being added
4. **Work on it**: Implement, test, document
   - Make edits to files normally
   - Use `jj diff` to review changes
   - Run tests frequently: `uv run pytest`
   - Do NOT commit yet; changes accumulate in your working change
5. **Discover new work?** Create linked issues for problems found during work:
   - Use: `bd create "Issue title" -t bug|feature|task -p 0-4 --deps discovered-from:<parent-id> --json`
   - Example: `bd create "Add validation for webhook signatures" -t task -p 1 --deps discovered-from:bd-42 --json`
   - Always link discovered work with `discovered-from` to track where the issue originated
   - This maintains traceability and helps understand dependencies across work items
6. **Complete**: Mark issue as done: `bd close <id> --reason "Completed"`
7. **Squash work**: After closing the issue, consolidate all changes: `jj squash`
   - This moves accumulated changes into the single, well-described commit you created in step 3
   - The working copy becomes empty after squash
8. **Sync state**: The `.beads/issues.jsonl` file auto-syncs when you run bd commands
   - No manual commits of this file needed; the workflow is complete

### Auto-Sync

bd automatically syncs with git:

- Exports to `.beads/issues.jsonl` after changes (5s debounce)
- Imports from JSONL when newer (e.g., after `git pull`)
- No manual export/import needed!

### MCP Server (Recommended)

If using Claude or MCP-compatible clients, install the beads MCP server:

```bash
pip install beads-mcp
```

Add to MCP config (e.g., `~/.config/claude/config.json`):

```json
{
  "beads": {
    "command": "beads-mcp",
    "args": []
  }
}
```

Then use `mcp__beads__*` functions instead of CLI commands.

### Managing AI-Generated Planning Documents

AI assistants often create planning and design documents during development:

- PLAN.md, IMPLEMENTATION.md, ARCHITECTURE.md
- DESIGN.md, CODEBASE_SUMMARY.md, INTEGRATION_PLAN.md
- TESTING_GUIDE.md, TECHNICAL_DESIGN.md, and similar files

**Best Practice: Use a dedicated directory for these ephemeral files**

**Recommended approach:**

- Create a `history/` directory in the project root
- Store ALL AI-generated planning/design docs in `history/`
- Keep the repository root clean and focused on permanent project files
- Only access `history/` when explicitly asked to review past planning

**Example .gitignore entry (optional):**

```
# AI planning documents (ephemeral)
history/
```

**Benefits:**

- ✅ Clean repository root
- ✅ Clear separation between ephemeral and permanent documentation
- ✅ Easy to exclude from version control if desired
- ✅ Preserves planning history for archeological research
- ✅ Reduces noise when browsing the project

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ✅ Store AI planning docs in `history/` directory
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems
- ❌ Do NOT clutter repo root with planning documents

For more details, see README.md and QUICKSTART.md.

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
- **Claude Agent SDK**: AI agent framework via Anthropic API
- **GitHubKit**: GitHub API client
- **Sourcegraph MCP**: Code analysis and search capabilities
- **pytest + pytest-asyncio**: Testing framework

## Environment Variables

Configuration uses `TRIAGE_` prefix:

- `TRIAGE_GITHUB_APP_ID`: GitHub App ID
- `TRIAGE_GITHUB_PRIVATE_KEY`: GitHub App private key
- `TRIAGE_GITHUB_WEBHOOK_SECRET`: Webhook verification secret
- `TRIAGE_ANTHROPIC_API_KEY`: Anthropic API key for Claude Agent SDK
- `TRIAGE_SOURCEGRAPH_TOKEN`: Sourcegraph access token for MCP integration
- `TRIAGE_SOURCEGRAPH_MCP_URL`: Sourcegraph MCP server URL
- `TRIAGE_REDIS_URL`: Redis URL for Celery broker and result backend (default: redis://localhost:6379/0)

## Current Implementation Status

**Core Features Implemented**

- ✅ Package structure established
- ✅ Domain models and protocols defined
- ✅ FastAPI routing configured
- ✅ Infrastructure adapter implementations
- ✅ GitHub API integration via GitHubKit
- ✅ AI-powered diagnosis via Claude Agent SDK
- ✅ Background processing via FastAPI BackgroundTasks
- ✅ Comment posting to workflow runs and commits
- ✅ Sourcegraph MCP integration for code analysis
- ⏳ Automated fix application (in progress)

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
- [Claude Agent SDK Documentation](https://github.com/anthropics/anthropic-sdk-python)
