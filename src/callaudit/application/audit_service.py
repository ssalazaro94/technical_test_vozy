"""Use cases: audit one conversation or a whole dataset, persist it, read it back."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from callaudit.application.models import DatasetAudit
from callaudit.application.ports import AuditRepository, FactSource
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
        facts: FactSource,
        repository: AuditRepository,
        *,
        max_concurrency: int = 4,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._facts_source = facts
        self._repository = repository
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._clock = clock

    @property
    def model_name(self) -> str:
        return self._facts_source.name

    @property
    def repository(self) -> AuditRepository:
        return self._repository

    async def _facts(
        self, conversation: Conversation, spec: AgentSpec
    ) -> tuple[ConversationFacts | None, list[str]]:
        """Facts from the source, or None plus a warning. Never raises.

        The catch is deliberately broad: whatever goes wrong on the model side
        (quota, timeout, invalid answers, an SDK bug), the audit must still be
        returned with the criteria that code can evaluate on its own.
        """
        async with self._semaphore:
            try:
                return await self._facts_source.extract(conversation, spec), []
            except Exception as exc:
                logger.warning("fact extraction failed for %s: %r", conversation.id, exc)
                return None, [
                    "Análisis del modelo de lenguaje no disponible; solo se evaluaron los "
                    f"criterios de código. Causa: {type(exc).__name__}: {exc}"
                ]

    async def _audit(self, conversation: Conversation, spec: AgentSpec) -> ConversationAudit:
        facts, warnings = await self._facts(conversation, spec)
        return audit_conversation(conversation, facts, warnings=warnings)

    async def audit_conversation(
        self, conversation: Conversation, spec: AgentSpec
    ) -> ConversationAudit:
        audit = await self._audit(conversation, spec)
        try:
            await self._repository.save_audit(audit)
        except Exception as exc:
            # Persistence is a convenience: the caller still gets the audit.
            logger.warning("could not persist audit %s: %r", audit.audit_id, exc)
            return audit.model_copy(
                update={"warnings": [*audit.warnings, _not_persisted(self._repository, exc)]}
            )
        return audit.model_copy(update={"persisted": self._repository.enabled})

    async def audit_dataset(self, dataset: Dataset) -> DatasetAudit:
        audits = await asyncio.gather(
            *(
                self._audit(conversation, dataset.agent_spec)
                for conversation in dataset.conversations
            )
        )
        run = DatasetAudit(
            run_id=uuid4(),
            generated_at=self._clock(),
            rubric_version=RUBRIC_VERSION,
            model=self.model_name,
            report=build_report(audits),
            audits=list(audits),
        )
        try:
            await self._repository.save_run(run)
        except Exception as exc:
            logger.warning("could not persist run %s: %r", run.run_id, exc)
            return run
        return _mark_persisted(run) if self._repository.enabled else run

    async def get_audit(self, audit_id: UUID) -> ConversationAudit | None:
        return await self._repository.get_audit(audit_id)

    async def get_run(self, run_id: UUID) -> DatasetAudit | None:
        return await self._repository.get_run(run_id)


def _not_persisted(repository: AuditRepository, exc: Exception) -> str:
    return (
        f"La auditoría no se guardó ({repository.name}): {type(exc).__name__}. "
        "El resultado es válido, pero no podrá consultarse después por su identificador."
    )


def _mark_persisted(run: DatasetAudit) -> DatasetAudit:
    return run.model_copy(
        update={
            "persisted": True,
            "audits": [audit.model_copy(update={"persisted": True}) for audit in run.audits],
        }
    )
