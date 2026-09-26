"""Runtime configuration, read from environment variables (and `.env` locally)."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["gemini", "none"] = "gemini"
    llm_model: str = "gemini-2.5-flash"
    gemini_api_key: SecretStr | None = None

    # Free tier guard rails: requests in flight, requests per minute and
    # attempts per request (transient errors only).
    llm_max_concurrency: int = Field(default=4, ge=1)
    llm_requests_per_minute: float = Field(default=10, gt=0)
    llm_max_attempts: int = Field(default=4, ge=1)
    llm_timeout_seconds: float = Field(default=90, gt=0)

    # Attempts to get facts that are consistent with the transcript.
    extraction_max_attempts: int = Field(default=2, ge=1)

    database_url: SecretStr | None = None

    # Local tooling only (tests and scripts): path to the client's dataset,
    # which is provided privately and is never versioned.
    local_dataset_path: Path | None = None
