import pytest

from callaudit.application.fact_extraction import FactExtractionError, FactExtractor
from callaudit.application.ports import InvalidResponseError, LanguageModelError
from callaudit.application.prompts import build_system_prompt, build_user_prompt
from callaudit.domain.conversation import Conversation, Dataset
from callaudit.domain.facts import ConversationFacts, Interlocutor, Outcome
from tests.fakes import ScriptedLanguageModel

SHIFTED = ConversationFacts(
    interlocutor=Interlocutor.HOLDER,
    debt_disclosure_turn=5,  # a client turn in C01: the model is off by one
    outcome=Outcome.PAYMENT_COMMITMENT,
)


class TestPrompts:
    def test_user_prompt_numbers_every_turn_and_includes_the_record(
        self, conversations: dict[str, Conversation]
    ) -> None:
        prompt = build_user_prompt(conversations["C01"])

        assert "[0] agente: Buenos días, le habla Lina" in prompt
        assert "[3] cliente: 4821." in prompt
        assert "Monto vencido: $1.250.000" in prompt
        assert "Fecha de la llamada\n2026-09-22" in prompt

    def test_system_turns_are_labelled_as_system(
        self, conversations: dict[str, Conversation]
    ) -> None:
        assert "[10] sistema: [El cliente finalizó la llamada]" in build_user_prompt(
            conversations["C07"]
        )

    def test_system_prompt_carries_the_agent_rules(self, dataset: Dataset) -> None:
        prompt = build_system_prompt(dataset.agent_spec)

        assert "- R10. Mantener un tono respetuoso" in prompt
        assert "Nombre: Lina" in prompt

    def test_feedback_is_appended_only_when_present(
        self, conversations: dict[str, Conversation]
    ) -> None:
        assert "Corrige" not in build_user_prompt(conversations["C01"])
        prompt = build_user_prompt(conversations["C01"], ["debt_disclosure_turn=5: ..."])
        assert "Corrige tu respuesta anterior" in prompt
        assert "- debt_disclosure_turn=5: ..." in prompt


class TestFactExtractor:
    async def test_returns_consistent_facts_on_first_try(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        llm = ScriptedLanguageModel([golden_facts["C01"]])

        facts = await FactExtractor(llm).extract(conversations["C01"], dataset.agent_spec)

        assert facts == golden_facts["C01"]
        assert len(llm.calls) == 1
        assert llm.calls[0].schema is ConversationFacts

    async def test_retries_with_feedback_when_turns_do_not_fit(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        llm = ScriptedLanguageModel([SHIFTED, golden_facts["C01"]])

        facts = await FactExtractor(llm).extract(conversations["C01"], dataset.agent_spec)

        assert facts == golden_facts["C01"]
        assert (
            "debt_disclosure_turn=5: se esperaba un turno de 'agente'" in llm.calls[1].user_prompt
        )

    async def test_retries_with_feedback_when_answer_is_not_valid_json(
        self,
        dataset: Dataset,
        conversations: dict[str, Conversation],
        golden_facts: dict[str, ConversationFacts],
    ) -> None:
        llm = ScriptedLanguageModel([InvalidResponseError("outcome: invalid"), golden_facts["C01"]])

        await FactExtractor(llm).extract(conversations["C01"], dataset.agent_spec)

        assert "respuesta no válida para el esquema: outcome: invalid" in llm.calls[1].user_prompt

    async def test_gives_up_after_max_attempts(
        self, dataset: Dataset, conversations: dict[str, Conversation]
    ) -> None:
        llm = ScriptedLanguageModel([SHIFTED, SHIFTED])

        with pytest.raises(FactExtractionError, match="C01: hechos inconsistentes tras 2 intentos"):
            await FactExtractor(llm, max_attempts=2).extract(
                conversations["C01"], dataset.agent_spec
            )

    async def test_transport_errors_are_not_retried_here(
        self, dataset: Dataset, conversations: dict[str, Conversation]
    ) -> None:
        # The adapter already retried; asking again here would multiply the attempts.
        llm = ScriptedLanguageModel([LanguageModelError("quota")])

        with pytest.raises(LanguageModelError):
            await FactExtractor(llm).extract(conversations["C01"], dataset.agent_spec)
        assert len(llm.calls) == 1
