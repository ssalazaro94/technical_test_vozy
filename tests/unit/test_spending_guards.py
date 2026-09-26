"""Spending guards: the daily model-call budget and the per-client request limit."""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from callaudit.adapters.http.app import create_app
from callaudit.adapters.http.client_limits import ClientRateLimiter
from callaudit.adapters.http.examples import SYNTHETIC_CONVERSATION
from callaudit.adapters.persistence.null import InMemoryUsageCounter, NullAuditRepository
from callaudit.application.audit_service import AuditService
from callaudit.application.budget import DailyCallBudget
from callaudit.application.fact_cache import CachedFactSource
from callaudit.application.fact_extraction import FactExtractor
from callaudit.application.ports import QuotaExhaustedError
from callaudit.bootstrap import build_fact_source
from callaudit.config import Settings
from callaudit.domain.audit import AnalysisStatus
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.facts import ConversationFacts
from tests.fakes import (
    BrokenUsageCounter,
    GoldenLanguageModel,
    InMemoryFactCache,
    ScriptedLanguageModel,
)


class _Day:
    def __init__(self, day: date) -> None:
        self.day = day

    def __call__(self) -> date:
        return self.day


class TestDailyCallBudget:
    async def test_calls_up_to_the_limit_then_stops(
        self, golden_facts: dict[str, ConversationFacts]
    ) -> None:
        llm = ScriptedLanguageModel([golden_facts["C01"], golden_facts["C01"]])
        budget = DailyCallBudget(llm, InMemoryUsageCounter(), daily_limit=2)

        for _ in range(2):
            await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)
        with pytest.raises(QuotaExhaustedError, match="presupuesto diario del servicio agotado"):
            await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)

        assert len(llm.calls) == 2  # the third call never reached the model

    async def test_the_budget_renews_the_next_day(
        self, golden_facts: dict[str, ConversationFacts]
    ) -> None:
        today = _Day(date(2026, 9, 26))
        llm = ScriptedLanguageModel([golden_facts["C01"], golden_facts["C01"]])
        budget = DailyCallBudget(llm, InMemoryUsageCounter(), daily_limit=1, today=today)

        await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)
        with pytest.raises(QuotaExhaustedError):
            await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)
        today.day = date(2026, 9, 27)
        await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)

        assert len(llm.calls) == 2

    async def test_fails_closed_when_the_counter_is_unavailable(self) -> None:
        llm = ScriptedLanguageModel([])
        budget = DailyCallBudget(llm, BrokenUsageCounter(), daily_limit=100)

        with pytest.raises(QuotaExhaustedError, match="por seguridad no se llamó al modelo"):
            await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)
        assert llm.calls == []

    async def test_a_zero_budget_never_calls_the_model(self) -> None:
        llm = ScriptedLanguageModel([])
        budget = DailyCallBudget(llm, InMemoryUsageCounter(), daily_limit=0)

        with pytest.raises(QuotaExhaustedError):
            await budget.generate(system_prompt="s", user_prompt="u", schema=ConversationFacts)
        assert llm.calls == []

    async def test_over_budget_conversations_degrade_and_cached_ones_cost_nothing(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        llm = GoldenLanguageModel(conversations, golden_facts)
        cache = InMemoryFactCache()
        budget = DailyCallBudget(llm, InMemoryUsageCounter(), daily_limit=5)
        service = AuditService(
            CachedFactSource(FactExtractor(budget), cache),
            NullAuditRepository(),
            max_concurrency=1,
        )

        first = await service.audit_dataset(dataset)
        second = await service.audit_dataset(dataset)

        assert len(llm.seen) == 5  # the budget capped the model calls at 5
        assert first.facts_origin_distribution == {"modelo": 5, "sin_analisis": 15}
        partial = next(a for a in first.audits if a.analysis is AnalysisStatus.PARTIAL)
        assert "presupuesto diario del servicio agotado" in partial.warnings[0]
        # The five analysed conversations come back from the cache, over budget or not.
        assert second.facts_origin_distribution["cache"] == 5
        assert len(llm.seen) == 5


class TestClientRateLimiter:
    def test_allows_up_to_the_limit_then_asks_to_wait(self) -> None:
        now = [0.0]
        limiter = ClientRateLimiter(2, window_seconds=3600, clock=lambda: now[0])

        assert limiter.check("1.1.1.1") is None
        assert limiter.check("1.1.1.1") is None
        now[0] = 600
        assert limiter.check("1.1.1.1") == 3000  # the oldest request leaves in 50 minutes
        assert limiter.check("2.2.2.2") is None  # another client is independent

    def test_the_window_slides(self) -> None:
        now = [0.0]
        limiter = ClientRateLimiter(1, window_seconds=60, clock=lambda: now[0])

        assert limiter.check("c") is None
        assert limiter.check("c") is not None
        now[0] = 61
        assert limiter.check("c") is None


class TestClientLimitOverHttp:
    @pytest.fixture
    def app(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> FastAPI:
        llm = GoldenLanguageModel(conversations, golden_facts)
        return create_app(
            AuditService(FactExtractor(llm), NullAuditRepository()),
            client_limiter=ClientRateLimiter(2),
        )

    async def test_third_audit_request_gets_429_with_retry_after(self, app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=app)
        payload = {"conversacion": SYNTHETIC_CONVERSATION}
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            codes = [(await client.post("/v1/audits", json=payload)).status_code for _ in range(2)]
            blocked = await client.post("/v1/audits", json=payload)
            health = await client.get("/health")

        assert codes == [200, 200]
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "demasiadas_solicitudes"
        assert int(blocked.headers["retry-after"]) > 0
        assert health.status_code == 200  # reads are not limited

    async def test_production_app_builds_the_limiter_from_settings(self) -> None:
        app = create_app(
            settings=Settings(_env_file=None, llm_provider="none", client_requests_per_hour=5)
        )
        assert isinstance(app.state.client_limiter, ClientRateLimiter)


def test_bootstrap_wraps_the_model_with_the_budget() -> None:
    source = build_fact_source(
        Settings(_env_file=None, gemini_api_key=SecretStr("k"), llm_daily_call_budget=50)
    )
    assert isinstance(source, FactExtractor)
    assert isinstance(source._llm, DailyCallBudget)
    assert source.name == "gemini-3.8-flash"
