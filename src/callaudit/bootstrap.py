"""Composition root: the only place that knows which adapter backs each port."""

import logging

from callaudit.adapters.facts.replay import ReplayFactSource
from callaudit.adapters.llm.disabled import DisabledLanguageModel
from callaudit.adapters.llm.gemini import GeminiLanguageModel, RetryPolicy
from callaudit.adapters.llm.rate_limit import MinIntervalRateLimiter
from callaudit.adapters.persistence.null import NullAuditRepository
from callaudit.adapters.persistence.postgres import PostgresAuditRepository
from callaudit.application.audit_service import AuditService
from callaudit.application.fact_extraction import FactExtractor
from callaudit.application.ports import AuditRepository, FactSource, StructuredLanguageModel
from callaudit.config import Settings

logger = logging.getLogger(__name__)


def build_language_model(settings: Settings) -> StructuredLanguageModel:
    if settings.llm_provider == "none":
        return DisabledLanguageModel("LLM_PROVIDER=none")
    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    if not api_key:
        # Degrade instead of refusing to start: the service still audits with
        # the code criteria, and every audit says why it is partial.
        logger.warning("GEMINI_API_KEY is not set; running without a language model")
        return DisabledLanguageModel("falta GEMINI_API_KEY")
    return GeminiLanguageModel(
        model=settings.llm_model,
        api_key=api_key,
        rate_limiter=MinIntervalRateLimiter(settings.llm_requests_per_minute),
        retry=RetryPolicy(
            max_attempts=settings.llm_max_attempts,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
    )


def build_fact_source(settings: Settings) -> FactSource:
    if settings.llm_provider == "replay":
        if settings.replay_facts_path is None:
            raise ValueError("LLM_PROVIDER=replay requires REPLAY_FACTS_PATH")
        logger.warning(
            "replaying annotated facts from %s: development only", settings.replay_facts_path
        )
        return ReplayFactSource(settings.replay_facts_path)
    return FactExtractor(
        build_language_model(settings), max_attempts=settings.extraction_max_attempts
    )


def build_repository(settings: Settings) -> AuditRepository:
    if settings.database_url is None:
        logger.warning("DATABASE_URL is not set; audits will not be stored")
        return NullAuditRepository()
    return PostgresAuditRepository.from_url(
        settings.database_url.get_secret_value(),
        timeout_seconds=settings.database_timeout_seconds,
    )


def build_audit_service(settings: Settings) -> AuditService:
    return AuditService(
        build_fact_source(settings),
        build_repository(settings),
        max_concurrency=settings.llm_max_concurrency,
    )
