"""Composition root: the only place that knows which adapter backs each port."""

import logging

from callaudit.adapters.llm.disabled import DisabledLanguageModel
from callaudit.adapters.llm.gemini import GeminiLanguageModel, RetryPolicy
from callaudit.adapters.llm.rate_limit import MinIntervalRateLimiter
from callaudit.application.audit_service import AuditService
from callaudit.application.fact_extraction import FactExtractor
from callaudit.application.ports import StructuredLanguageModel
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


def build_audit_service(settings: Settings) -> AuditService:
    llm = build_language_model(settings)
    return AuditService(
        FactExtractor(llm, max_attempts=settings.extraction_max_attempts),
        model_name=llm.model_name,
        max_concurrency=settings.llm_max_concurrency,
    )
