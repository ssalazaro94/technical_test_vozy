"""PostgresFactCache against a real, migrated Postgres (enabled by TEST_DATABASE_URL)."""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from callaudit.adapters.persistence.postgres import PostgresFactCache, create_engine, fact_cache
from callaudit.application.agent_spec import LINA_AGENT_SPEC
from callaudit.application.fact_cache import fact_cache_key
from callaudit.domain.conversation import Conversation
from callaudit.domain.facts import ConversationFacts

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not set")

MODEL = "integration-test-model"


@pytest.fixture
async def cache() -> AsyncIterator[PostgresFactCache]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    yield PostgresFactCache(engine)
    async with engine.begin() as connection:
        await connection.execute(delete(fact_cache).where(fact_cache.c.model == MODEL))
    await engine.dispose()


async def test_round_trip_and_first_write_wins(
    cache: PostgresFactCache,
    conversations: dict[str, Conversation],
    golden_facts: dict[str, ConversationFacts],
) -> None:
    key = fact_cache_key(conversations["C05"], LINA_AGENT_SPEC, MODEL)
    assert await cache.get(key) is None

    await cache.put(key, MODEL, golden_facts["C05"])
    await cache.put(key, MODEL, golden_facts["C01"])  # same key: ignored, no error

    assert await cache.get(key) == golden_facts["C05"]
