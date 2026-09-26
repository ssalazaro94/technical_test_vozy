"""Use cases: audit one conversation, or a whole dataset with its report."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from callaudit.application.fact_extraction import FactExtractor
from callaudit.application.models import DatasetAudit
from callaudit.domain.audit import ConversationAudit
from callaudit.domain.conversation import AgentSpec, Conversation, Dataset
from callaudit.domain.criteria import RUBRIC_VERSION
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts
from callaudit.domain.report import build_report

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AuditService:
    def __init__(
        self,
        extractor: FactExtractor,
        *,
        model_name: str,
        max_concurrency: int = 4,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._extractor = extractor
        self._model_name = model_name
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._clock = clock

    @property
    def model_name(self) -> str:
        return self._model_name

    async def _facts(
        self, conversation: Conversation, spec: AgentSpec
    ) -> tuple[ConversationFacts | None, list[str]]:
        """Facts from the model, or None plus a warning. Never raises.

        The catch is deliberately broad: whatever goes wrong on the model side
        (quota, timeout, invalid answers, an SDK bug), the audit must still be
        returned with the criteria that code can evaluate on its own.
        """
        async with self._semaphore:
            try:
                return await self._extractor.extract(conversation, spec), []
            except Exception as exc:
                logger.warning("fact extraction failed for %s: %r", conversation.id, exc)
                return None, [
                    "Análisis del modelo de lenguaje no disponible; solo se evaluaron los "
                    f"criterios de código. Causa: {type(exc).__name__}: {exc}"
                ]

    async def audit_conversation(
        self, conversation: Conversation, spec: AgentSpec
    ) -> ConversationAudit:
        facts, warnings = await self._facts(conversation, spec)
        return audit_conversation(conversation, facts, warnings=warnings)

    async def audit_dataset(self, dataset: Dataset) -> DatasetAudit:
        audits = await asyncio.gather(
            *(
                self.audit_conversation(conversation, dataset.agent_spec)
                for conversation in dataset.conversations
            )
        )
        return DatasetAudit(
            run_id=uuid4(),
            generated_at=self._clock(),
            rubric_version=RUBRIC_VERSION,
            model=self._model_name,
            report=build_report(audits),
            audits=list(audits),
        )
