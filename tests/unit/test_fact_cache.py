"""The fact cache: identical conversations reuse the extraction, anything else calls the model."""

import pytest

from callaudit.adapters.facts.replay import ReplayFactSource
from callaudit.adapters.persistence.null import NullAuditRepository
from callaudit.application.agent_spec import LINA_AGENT_SPEC
from callaudit.application.audit_service import AuditService
from callaudit.application.fact_cache import CachedFactSource, fact_cache_key
from callaudit.application.fact_extraction import FactExtractor
from callaudit.domain.audit import AnalysisStatus, FactsOrigin
from callaudit.domain.conversation import Conversation, Dataset, Turn
from callaudit.domain.facts import ConversationFacts
from tests.conftest import FIXTURES
from tests.fakes import (
    BrokenFactCache,
    GoldenLanguageModel,
    InMemoryFactCache,
    ScriptedLanguageModel,
)

MODEL = "gemini-test"


def _with_turn_text(conversation: Conversation, index: int, text: str) -> Conversation:
    turns = list(conversation.transcript)
    turns[index] = Turn(speaker=turns[index].speaker, text=text)
    return conversation.model_copy(update={"transcript": tuple(turns)})


class TestKey:
    def test_is_a_sha256_hex_digest(self, conversations: dict[str, Conversation]) -> None:
        key = fact_cache_key(conversations["C01"], LINA_AGENT_SPEC, MODEL)
        assert len(key) == 64
        assert set(key) <= set("0123456789abcdef")

    def test_ignores_the_conversation_id(self, conversations: dict[str, Conversation]) -> None:
        original = conversations["C01"]
        renamed = original.model_copy(update={"id": "OTRA-ID"})
        assert fact_cache_key(renamed, LINA_AGENT_SPEC, MODEL) == fact_cache_key(
            original, LINA_AGENT_SPEC, MODEL
        )

    def test_same_id_with_other_content_is_another_key(
        self, conversations: dict[str, Conversation]
    ) -> None:
        # An evaluator could reuse "C01" for a different call.
        impostor = conversations["C02"].model_copy(update={"id": "C01"})
        assert fact_cache_key(impostor, LINA_AGENT_SPEC, MODEL) != fact_cache_key(
            conversations["C01"], LINA_AGENT_SPEC, MODEL
        )

    @pytest.mark.parametrize(
        "change",
        [
            "one_character_in_a_turn",
            "customer_amount",
            "customer_digits",
            "call_date",
            "spec",
            "model",
        ],
    )
    def test_any_change_produces_another_key(
        self, conversations: dict[str, Conversation], change: str
    ) -> None:
        base = conversations["C01"]
        conversation, spec, model = base, LINA_AGENT_SPEC, MODEL
        if change == "one_character_in_a_turn":
            conversation = _with_turn_text(base, 5, base.transcript[5].text + ".")
        elif change == "customer_amount":
            customer = base.customer.model_copy(update={"overdue_amount_cop": 1_250_001})
            conversation = base.model_copy(update={"customer": customer})
        elif change == "customer_digits":
            customer = base.customer.model_copy(update={"document_last4": "0000"})
            conversation = base.model_copy(update={"customer": customer})
        elif change == "call_date":
            conversation = base.model_copy(update={"call_date": base.call_date.replace(day=23)})
        elif change == "spec":
            spec = LINA_AGENT_SPEC.model_copy(update={"agent_name": "Otra"})
        else:
            model = "otro-modelo"

        assert fact_cache_key(conversation, spec, model) != fact_cache_key(
            base, LINA_AGENT_SPEC, MODEL
        )


