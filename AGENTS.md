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

