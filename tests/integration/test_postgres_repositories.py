"""Run the repository contract suite and rollback checks against PostgreSQL.

Skipped unless TEST_DATABASE_URL is set. Run with: pytest -m integration
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import asyncpg
import pytest

from app.core.config import get_settings
from app.repositories.base import (
    NewAttempt,
    NewLevelEvent,
    NewMessage,
    NewSession,
    TurnCommit,
)
from app.repositories.postgres import PostgresRepository
from scripts.apply_migrations import apply_migrations
from tests.repositories.contract import RepositoryContract, _future, _update

pytestmark = pytest.mark.integration

logger = logging.getLogger("tests.integration.turn_state")


@pytest.fixture
async def repository() -> object:
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    pool = await asyncpg.create_pool(
        dsn=url, min_size=1, max_size=2, statement_cache_size=0
    )
    assert pool is not None
    try:
        async with pool.acquire() as connection:
            await apply_migrations(connection)
            await connection.execute("truncate sessions cascade")
        yield PostgresRepository(pool)
    finally:
        await pool.close()


class TestPostgresRepository(RepositoryContract):
    async def test_persist_turn_rolls_back_on_failure(self, repository: object) -> None:
        session = await repository.create_session(
            NewSession(
                token_hash=f"rollback-{datetime.now(UTC).timestamp()}",
                nickname=None,
                avatar="sprout",
                expires_at=_future(),
            )
        )
        commit = TurnCommit(
            session_id=session.id,
            session=_update(level=3),
            messages=(NewMessage(role="child", content="hi"),),
            attempts=(
                NewAttempt(
                    item_id="x",
                    level=1,
                    skill_tag="s",
                    attempt_no=1,
                    result="bogus",
                    counted=True,
                ),
            ),
            level_events=(NewLevelEvent(from_level=1, to_level=3),),
        )
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await repository.persist_turn(commit)
        reloaded = await repository.get_by_id(session.id)
        assert reloaded is not None
        assert reloaded.level == 1
        assert await repository.recent_messages(session.id, 10) == []
        assert await repository.recent_level_events(session.id, 10) == []

    async def test_get_turn_state_timing(self, repository: object) -> None:
        session = await repository.create_session(
            NewSession(
                token_hash=f"timing-{datetime.now(UTC).timestamp()}",
                nickname=None,
                avatar="sprout",
                expires_at=_future(),
            )
        )
        await repository.persist_turn(
            TurnCommit(
                session_id=session.id,
                session=_update(level=2),
                messages=(NewMessage(role="child", content="hi"),),
                attempts=(
                    NewAttempt(
                        item_id="t",
                        level=2,
                        skill_tag="animals",
                        attempt_no=1,
                        result="correct",
                        counted=True,
                    ),
                ),
            )
        )
        start = time.perf_counter()
        await repository.get_turn_state(session.id)
        cold_ms = (time.perf_counter() - start) * 1000
        await repository.get_turn_state(session.id)
        start = time.perf_counter()
        state = await repository.get_turn_state(session.id)
        warm_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "get_turn_state cold %.1f ms, warm %.1f ms (two gathered round trips); "
            "same-region target is < 40 ms",
            cold_ms,
            warm_ms,
        )
        assert state is not None
        assert warm_ms < 500
