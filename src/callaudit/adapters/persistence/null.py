"""Repository used when no database is configured."""

from uuid import UUID

from callaudit.application.models import DatasetAudit
from callaudit.application.ports import PersistenceUnavailableError
from callaudit.domain.audit import ConversationAudit
from callaudit.domain.facts import ConversationFacts


class NullAuditRepository:
    """Saving is a no-op, so auditing works; reading says persistence is unavailable."""

    @property
    def name(self) -> str:
        return "deshabilitada"

    @property
    def enabled(self) -> bool:
        return False

    async def save_audit(self, audit: ConversationAudit) -> None:
        return None

    async def save_run(self, run: DatasetAudit) -> None:
        return None

    async def get_audit(self, audit_id: UUID) -> ConversationAudit | None:
        raise PersistenceUnavailableError("no hay base de datos configurada (DATABASE_URL)")

    async def get_run(self, run_id: UUID) -> DatasetAudit | None:
        raise PersistenceUnavailableError("no hay base de datos configurada (DATABASE_URL)")

    async def ping(self) -> None:
        raise PersistenceUnavailableError("no hay base de datos configurada (DATABASE_URL)")

    async def close(self) -> None:
        return None


class NullFactCache:
    """No cache: every lookup misses and nothing is stored."""

    @property
    def name(self) -> str:
        return "deshabilitada"

    async def get(self, key: str) -> ConversationFacts | None:
        return None

    async def put(self, key: str, model: str, facts: ConversationFacts) -> None:
        return None
