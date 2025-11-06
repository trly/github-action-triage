# GitHub Action Triage

Automated CI/CD failure analysis and remediation using AI agents.

## Overview

This service receives GitHub workflow failure webhooks, analyzes the failure context using AI, and proposes or applies automated fixes to resolve build issues.

## Architecture

The project follows a clean architecture pattern with clear separation of concerns:

```
src/github_action_triage/
├── app/                      # Application layer
│   ├── web/                  # FastAPI routers and HTTP concerns
│   │   └── api.py           # Webhook endpoints
│   ├── events/              # Domain models and events
│   │   ├── models.py        # Event DTOs (WorkflowRunFailureEvent, etc.)
│   │   └── outcomes.py      # Triage result enums
│   ├── config/              # Configuration management
│   │   └── settings.py      # Environment-based settings
│   ├── infra/               # Infrastructure adapters
│   │   └── github_client.py # GitHub API integration
│   ├── api.py               # Core triage service orchestration
│   └── factory.py           # FastAPI application factory
└── agent/                   # Agent layer
    ├── ports.py             # Protocol definitions for external services
    └── ai_agent.py          # PydanticAI remediation agent
```

### Key Components

- **App Package**: Webhook routing, event models, infrastructure adapters
- **Agent Package**: External service protocols, AI integrations
- **Ports Pattern**: Protocol-based dependency injection for testability and flexibility

### Data Flow

1. GitHub webhook → FastAPI endpoint (`/github/webhook`)
2. Triage service orchestrates:
   - Context gathering via `GitHubContextProvider`
   - Diagnosis via `RemediationAgent`
   - Fix application via `RepositoryActuator`
3. Returns triage outcome (DEFERRED, FIX_APPLIED, UNSUPPORTED)

## Development

### Prerequisites

- Python >=3.14
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

```bash
# Install dependencies
uv sync --group dev

# Install package in editable mode (required for imports to work)
uv pip install -e .
```

### Running the Service

```bash
# Start development server with auto-reload
uv run poe dev

# Or manually
uv run uvicorn main:app --reload
```

The API will be available at:

- http://localhost:8000
- Docs: http://localhost:8000/docs
- Health check: http://localhost:8000/github/health

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/github_action_triage

# Run specific test file
uv run pytest tests/test_app_events.py -v
```

### Configuration

The service is configured via environment variables with the `TRIAGE_` prefix:

```bash
export TRIAGE_GITHUB_APP_ID="your-app-id"
export TRIAGE_GITHUB_PRIVATE_KEY="your-private-key"
export TRIAGE_GITHUB_WEBHOOK_SECRET="your-webhook-secret"
export TRIAGE_OPENAI_API_KEY="your-openai-key"
```

## Current Status

**Phase: Scaffold Complete**

- ✅ Package structure established
- ✅ Domain models and protocols defined
- ✅ FastAPI routing configured
- ✅ Infrastructure adapter skeletons in place
- ⏳ GitHub API integration (not implemented)
- ⏳ AI-powered diagnosis (not implemented)
- ⏳ Automated fix application (not implemented)

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [GitHubKit Documentation](https://yanyongyu.github.io/githubkit/)
- [PydanticAI Documentation](https://ai.pydantic.dev/)

## Contributing

1. Write tests first to specify behavior
2. Implement to satisfy tests
3. Ensure all tests pass: `uv run pytest`
4. Verify server boots: `uv run poe dev`

