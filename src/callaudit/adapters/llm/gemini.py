"""Google Gemini adapter for the `StructuredLanguageModel` port."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from callaudit.adapters.llm.rate_limit import MinIntervalRateLimiter
from callaudit.application.ports import (
    InvalidResponseError,
    LanguageModelError,
    QuotaExhaustedError,
)

logger = logging.getLogger(__name__)

# 429: quota or rate limit. 5xx: server side. Everything else (400 bad request,
# 401/403 bad key, 404 unknown model) will not improve by asking again.
TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

QUOTA_RESET_TIMEZONE = ZoneInfo("America/Los_Angeles")


class _AsyncModels(Protocol):
    """The slice of `genai.Client().aio.models` this adapter uses."""

    async def generate_content(
        self, *, model: str, contents: Any, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse: ...


@dataclass(frozen=True)
class RetryPolicy:
    """How transient failures are retried: attempts, per-call timeout and backoff."""

    max_attempts: int = 4
    timeout_seconds: float = 90
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 30.0
    # Upper bound for the wait Google suggests in a 429 ("retry in 44s").
    max_retry_after_seconds: float = 60.0
    # Injectable so tests run instantly and deterministically.
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    jitter: Callable[[], float] = random.random
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def backoff(self, attempt: int) -> float:
        """Exponential backoff with full jitter: uniform in [0, min(cap, base * 2^(n-1))]."""
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * 2.0 ** (attempt - 1))
        return ceiling * self.jitter()


def _quota_details(exc: errors.APIError) -> tuple[bool, float | None]:
    """Read Google's structured error details: (daily quota exhausted, suggested wait).

    A 429 carries a google.rpc.QuotaFailure whose quotaId names the exhausted
    quota (e.g. "GenerateRequestsPerDayPerProjectPerModel-FreeTier") and a
    google.rpc.RetryInfo with the suggested delay (e.g. "44.8s"). Anything
    missing or malformed yields (False, None): plain backoff, as before.
    """
    body = exc.details if isinstance(exc.details, dict) else {}
    error = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
    daily = False
    retry_after: float | None = None
    for item in error.get("details") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            daily = daily or any(
                "PerDay" in str(violation.get("quotaId", ""))
                for violation in item.get("violations") or []
                if isinstance(violation, dict)
            )
        elif kind.endswith("RetryInfo"):
            with suppress(ValueError):
                retry_after = float(str(item.get("retryDelay", "")).removesuffix("s"))
    return daily, retry_after


def next_quota_reset(now: datetime) -> datetime:
    """Free tier daily quotas reset at midnight Pacific time."""
    local = now.astimezone(QUOTA_RESET_TIMEZONE)
    return datetime.combine(local.date() + timedelta(days=1), time.min, QUOTA_RESET_TIMEZONE)


class GeminiLanguageModel:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        models: _AsyncModels | None = None,
        rate_limiter: MinIntervalRateLimiter | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        if models is None:
            if not api_key:
                raise ValueError("GEMINI_API_KEY is required for the Gemini adapter")
            models = genai.Client(api_key=api_key).aio.models
        self._models = models
        self._model = model
        self._rate_limiter = rate_limiter
        self._retry = retry or RetryPolicy()
        # Set when Google reports the daily quota exhausted: until then every
        # call fails fast, without sending requests that Google still counts.
        self._blocked_until: datetime | None = None

    @property
    def model_name(self) -> str:
        return self._model

    async def generate[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            # The full JSON Schema from Pydantic ($defs, enums, descriptions,
            # additionalProperties=false), not the SDK's reduced conversion:
            # the contract Gemini sees is the one Pydantic validates.
            response_json_schema=schema.model_json_schema(),
            # No temperature: Gemini 3 models are tuned for the default (1.0), and
            # Google warns that lower values can cause looping or degraded output.
            # Consistency comes from the schema and from code-issued verdicts.
        )
        text = await self._call_with_retries(user_prompt, config)
        return self._parse(text, schema)

    @staticmethod
    def _quota_error(until: datetime) -> QuotaExhaustedError:
        reset = until.astimezone(UTC)
        return QuotaExhaustedError(
            "cuota diaria de Gemini agotada; se renueva a la medianoche del Pacífico "
            f"({reset:%Y-%m-%d %H:%M} UTC)"
        )

    async def _call_with_retries(
        self, user_prompt: str, config: types.GenerateContentConfig
    ) -> str:
        if self._blocked_until is not None:
            if self._retry.clock() < self._blocked_until:
                raise self._quota_error(self._blocked_until)
            self._blocked_until = None
        for attempt in range(1, self._retry.max_attempts + 1):
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire()
            try:
                response = await asyncio.wait_for(
                    self._models.generate_content(
                        model=self._model, contents=user_prompt, config=config
                    ),
                    timeout=self._retry.timeout_seconds,
                )
            except errors.APIError as exc:
                daily, retry_after = _quota_details(exc) if exc.code == 429 else (False, None)
                if daily:
                    self._blocked_until = next_quota_reset(self._retry.clock())
                    logger.warning(
                        "gemini daily quota exhausted; blocked until %s", self._blocked_until
                    )
                    raise self._quota_error(self._blocked_until) from exc
                if exc.code not in TRANSIENT_STATUS_CODES or attempt == self._retry.max_attempts:
                    raise LanguageModelError(f"Gemini respondió {exc.code}: {exc.message}") from exc
                reason = f"HTTP {exc.code}"
                if retry_after is not None:
                    delay = min(retry_after, self._retry.max_retry_after_seconds)
                    logger.info("gemini asked to retry in %.1fs (attempt %d)", delay, attempt)
                    await self._retry.sleep(delay)
                    continue
            except (TimeoutError, httpx.TransportError) as exc:
                if attempt == self._retry.max_attempts:
                    raise LanguageModelError(f"Gemini no respondió: {exc!r}") from exc
                reason = type(exc).__name__
            else:
                if not response.text:
                    raise InvalidResponseError("Gemini devolvió una respuesta vacía")
                return response.text
            delay = self._retry.backoff(attempt)
            logger.info("gemini attempt %d failed (%s); retrying in %.1fs", attempt, reason, delay)
            await self._retry.sleep(delay)
        raise LanguageModelError("unreachable: retry loop exhausted")

    @staticmethod
    def _parse[T: BaseModel](text: str, schema: type[T]) -> T:
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            summary = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()[:5]
            )
            raise InvalidResponseError(summary or str(exc)) from exc
