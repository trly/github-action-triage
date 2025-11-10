from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRIAGE_", case_sensitive=False)

    github_app_id: str = Field(default="", description="GitHub App ID")
    github_private_key: str = Field(default="", description="GitHub App private key")
    github_webhook_secret: str = Field(default="", description="GitHub webhook secret")
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), description="Anthropic API key for Claude Agent SDK"
    )
    sourcegraph_mcp_url: str = Field(
        default="", description="Sourcegraph MCP server URL (optional)"
    )
    sourcegraph_token: SecretStr = Field(
        default=SecretStr(""), description="Sourcegraph API token (optional)"
    )

    claude_model: str = Field(
        default="claude-sonnet-4-20250514", description="Claude model to use for failure analysis"
    )
    claude_max_turns: int = Field(
        default=6, description="Maximum conversation turns for Claude agent"
    )
    analysis_timeout_seconds: int = Field(
        default=300, description="Timeout for failure analysis in seconds"
    )
    log_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )


def get_settings() -> Settings:
    return Settings()
