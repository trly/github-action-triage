import logging
from fastapi import FastAPI
from githubkit import GitHub, AppAuthStrategy
from github_action_triage.app.web.api import router as github_router
from github_action_triage.app.api import TriageService
from github_action_triage.app.infra.github_client import GitHubContextAdapter
from github_action_triage.app.infra.github_issue_creator import GitHubIssueCreatorAdapter
from github_action_triage.agent.ai_agent import ActionTriageAgent
from github_action_triage.app.config.settings import Settings, get_settings


def create_github_client(settings: Settings) -> GitHub:
    """Create and configure a GitHubKit client."""
    logger = logging.getLogger(__name__)
    logger.debug("Creating GitHub client...")
    auth = AppAuthStrategy(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )
    client = GitHub(auth=auth)
    logger.debug("GitHub client created")
    return client


def create_triage_service(settings: Settings) -> TriageService:
    """Factory for creating a fully wired TriageService."""
    github_client = create_github_client(settings)
    context_provider = GitHubContextAdapter(settings, github_client)
    agent = ActionTriageAgent(settings)
    issue_creator = GitHubIssueCreatorAdapter(settings)
    
    return TriageService(
        context_provider=context_provider,
        agent=agent,
        issue_creator=issue_creator,
    )


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GitHub Action Triage",
        description="Automated CI/CD failure analysis and remediation",
        version="0.1.0",
    )

    # Wire dependencies
    app.state.settings = settings
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
