from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisSettings(BaseSettings):
    """Configuration for TriageAgent analysis worker."""

    model_config = SettingsConfigDict(env_prefix="TRIAGE_ANALYSIS_", case_sensitive=False)

    model: str = Field(
        default="anthropic:claude-sonnet-4-5",
        description="Model for analysis in pydantic-ai format. Examples: 'anthropic:claude-sonnet-4-5', 'ollama:qwen2.5:latest'",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="Base URL for Ollama server (only used when model starts with 'ollama:')",
    )
    timeout_seconds: int = Field(
        default=300,
        description="Timeout for analysis in seconds",
    )


def get_analysis_settings() -> AnalysisSettings:
    return AnalysisSettings()