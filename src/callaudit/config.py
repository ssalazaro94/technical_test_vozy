"""Runtime configuration, read from environment variables (and `.env` locally)."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "replay" is for local development only: it replays annotated facts from
    # REPLAY_FACTS_PATH instead of calling a model.
    llm_provider: Literal["gemini", "none", "replay"] = "gemini"
    llm_model: str = "gemini-3.8-flash"
    gemini_api_key: SecretStr | None = None

    # Free tier guard rails: requests in flight, requests per minute and
    # attempts per request (transient errors only).
    # Defaults fit the free tier of gemini-3.8-flash (5 requests per minute).
    llm_max_concurrency: int = Field(default=2, ge=1)
    llm_requests_per_minute: float = Field(default=4, gt=0)
    llm_max_attempts: int = Field(default=4, ge=1)
    llm_timeout_seconds: float = Field(default=90, gt=0)

    # Attempts to get facts that are consistent with the transcript.
    extraction_max_attempts: int = Field(default=2, ge=1)

    replay_facts_path: Path | None = None

    # Postgres (Supabase pooler in production). Unset: audits are not stored.
    database_url: SecretStr | None = None
    database_timeout_seconds: float = Field(default=10, gt=0)

    # Spending guards for a public API with a paid model. The daily budget is the
    # hard cap on model calls (UTC day, counted in the database); unset = no cap.
    # The per-client limit applies to the audit routes; unset = no limit.
    llm_daily_call_budget: int | None = Field(default=None, ge=0)
    client_requests_per_hour: int | None = Field(default=30, ge=1)

    # Reuse the model's extraction of an identical conversation (needs a
    # database). Any change to the conversation, rules, prompt or model misses.
    facts_cache_enabled: bool = True

    # Local tooling only (tests and scripts): path to the client's dataset,
    # which is provided privately and is never versioned.
    local_dataset_path: Path | None = None