class TestCachedFactSource:
    async def test_first_call_uses_the_model_and_stores_the_facts(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        cache = InMemoryFactCache()
        source = CachedFactSource(
            FactExtractor(ScriptedLanguageModel([golden_facts["C01"]])), cache
        )

        extraction = await source.obtain(conversations["C01"], LINA_AGENT_SPEC)

        assert extraction.origin is FactsOrigin.MODEL
        assert extraction.facts == golden_facts["C01"]
        assert cache.puts == 1

    async def test_an_identical_conversation_is_served_from_cache_without_a_model_call(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        llm = ScriptedLanguageModel([golden_facts["C01"]])  # a second call would fail
        source = CachedFactSource(FactExtractor(llm), InMemoryFactCache())

        await source.obtain(conversations["C01"], LINA_AGENT_SPEC)
        again = await source.obtain(
            conversations["C01"].model_copy(update={"id": "RENOMBRADA"}), LINA_AGENT_SPEC
        )

        assert again.origin is FactsOrigin.CACHE
        assert again.facts == golden_facts["C01"]
        assert len(llm.calls) == 1

    async def test_a_different_conversation_calls_the_model(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        llm = GoldenLanguageModel(conversations, golden_facts)
        source = CachedFactSource(FactExtractor(llm), InMemoryFactCache())

        await source.obtain(conversations["C01"], LINA_AGENT_SPEC)
        second = await source.obtain(conversations["C02"], LINA_AGENT_SPEC)

        assert second.origin is FactsOrigin.MODEL
        assert llm.seen == ["C01", "C02"]

    async def test_an_edited_conversation_calls_the_model(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        edited = _with_turn_text(
            conversations["C01"], 4, conversations["C01"].transcript[4].text.replace("15", "16")
        )
        llm = ScriptedLanguageModel([golden_facts["C01"], golden_facts["C01"]])
        source = CachedFactSource(FactExtractor(llm), InMemoryFactCache())

        await source.obtain(conversations["C01"], LINA_AGENT_SPEC)
        result = await source.obtain(edited, LINA_AGENT_SPEC)

        assert result.origin is FactsOrigin.MODEL
        assert len(llm.calls) == 2

    async def test_a_broken_cache_falls_back_to_the_model(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        source = CachedFactSource(
            FactExtractor(ScriptedLanguageModel([golden_facts["C01"]])), BrokenFactCache()
        )

        extraction = await source.obtain(conversations["C01"], LINA_AGENT_SPEC)

        assert extraction.origin is FactsOrigin.MODEL

    async def test_cached_facts_that_do_not_fit_are_ignored(
        self, conversations: dict[str, Conversation], golden_facts: dict[str, ConversationFacts]
    ) -> None:
        cache = InMemoryFactCache()
        key = fact_cache_key(conversations["C01"], LINA_AGENT_SPEC, "scripted-fake")
        cache.entries[key] = golden_facts["C01"].model_copy(update={"debt_disclosure_turn": 99})
        llm = ScriptedLanguageModel([golden_facts["C01"]])
        source = CachedFactSource(FactExtractor(llm), cache)

        extraction = await source.obtain(conversations["C01"], LINA_AGENT_SPEC)

        assert extraction.origin is FactsOrigin.MODEL
        assert len(llm.calls) == 1

    async def test_model_failures_are_not_cached(
        self, conversations: dict[str, Conversation]
    ) -> None:
        cache = InMemoryFactCache()
        source = CachedFactSource(
            FactExtractor(ScriptedLanguageModel([RuntimeError("quota")])), cache
        )

        with pytest.raises(RuntimeError):
            await source.obtain(conversations["C01"], LINA_AGENT_SPEC)
        assert cache.entries == {}

    async def test_replayed_facts_are_not_cached(
        self, conversations: dict[str, Conversation]
    ) -> None:
        cache = InMemoryFactCache()
        source = CachedFactSource(ReplayFactSource(FIXTURES / "golden_facts.json"), cache)

        extraction = await source.obtain(conversations["C01"], LINA_AGENT_SPEC)

        assert extraction.origin is FactsOrigin.REPLAY
        assert cache.puts == 0


class TestServiceWithCache:
    async def test_second_run_is_served_from_cache_and_says_so(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        llm = GoldenLanguageModel(conversations, golden_facts)
        cache = InMemoryFactCache()
        service = AuditService(CachedFactSource(FactExtractor(llm), cache), NullAuditRepository())

        first = await service.audit_dataset(dataset)
        second = await service.audit_dataset(dataset)

        assert len(llm.seen) == 20  # only the first run called the model
        assert first.facts_origin_distribution == {"modelo": 20}
        assert second.facts_origin_distribution == {"cache": 20}
        assert [a.failed_criteria for a in second.audits] == [
            a.failed_criteria for a in first.audits
        ]

    async def test_a_partial_run_is_completed_later_with_only_the_missing_calls(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        # Day 1: quota runs out for C19 and C20. Day 2: only those two call the model.
        cache = InMemoryFactCache()
        day_one = GoldenLanguageModel(
            conversations, golden_facts, failing=frozenset({"C19", "C20"})
        )
        first = await AuditService(
            CachedFactSource(FactExtractor(day_one), cache), NullAuditRepository()
        ).audit_dataset(dataset)
        day_two = GoldenLanguageModel(conversations, golden_facts)
        second = await AuditService(
            CachedFactSource(FactExtractor(day_two), cache), NullAuditRepository()
        ).audit_dataset(dataset)

        assert first.facts_origin_distribution == {"modelo": 18, "sin_analisis": 2}
        assert sorted(day_two.seen) == ["C19", "C20"]
        assert second.facts_origin_distribution == {"cache": 18, "modelo": 2}
        assert all(a.analysis is AnalysisStatus.COMPLETE for a in second.audits)
