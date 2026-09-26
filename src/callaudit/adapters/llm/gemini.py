"""Google Gemini adapter for the `StructuredLanguageModel` port."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from callaudit.adapters.llm.rate_limit import MinIntervalRateLimiter
from callaudit.application.ports import InvalidResponseError, LanguageModelError

logger = logging.getLogger(__name__)

# 429: quota or rate limit. 5xx: server side. Everything else (400 bad request,
# 401/403 bad key, 404 unknown model) will not improve by asking again.
TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


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
    # Injectable so tests run instantly and deterministically.
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    jitter: Callable[[], float] = random.random

    def backoff(self, attempt: int) -> float:
        """Exponential backoff with full jitter: uniform in [0, min(cap, base * 2^(n-1))]."""
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * 2.0 ** (attempt - 1))
        return ceiling * self.jitter()


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
            temperature=0.0,
        )
        text = await self._call_with_retries(user_prompt, config)
        return self._parse(text, schema)

    async def _call_with_retries(
        self, user_prompt: str, config: types.GenerateContentConfig
    ) -> str:
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
                if exc.code not in TRANSIENT_STATUS_CODES or attempt == self._retry.max_attempts:
                    raise LanguageModelError(f"Gemini respondió {exc.code}: {exc.message}") from exc
                reason = f"HTTP {exc.code}"
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
