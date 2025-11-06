import logging
from fastapi import FastAPI
from githubkit import GitHub
from github_action_triage.app.web.api import router as github_router
from github_action_triage.app.api import TriageService
from github_action_triage.app.infra.github_client import (
    GitHubContextAdapter,
    GitHubRepositoryActuator,
)
from github_action_triage.agent.ai_agent import PydanticAIRemediationAgent
from github_action_triage.app.config.settings import Settings, get_settings


def create_github_client(settings: Settings) -> GitHub:
    """Create and configure a GitHubKit client."""
    # For now, create an unauthenticated client
    # TODO: Implement GitHub App authentication
    return GitHub()


def create_triage_service(settings: Settings) -> TriageService:
    """Factory for creating a fully wired TriageService."""
    github_client = create_github_client(settings)
    context_provider = GitHubContextAdapter(settings, github_client)
    agent = PydanticAIRemediationAgent(settings)
    actuator = GitHubRepositoryActuator(settings)
    
    return TriageService(
        context_provider=context_provider,
        agent=agent,
        actuator=actuator,
    )


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:     %(name)s - %(message)s",
    )
    
    app = FastAPI(
        title="GitHub Action Triage",
        description="Automated CI/CD failure analysis and remediation",
        version="0.1.0",
    )

    # Wire dependencies
    settings = get_settings()
    app.state.triage_service = create_triage_service(settings)

    app.include_router(github_router)

    @app.get("/")
    async def root():
        return {
            "message": "GitHub Action Triage API",
            "version": "0.1.0",
            "docs_url": "/docs",
        }

    return app
