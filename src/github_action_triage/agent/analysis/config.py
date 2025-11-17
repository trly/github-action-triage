from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalysisSettings(BaseSettings):
    """Configuration for TriageAgent analysis worker."""

    model_config = SettingsConfigDict(env_prefix="TRIAGE_ANALYSIS_", case_sensitive=False)

    model: str = Field(
        default="anthropic:claude-sonnet-4-5",
        description="Anthropic model for analysis (pydantic-ai format)",
    )
    timeout_seconds: int = Field(
        default=300,
        description="Timeout for analysis in seconds",
    )


def get_analysis_settings() -> AnalysisSettings:
    return AnalysisSettings()
