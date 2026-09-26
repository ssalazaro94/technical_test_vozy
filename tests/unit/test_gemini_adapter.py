"""The Gemini adapter, exercised against a fake SDK client: no network, no key."""

from typing import Any

import httpx
import pytest
from google.genai import errors, types

from callaudit.adapters.llm.gemini import GeminiLanguageModel, RetryPolicy
from callaudit.adapters.llm.rate_limit import MinIntervalRateLimiter
from callaudit.application.ports import InvalidResponseError, LanguageModelError
from callaudit.domain.facts import ConversationFacts

VALID_JSON = '{"interlocutor": "titular", "debt_disclosure_turn": 4, "outcome": "compromiso_pago"}'


def _response(text: str | None) -> types.GenerateContentResponse:
    parts = [types.Part(text=text)] if text is not None else []
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))]
    )


def _api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": f"status {code}"}})


class FakeModels:
    """Stands in for `genai.Client().aio.models`; replays a script of outcomes."""

    def __init__(self, *outcomes: types.GenerateContentResponse | Exception) -> None:
        self._outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []

    async def generate_content(
        self, *, model: str, contents: Any, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        self.requests.append({"model": model, "contents": contents, "config": config})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _adapter(models: FakeModels, sleep: RecordingSleep, attempts: int = 4) -> GeminiLanguageModel:
    return GeminiLanguageModel(
        model="gemini-test",
        models=models,
        retry=RetryPolicy(max_attempts=attempts, sleep=sleep, jitter=lambda: 1.0),
    )


async def _generate(adapter: GeminiLanguageModel) -> ConversationFacts:
    return await adapter.generate(system_prompt="sys", user_prompt="usr", schema=ConversationFacts)


async def test_parses_structured_json_and_sends_the_schema() -> None:
    models = FakeModels(_response(VALID_JSON))

    facts = await _generate(_adapter(models, RecordingSleep()))

    assert facts.debt_disclosure_turn == 4
    request = models.requests[0]
    assert request["model"] == "gemini-test"
    assert request["contents"] == "usr"
    config: types.GenerateContentConfig = request["config"]
    assert config.system_instruction == "sys"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == ConversationFacts.model_json_schema()
    assert config.temperature == 0.0


@pytest.mark.parametrize("code", [429, 500, 503])
async def test_retries_transient_http_errors_with_exponential_backoff(code: int) -> None:
    models = FakeModels(_api_error(code), _api_error(code), _response(VALID_JSON))
    sleep = RecordingSleep()

    await _generate(_adapter(models, sleep))

    assert len(models.requests) == 3
    assert sleep.delays == [2.0, 4.0]


async def test_retries_timeouts_and_network_errors() -> None:
    models = FakeModels(TimeoutError(), httpx.ConnectError("down"), _response(VALID_JSON))

    await _generate(_adapter(models, RecordingSleep()))

    assert len(models.requests) == 3


@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_does_not_retry_permanent_errors(code: int) -> None:
    models = FakeModels(_api_error(code))

    with pytest.raises(LanguageModelError, match=f"Gemini respondió {code}"):
        await _generate(_adapter(models, RecordingSleep()))
    assert len(models.requests) == 1


async def test_gives_up_after_max_attempts() -> None:
    models = FakeModels(_api_error(429), _api_error(429), _api_error(429))
    sleep = RecordingSleep()

    with pytest.raises(LanguageModelError, match="429"):
        await _generate(_adapter(models, sleep, attempts=3))
    assert len(sleep.delays) == 2


async def test_backoff_is_capped() -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=30, jitter=lambda: 1.0)
    assert [policy.backoff(n) for n in range(1, 7)] == [2, 4, 8, 16, 30, 30]


async def test_invalid_json_is_reported_as_invalid_response() -> None:
    models = FakeModels(_response('{"interlocutor": "jefe", "outcome": "compromiso_pago"}'))

    with pytest.raises(InvalidResponseError, match="interlocutor"):
        await _generate(_adapter(models, RecordingSleep()))


async def test_empty_answer_is_reported_as_invalid_response() -> None:
    models = FakeModels(_response(None))

    with pytest.raises(InvalidResponseError, match="vacía"):
        await _generate(_adapter(models, RecordingSleep()))


def test_requires_an_api_key_when_no_client_is_injected() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiLanguageModel(model="gemini-test", api_key="")


class TestRateLimiter:
    async def test_spaces_requests_evenly(self) -> None:
        now = [100.0]
        sleep = RecordingSleep()

        async def advancing_sleep(seconds: float) -> None:
            await sleep(seconds)
            now[0] += seconds

        limiter = MinIntervalRateLimiter(10, clock=lambda: now[0], sleep=advancing_sleep)
        for _ in range(3):
            await limiter.acquire()

        # 10 per minute: one every 6 seconds, the first one immediately.
        assert sleep.delays == [6.0, 6.0]

    async def test_does_not_wait_when_calls_are_already_spaced(self) -> None:
        now = [0.0]
        sleep = RecordingSleep()
        limiter = MinIntervalRateLimiter(60, clock=lambda: now[0], sleep=sleep)

        await limiter.acquire()
        now[0] = 5.0
        await limiter.acquire()

        assert sleep.delays == []
