"""Tests for the expired-session purge script (both modes, no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories.base import NewMessage, NewSession
from app.repositories.memory import InMemoryRepository
from scripts.purge_expired import build_parser, purge_expired_sessions

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)


def _expired_at(seconds_ago: int) -> datetime:
    return NOW - timedelta(seconds=seconds_ago)


def _live_at(seconds_ahead: int) -> datetime:
    return NOW + timedelta(seconds=seconds_ahead)


async def _seed(repo: InMemoryRepository) -> None:
    for i, expires_at in enumerate(
        [_expired_at(10), _expired_at(3600), _live_at(3600)]
    ):
        session = await repo.create_session(
            NewSession(
                token_hash=f"hash-{i}",
                nickname=f"Child{i}",
                avatar="sprout",
                expires_at=expires_at,
            )
        )
        await repo.add_message(
            session.id, NewMessage(role="bot", content="Hello!", mode="conversation")
        )


async def test_purge_dry_run_counts_without_deleting() -> None:
    repo = InMemoryRepository()
    await _seed(repo)

    count = await purge_expired_sessions(repo, NOW, dry_run=True)

    assert count == 2
    assert await repo.count_expired(NOW) == 2
    assert await repo.get_by_token_hash("hash-0") is not None
    assert await repo.get_by_token_hash("hash-2") is not None
    live = await repo.get_by_token_hash("hash-2")
    assert live is not None
    assert len(await repo.recent_messages(live.id, limit=10)) == 1


async def test_purge_deletes_expired_and_returns_count() -> None:
    repo = InMemoryRepository()
    await _seed(repo)

    count = await purge_expired_sessions(repo, NOW, dry_run=False)

    assert count == 2
    assert await repo.get_by_token_hash("hash-0") is None
    assert await repo.get_by_token_hash("hash-1") is None
    assert await repo.count_expired(NOW) == 0

    live = await repo.get_by_token_hash("hash-2")
    assert live is not None
    assert len(await repo.recent_messages(live.id, limit=10)) == 1


async def test_purge_no_expired_returns_zero() -> None:
    repo = InMemoryRepository()

    assert await purge_expired_sessions(repo, NOW, dry_run=True) == 0
    assert await purge_expired_sessions(repo, NOW, dry_run=False) == 0


def test_build_parser_dry_run_flag() -> None:
    parser = build_parser()
    assert parser.parse_args([]).dry_run is False
    assert parser.parse_args(["--dry-run"]).dry_run is True
