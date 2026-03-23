from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Shared configuration for github-action-triage."""

    model_config = SettingsConfigDict(env_prefix="TRIAGE_", case_sensitive=False)

    github_app_id: str = Field(default="", description="GitHub App ID")
    github_private_key: str = Field(default="", description="GitHub App private key")
    github_webhook_secret: str = Field(default="", description="GitHub webhook secret")
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), description="Anthropic API key for AI agents"
    )
    sourcegraph_url: str = Field(
        default="", description="Sourcegraph instance URL for Deep Search"
    )
    sourcegraph_token: SecretStr = Field(
        default=SecretStr(""), description="Sourcegraph API token"
    )

    log_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL for Celery broker and result backend",
    )
    disable_issue_creation: bool = Field(
        default=False,
        description="Disable GitHub issue creation (log instead) for testing",
    )
    github_token: SecretStr = Field(
        default=SecretStr(""), description="GitHub personal access token for API access"
    )

    # Analysis settings
    analysis_model: str = Field(
        default="anthropic:claude-sonnet-4-5",
        description="Model identifier for TriageAgent analysis",
    )
    analysis_timeout_seconds: int = Field(
        default=300,
        description="Timeout in seconds for TriageAgent analysis",
    )

    # Deep Search polling settings
    deepsearch_poll_interval_seconds: float = Field(
        default=3.0,
        description="Interval in seconds between Deep Search poll requests",
    )


def get_settings() -> Settings:
    return Settings()
