"""Ports: what the application needs from the outside world.

Adapters implement these protocols structurally (no inheritance), so the
domain and the use cases never import a vendor SDK.
"""

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from callaudit.application.models import DatasetAudit
from callaudit.domain.audit import ConversationAudit
from callaudit.domain.conversation import AgentSpec, Conversation
from callaudit.domain.facts import ConversationFacts


class LanguageModelError(Exception):
    """The language model could not produce an answer: network, quota, timeout, disabled."""


class InvalidResponseError(LanguageModelError):
    """The language model answered, but not with a valid instance of the schema.

    Unlike transport errors, it is worth asking again with feedback.
    """


class StructuredLanguageModel(Protocol):
    """A language model that answers with an instance of a given Pydantic schema."""

    @property
    def model_name(self) -> str: ...

    async def generate[T: BaseModel](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
    ) -> T:
        """Return a validated `schema` instance or raise `LanguageModelError`."""
        ...


class FactSource(Protocol):
    """Where the facts of a conversation come from: a language model, or a replay in development."""

    @property
    def name(self) -> str: ...

    async def extract(self, conversation: Conversation, spec: AgentSpec) -> ConversationFacts:
        """Return the facts, or raise; the audit service degrades on any exception."""
        ...


class PersistenceError(Exception):
    """The audit store failed: unreachable, timeout, constraint violation."""


class PersistenceUnavailableError(PersistenceError):
    """No audit store is configured (DATABASE_URL is not set)."""


class AuditRepository(Protocol):
    """Stores audits and dataset runs so they can be read back by identifier."""

    @property
    def name(self) -> str: ...

    @property
    def enabled(self) -> bool:
        """False when no store is configured: saving is a silent no-op and reads are unavailable."""
        ...

    async def save_audit(self, audit: ConversationAudit) -> None: ...

    async def save_run(self, run: DatasetAudit) -> None:
        """Store the run and all of its audits atomically."""
        ...

    async def get_audit(self, audit_id: UUID) -> ConversationAudit | None: ...

    async def get_run(self, run_id: UUID) -> DatasetAudit | None: ...

    async def ping(self) -> None:
        """Raise `PersistenceError` if the store cannot be reached."""
        ...

    async def close(self) -> None: ...
