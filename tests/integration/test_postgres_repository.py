"""PostgresAuditRepository against a real, migrated Postgres.

Runs only when TEST_DATABASE_URL points to a database with the migration
applied (for example the local docker compose stack):
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/postgres uv run pytest
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from callaudit.adapters.persistence.postgres import (
    PostgresAuditRepository,
    audit_runs,
    conversation_audits,
)
from callaudit.application.models import DatasetAudit
from callaudit.application.ports import PersistenceError
from callaudit.domain.conversation import Conversation
from callaudit.domain.engine import audit_conversation
from callaudit.domain.facts import ConversationFacts
from callaudit.domain.report import build_report

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
async def repository() -> AsyncIterator[PostgresAuditRepository]:
    assert DATABASE_URL is not None
    repo = PostgresAuditRepository.from_url(DATABASE_URL)
    yield repo
    await repo.close()


async def _cleanup(repo: PostgresAuditRepository, run_id: object, audit_ids: list[object]) -> None:
    async with repo._engine.begin() as connection:
        await connection.execute(
            delete(conversation_audits).where(conversation_audits.c.audit_id.in_(audit_ids))
        )
        await connection.execute(delete(audit_runs).where(audit_runs.c.run_id == run_id))


async def test_round_trip_of_a_single_audit(
    repository: PostgresAuditRepository,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    audit = audit_conversation(conversations["C09"], golden_facts["C09"])

    await repository.save_audit(audit)
    stored = await repository.get_audit(audit.audit_id)

    try:
        assert stored == audit.model_copy(update={"persisted": True})
    finally:
        await _cleanup(repository, None, [audit.audit_id])


async def test_round_trip_of_a_run_keeps_order_and_report(
    repository: PostgresAuditRepository,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    audits = [audit_conversation(conversations[cid], golden_facts[cid]) for cid in golden_facts]
    run = DatasetAudit(
        run_id=uuid4(),
        generated_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        rubric_version="2026-09-25",
        model="test",
        report=build_report(audits),
        audits=audits,
    )

    await repository.save_run(run)
    stored = await repository.get_run(run.run_id)

    try:
        assert stored is not None
        assert stored.report == run.report
        assert [a.conversation_id for a in stored.audits] == [a.conversation_id for a in audits]
        assert stored.persisted is True
    finally:
        await _cleanup(repository, run.run_id, [a.audit_id for a in audits])


async def test_duplicate_ids_raise_persistence_error(
    repository: PostgresAuditRepository,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    audit = audit_conversation(conversations["C01"], golden_facts["C01"])
    await repository.save_audit(audit)
    try:
        with pytest.raises(PersistenceError):
            await repository.save_audit(audit)
    finally:
        await _cleanup(repository, None, [audit.audit_id])


async def test_unknown_ids_return_none(repository: PostgresAuditRepository) -> None:
    assert await repository.get_audit(uuid4()) is None
    assert await repository.get_run(uuid4()) is None


async def test_unreachable_database_raises_persistence_error() -> None:
    repo = PostgresAuditRepository.from_url(
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:1/postgres", timeout_seconds=2
    )
    try:
        with pytest.raises(PersistenceError):
            await repo.ping()
    finally:
        await repo.close()
