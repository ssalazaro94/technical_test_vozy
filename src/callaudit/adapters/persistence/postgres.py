"""Postgres repository (Supabase in production, a local container in development).

Each audit is stored whole as JSONB, which is the source of truth when reading
it back, plus a few columns (score, severity, failed criteria...) that make
the table queryable with plain SQL without parsing JSON.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    Uuid,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from callaudit.application.models import DatasetAudit
from callaudit.application.ports import PersistenceError
from callaudit.domain.audit import ConversationAudit
from callaudit.domain.report import DatasetReport

SCHEMA = "callaudit"
metadata = MetaData(schema=SCHEMA)

# Mirrors supabase/migrations; the migration is what creates the tables.
audit_runs = Table(
    "audit_runs",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("rubric_version", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("total_conversations", Integer, nullable=False),
    Column("average_score", Numeric(5, 1), nullable=False),
    Column("report", JSONB, nullable=False),
)

conversation_audits = Table(
    "conversation_audits",
    metadata,
    Column("audit_id", Uuid, primary_key=True),
    Column("run_id", Uuid, ForeignKey(audit_runs.c.run_id)),
    Column("run_position", Integer),
    Column("conversation_id", Text, nullable=False),
    Column("call_date", Date, nullable=False),
    Column("analysis", Text, nullable=False),
    Column("score", Numeric(5, 1), nullable=False),
    Column("severity", Text, nullable=False),
    Column("outcome", Text),
    Column("failed_criteria", ARRAY(Text), nullable=False),
    Column("audit", JSONB, nullable=False),
)


def _audit_row(
    audit: ConversationAudit, run_id: UUID | None = None, position: int | None = None
) -> dict[str, Any]:
    return {
        "audit_id": audit.audit_id,
        "run_id": run_id,
        "run_position": position,
        "conversation_id": audit.conversation_id,
        "call_date": audit.call_date,
        "analysis": audit.analysis.value,
        "score": audit.score,
        "severity": audit.severity.value,
        "outcome": audit.outcome.value if audit.outcome else None,
        "failed_criteria": audit.failed_criteria,
        # Stored as it was produced; `persisted` is set when read back.
        "audit": audit.model_dump(mode="json"),
    }


def _stored(audit_json: dict[str, Any]) -> ConversationAudit:
    return ConversationAudit.model_validate({**audit_json, "persisted": True})


class PostgresAuditRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: str, *, timeout_seconds: float = 10) -> "PostgresAuditRepository":
        engine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=5,
            # Supabase's pooler and container restarts can drop idle
            # connections; check them before use and recycle regularly.
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"timeout": timeout_seconds, "command_timeout": timeout_seconds},
        )
        return cls(engine)

    @property
    def name(self) -> str:
        return "postgres"

    @property
    def enabled(self) -> bool:
        return True

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncConnection]:
        """One transaction; any database or network error becomes `PersistenceError`."""
        try:
            async with self._engine.begin() as connection:
                yield connection
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            raise PersistenceError(f"{type(exc).__name__}: {exc}") from exc

    async def save_audit(self, audit: ConversationAudit) -> None:
        async with self._transaction() as connection:
            await connection.execute(conversation_audits.insert(), [_audit_row(audit)])

    async def save_run(self, run: DatasetAudit) -> None:
        async with self._transaction() as connection:
            await connection.execute(
                audit_runs.insert(),
                [
                    {
                        "run_id": run.run_id,
                        "generated_at": run.generated_at,
                        "rubric_version": run.rubric_version,
                        "model": run.model,
                        "total_conversations": run.report.total_conversations,
                        "average_score": run.report.average_score,
                        "report": run.report.model_dump(mode="json"),
                    }
                ],
            )
            await connection.execute(
                conversation_audits.insert(),
                [_audit_row(a, run.run_id, i) for i, a in enumerate(run.audits)],
            )

    async def get_audit(self, audit_id: UUID) -> ConversationAudit | None:
        query = select(conversation_audits.c.audit).where(
            conversation_audits.c.audit_id == audit_id
        )
        async with self._transaction() as connection:
            stored = (await connection.execute(query)).scalar_one_or_none()
        return _stored(stored) if stored is not None else None

    async def get_run(self, run_id: UUID) -> DatasetAudit | None:
        run_query = select(audit_runs).where(audit_runs.c.run_id == run_id)
        audits_query = (
            select(conversation_audits.c.audit)
            .where(conversation_audits.c.run_id == run_id)
            .order_by(conversation_audits.c.run_position)
        )
        async with self._transaction() as connection:
            run = (await connection.execute(run_query)).mappings().one_or_none()
            if run is None:
                return None
            audits: list[dict[str, Any]] = list(
                (await connection.execute(audits_query)).scalars().all()
            )
        return DatasetAudit(
            run_id=run["run_id"],
            generated_at=run["generated_at"],
            rubric_version=run["rubric_version"],
            model=run["model"],
            report=DatasetReport.model_validate(run["report"]),
            audits=[_stored(audit) for audit in audits],
            persisted=True,
        )

    async def ping(self) -> None:
        async with self._transaction() as connection:
            await connection.execute(text("select 1"))

    async def close(self) -> None:
        await self._engine.dispose()
