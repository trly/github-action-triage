from github_action_triage.app.api import TriageService
from github_action_triage.app.config.settings import Settings
from github_action_triage.app.factory import (
    create_app,
    create_github_client,
    create_triage_service,
)


def test_create_github_client():
    settings = Settings()
    client = create_github_client(settings)
    assert client is not None


def test_create_triage_service():
    settings = Settings()
    service = create_triage_service(settings)
    
    assert isinstance(service, TriageService)
    assert service._context_provider is not None
    assert service._agent is not None
    assert service._issue_creator is not None


def test_create_app_wires_triage_service():
    app = create_app()
    
    assert hasattr(app.state, "triage_service")
    assert isinstance(app.state.triage_service, TriageService)
