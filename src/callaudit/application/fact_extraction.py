"""Use case: obtain `ConversationFacts` for one conversation from the language model."""

from callaudit.application.ports import InvalidResponseError, StructuredLanguageModel
from callaudit.application.prompts import build_system_prompt, build_user_prompt
from callaudit.domain.conversation import AgentSpec, Conversation
from callaudit.domain.facts import ConversationFacts


class FactExtractionError(Exception):
    """The model kept answering with facts that do not fit the transcript."""


class FactExtractor:
    """Asks the model for facts and checks them against the transcript.

    Transport failures are retried by the adapter, not here. This loop only
    retries answers that arrived but were wrong (invalid JSON, a turn index out
    of range or from the wrong speaker), sending the problems back as feedback.
    """

    def __init__(self, llm: StructuredLanguageModel, *, max_attempts: int = 2) -> None:
        self._llm = llm
        self._max_attempts = max_attempts

    @property
    def name(self) -> str:
        return self._llm.model_name

    async def extract(self, conversation: Conversation, spec: AgentSpec) -> ConversationFacts:
        system_prompt = build_system_prompt(spec)
        feedback: list[str] = []
        for _ in range(self._max_attempts):
            try:
                facts = await self._llm.generate(
                    system_prompt=system_prompt,
                    user_prompt=build_user_prompt(conversation, feedback),
                    schema=ConversationFacts,
                )
            except InvalidResponseError as exc:
                feedback = [f"respuesta no válida para el esquema: {exc}"]
                continue
            feedback = facts.inconsistencies(conversation)
            if not feedback:
                return facts
        raise FactExtractionError(
            f"{conversation.id}: hechos inconsistentes tras {self._max_attempts} intentos: "
            + "; ".join(feedback)
        )
