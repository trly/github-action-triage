from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRIAGE_", case_sensitive=False)

    github_app_id: str = Field(default="", description="GitHub App ID")
    github_private_key: str = Field(
        default="", description="GitHub App private key")
    github_webhook_secret: str = Field(
        default="", description="GitHub webhook secret")
    openai_api_key: str = Field(
        default="", description="OpenAI API key for PydanticAI")


def get_settings() -> Settings:
    return Settings()
