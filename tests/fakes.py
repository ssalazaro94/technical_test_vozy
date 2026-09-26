"""Test doubles for the `StructuredLanguageModel` port. No network, no quota."""

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel

from callaudit.application.models import DatasetAudit
from callaudit.application.ports import LanguageModelError, PersistenceError
from callaudit.domain.audit import ConversationAudit
from callaudit.domain.conversation import Conversation
from callaudit.domain.facts import ConversationFacts


@dataclass
class Call:
    system_prompt: str
    user_prompt: str
    schema: type[BaseModel]


class ScriptedLanguageModel:
    """Answers each call with the next item of a script: a model to return or an error to raise."""

    def __init__(self, script: Iterable[BaseModel | Exception]) -> None:
        self._script = iter(script)
        self.calls: list[Call] = []

    @property
    def model_name(self) -> str:
        return "scripted-fake"

    async def generate[T: BaseModel](
        self, *, system_prompt: str, user_prompt: str, schema: type[T]
    ) -> T:
        self.calls.append(Call(system_prompt, user_prompt, schema))
        item = next(self._script)
        if isinstance(item, Exception):
            raise item
        return schema.model_validate(item.model_dump())


@dataclass
class GoldenLanguageModel:
    """Returns the hand-annotated facts of whichever conversation is in the prompt.

    It also records how many calls were in flight at once, to verify the
    concurrency limit of the service.
    """

    conversations: Mapping[str, Conversation]
    facts: Mapping[str, ConversationFacts]
    failing: frozenset[str] = frozenset()
    latency_seconds: float = 0.01
    in_flight: int = 0
    max_in_flight: int = 0
    seen: list[str] = field(default_factory=list)

    @property
    def model_name(self) -> str:
        return "golden-fake"

    def _conversation_in(self, prompt: str) -> str:
        return next(
            cid
            for cid, conv in self.conversations.items()
            if f"Nombre: {conv.customer.name}\n" in prompt
        )

    async def generate[T: BaseModel](
        self, *, system_prompt: str, user_prompt: str, schema: type[T]
    ) -> T:
        cid = self._conversation_in(user_prompt)
        self.seen.append(cid)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.latency_seconds)
            if cid in self.failing:
                raise LanguageModelError("simulated quota exhausted")
            return schema.model_validate(self.facts[cid].model_dump())
        finally:
            self.in_flight -= 1


class InMemoryAuditRepository:
    """A working repository without a database."""

    def __init__(self) -> None:
        self.audits: dict[UUID, ConversationAudit] = {}
        self.runs: dict[UUID, DatasetAudit] = {}
        self.closed = False

    @property
    def name(self) -> str:
        return "memoria"

    @property
    def enabled(self) -> bool:
        return True

    async def save_audit(self, audit: ConversationAudit) -> None:
        self.audits[audit.audit_id] = audit

    async def save_run(self, run: DatasetAudit) -> None:
        self.runs[run.run_id] = run
        for audit in run.audits:
            self.audits[audit.audit_id] = audit

    async def get_audit(self, audit_id: UUID) -> ConversationAudit | None:
        audit = self.audits.get(audit_id)
        return audit.model_copy(update={"persisted": True}) if audit else None

    async def get_run(self, run_id: UUID) -> DatasetAudit | None:
        return self.runs.get(run_id)

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class BrokenAuditRepository(InMemoryAuditRepository):
    """A configured repository whose database is down."""

    async def save_audit(self, audit: ConversationAudit) -> None:
        raise PersistenceError("connection refused")

    async def save_run(self, run: DatasetAudit) -> None:
        raise PersistenceError("connection refused")

    async def get_audit(self, audit_id: UUID) -> ConversationAudit | None:
        raise PersistenceError("connection refused")

    async def get_run(self, run_id: UUID) -> DatasetAudit | None:
        raise PersistenceError("connection refused")

    async def ping(self) -> None:
        raise PersistenceError("connection refused")
