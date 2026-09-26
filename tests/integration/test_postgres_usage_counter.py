"""PostgresUsageCounter against a real, migrated Postgres (enabled by TEST_DATABASE_URL)."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import delete

from callaudit.adapters.persistence.postgres import (
    PostgresUsageCounter,
    create_engine,
    llm_daily_usage,
)

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not set")

# A day far from any real usage, deleted after the test.
TEST_DAY = date(2099, 1, 1)


@pytest.fixture
async def counter() -> AsyncIterator[PostgresUsageCounter]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    yield PostgresUsageCounter(engine)
    async with engine.begin() as connection:
        await connection.execute(delete(llm_daily_usage).where(llm_daily_usage.c.day == TEST_DAY))
    await engine.dispose()


async def test_concurrent_increments_are_never_lost(counter: PostgresUsageCounter) -> None:
    results = await asyncio.gather(*(counter.increment(TEST_DAY) for _ in range(8)))

    assert sorted(results) == list(range(1, 9))
