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
│   │   ├── github_client.py # GitHub API integration
│   │   └── github_issue_creator.py # GitHub issue creation
│   ├── llm/                 # LLM integrations
│   │   └── mcp.py           # MCP client configuration
│   ├── api.py               # Core triage service orchestration
│   ├── celery_app.py        # Celery application configuration
│   └── factory.py           # FastAPI application factory
├── agent/                   # Agent layer
│   ├── analysis/            # Analysis agent implementation
│   │   ├── agent.py         # Core analysis agent (pydantic-ai)
│   │   ├── config.py        # Analysis agent configuration
│   │   ├── instructions.py  # Agent instruction builders
│   │   └── tools/           # Agent tool integrations
│   │       ├── github.py    # GitHub API tools
│   │       └── sourcegraph.py # Sourcegraph code search tools
│   ├── ports.py             # Protocol definitions for external services
│   ├── config.py            # Agent configuration
│   └── mcp.py               # MCP tool integrations
└── tasks/                   # Background task layer
    └── triage.py            # Celery tasks for async triage processing
```

### Key Components

- **App Package**: Webhook routing, event models, infrastructure adapters, LLM clients
- **Agent Package**: External service protocols, AI integrations, MCP tool configurations
- **Tasks Package**: Celery background tasks for asynchronous processing
- **Ports Pattern**: Protocol-based dependency injection for testability and flexibility

### Data Flow

1. GitHub webhook → FastAPI endpoint (`/github/webhook`)
2. Webhook handler enqueues Celery task
3. Returns 200 OK immediately
4. Celery worker processes task asynchronously:
   - Context gathering via `GitHubContextProvider`
   - Diagnosis via `RemediationAgent` (with MCP tools)
   - Comment posting or issue creation via `IssueCreator`

## Development

### Prerequisites

- Python >=3.14
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

```bash
# Clone the repository
git clone https://github.com/trly/github-action-triage.git
cd github-action-triage

# Initialize issue tracking (required for development)
bd onboard

# Install Python dependencies
uv sync --group dev

# Install the project in editable mode (required for imports)
uv pip install -e .

# Verify setup by running tests
uv run pytest
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
export TRIAGE_GITHUB_APP_ID="123456"
export TRIAGE_GITHUB_PRIVATE_KEY="$(cat path/to/your-app.pem)"
export TRIAGE_GITHUB_WEBHOOK_SECRET="your-webhook-secret"
export TRIAGE_ANTHROPIC_API_KEY="sk-ant-..."
export TRIAGE_SOURCEGRAPH_TOKEN="sgp_..."
export TRIAGE_SOURCEGRAPH_MCP_URL="http://localhost:3000"
export TRIAGE_LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
export TRIAGE_DISABLE_ISSUE_CREATION="false"  # Set to "true" for testing without creating issues
```

**Notes**:

- `TRIAGE_GITHUB_PRIVATE_KEY` should contain the full PEM content (including `-----BEGIN RSA PRIVATE KEY-----` and `-----END RSA PRIVATE KEY-----` lines), not just a file path.
- `TRIAGE_GITHUB_WEBHOOK_SECRET` should be a secure random string. Generate one with:
- `TRIAGE_DISABLE_ISSUE_CREATION` when set to `"true"`, disables GitHub issue creation and instead logs the proposal. Useful for local testing and development to avoid cluttering repositories with test issues.

  ```bash
  # Generate a secure random secret
  openssl rand -hex 32

  # Or use Ruby
  ruby -rsecurerandom -e 'puts SecureRandom.hex(32)'

  # Or use Python
  python3 -c 'import secrets; print(secrets.token_hex(32))'
  ```

  Configure this same secret in your GitHub App webhook settings for signature verification.

## Deployment

### Container Deployment

The service is containerized using a multi-stage Docker build with a minimal Chainguard Python runtime.

#### Building the Container

```bash
# Build the container image
docker build -t github-action-triage:latest .

# Or with a specific tag
docker build -t ghcr.io/yourorg/github-action-triage:v1.0.0 .
```

#### Running the Container

```bash
# Run with environment variables
docker run -d \
  -p 8000:8000 \
  -e TRIAGE_GITHUB_APP_ID="123456" \
  -e TRIAGE_GITHUB_PRIVATE_KEY="$(cat path/to/your-app.pem)" \
  -e TRIAGE_GITHUB_WEBHOOK_SECRET="your-webhook-secret" \
  -e TRIAGE_ANTHROPIC_API_KEY="sk-ant-..." \
  -e TRIAGE_SOURCEGRAPH_TOKEN="sgp_..." \
  -e TRIAGE_SOURCEGRAPH_MCP_URL="http://localhost:3000" \
  -e TRIAGE_LOG_LEVEL="INFO" \
  --name github-action-triage \
  github-action-triage:latest
```

#### Using Environment File

Create a `.env` file with your configuration:

```bash
TRIAGE_GITHUB_APP_ID=123456
TRIAGE_GITHUB_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
TRIAGE_GITHUB_WEBHOOK_SECRET=your-webhook-secret
TRIAGE_ANTHROPIC_API_KEY=sk-ant-...
TRIAGE_SOURCEGRAPH_TOKEN=sgp_...
TRIAGE_SOURCEGRAPH_MCP_URL=http://localhost:3000
TRIAGE_LOG_LEVEL=INFO
```

Then run:

```bash
docker run -d -p 8000:8000 --env-file .env --name github-action-triage github-action-triage:latest
```

#### Docker Compose

Create a `docker-compose.yml` file:

```yaml
services:
  triage:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/github/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

Start the service:

```bash
docker compose up -d
```

#### Production Considerations

- **Secrets Management**: Use Docker secrets or a secrets manager (AWS Secrets Manager, HashiCorp Vault) instead of environment variables for sensitive data
- **Logging**: Container logs are sent to stdout/stderr; configure log aggregation (Datadog, CloudWatch, etc.)
- **Monitoring**: Expose `/github/health` endpoint for health checks and load balancer integration
- **Resource Limits**: Set memory and CPU limits in production:
  ```bash
  docker run -d -p 8000:8000 --memory="512m" --cpus="1.0" --env-file .env github-action-triage:latest
  ```
- **Security**: The container uses the minimal Chainguard Python image for reduced attack surface

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [GitHubKit Documentation](https://yanyongyu.github.io/githubkit/)
- [Claude Agent SDK Documentation](https://github.com/anthropics/anthropic-sdk-python)

## Contributing

1. Write tests first to specify behavior
2. Implement to satisfy tests
3. Ensure all tests pass: `uv run pytest`
4. Verify server boots: `uv run poe dev`
