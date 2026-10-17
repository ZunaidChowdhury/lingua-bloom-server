"""Shared, backend-agnostic contract tests for repositories.

Subclasses supply a `repository` fixture pointing at a concrete backend.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.base import (
    NewAttempt,
    NewLevelEvent,
    NewMessage,
    NewSession,
    Repository,
    SessionUpdate,
    TurnCommit,
    UnknownSessionError,
)


def _future(days: int = 30) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def _update(**overrides: object) -> SessionUpdate:
    values: dict[str, object] = {
        "level": 2,
        "learning_streak": 0,
        "turns_since_checkin": 0,
        "turn_count": 1,
        "pending_item_id": None,
        "pending_attempts": 0,
        "last_feeling": None,
        "last_active_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SessionUpdate(**values)  # type: ignore[arg-type]


async def _create(repository: Repository, **overrides: object) -> object:
    new = NewSession(
        token_hash=str(overrides.get("token_hash", uuid.uuid4().hex)),
        nickname=overrides.get("nickname"),  # type: ignore[arg-type]
        avatar=str(overrides.get("avatar", "sprout")),
        expires_at=overrides.get("expires_at", _future()),  # type: ignore[arg-type]
    )
    return await repository.create_session(new)


class RepositoryContract:
    async def test_create_session_defaults(self, repository: Repository) -> None:
        session = await repository.create_session(
            NewSession(token_hash="hash-1", nickname="Mimi", avatar="sprout", expires_at=_future())
        )
        assert session.level == 1
        assert session.learning_streak == 0
        assert session.turns_since_checkin == 0
        assert session.turn_count == 0
        assert session.pending_item_id is None
        assert session.pending_attempts == 0
        assert session.last_feeling is None
        assert isinstance(session.id, uuid.UUID)
        assert session.expires_at > session.created_at
        assert await repository.get_by_id(session.id) == session

    async def test_get_by_token_hash(self, repository: Repository) -> None:
        session = await _create(repository)
        assert await repository.get_by_token_hash(session.token_hash) == session
        assert await repository.get_by_token_hash("missing") is None

    async def test_touch_last_active(self, repository: Repository) -> None:
        session = await _create(repository)
        later = datetime.now(UTC) + timedelta(minutes=5)
        await repository.touch_last_active(session.id, later)
        updated = await repository.get_by_id(session.id)
        assert updated is not None
        assert updated.last_active_at == later

    async def test_delete_session_cascades(self, repository: Repository) -> None:
        session = await _create(repository)
        await repository.persist_turn(
            TurnCommit(
                session_id=session.id,
                session=_update(),
                messages=(NewMessage(role="child", content="hi"),),
                attempts=(
                    NewAttempt(
                        item_id="i1",
                        level=2,
                        skill_tag="s",
                        attempt_no=1,
                        result="correct",
                        counted=True,
                    ),
                ),
                level_events=(NewLevelEvent(from_level=1, to_level=2),),
            )
        )
        await repository.delete_session(session.id)
        assert await repository.get_by_id(session.id) is None
        assert await repository.recent_messages(session.id, 10) == []
        assert await repository.recent_counted_attempts(session.id, 2, 10) == []
        assert await repository.recent_level_events(session.id, 10) == []

    async def test_purge_expired(self, repository: Repository) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        live = await _create(repository, token_hash="live")
        dead = await _create(repository, token_hash="dead", expires_at=past)
        now = datetime.now(UTC)
        assert await repository.count_expired(now) == 1
        assert await repository.purge_expired(now) == 1
        assert await repository.get_by_id(dead.id) is None
        assert await repository.get_by_id(live.id) == live

    async def test_messages_are_recent_and_limited(self, repository: Repository) -> None:
        session = await _create(repository)
        for index in range(3):
            await repository.add_message(
                session.id, NewMessage(role="child", content=f"m{index}")
            )
        recent = await repository.recent_messages(session.id, 2)
        assert [message.content for message in recent] == ["m1", "m2"]

    async def test_attempts_filter_by_level_and_counted(
        self, repository: Repository
    ) -> None:
        session = await _create(repository)
        await repository.add_attempt(
            session.id,
            NewAttempt(
                item_id="a",
                level=1,
                skill_tag="s",
                attempt_no=1,
                result="correct",
                counted=True,
            ),
        )
        await repository.add_attempt(
            session.id,
            NewAttempt(
                item_id="b",
                level=1,
                skill_tag="s",
                attempt_no=2,
                result="incorrect",
                counted=False,
            ),
        )
        await repository.add_attempt(
            session.id,
            NewAttempt(
                item_id="c",
                level=2,
                skill_tag="s",
                attempt_no=1,
                result="correct",
                counted=True,
            ),
        )
        counted = await repository.recent_counted_attempts(session.id, 1, 10)
        assert [attempt.item_id for attempt in counted] == ["a"]

    async def test_persist_turn_writes_everything(self, repository: Repository) -> None:
        session = await _create(repository)
        await repository.persist_turn(
            TurnCommit(
                session_id=session.id,
                session=_update(pending_item_id="l2-cat", last_feeling="happy"),
                messages=(
                    NewMessage(role="child", content="cat"),
                    NewMessage(role="bot", content="Yes! A cat.", mode="learning"),
                ),
                attempts=(
                    NewAttempt(
                        item_id="l2-cat",
                        level=2,
                        skill_tag="animals",
                        attempt_no=1,
                        result="correct",
                        counted=True,
                    ),
                ),
                level_events=(NewLevelEvent(from_level=1, to_level=2),),
            )
        )
        updated = await repository.get_by_id(session.id)
        assert updated is not None
        assert updated.level == 2
        assert updated.pending_item_id == "l2-cat"
        assert updated.last_feeling == "happy"

        messages = await repository.recent_messages(session.id, 10)
        assert [message.content for message in messages] == ["cat", "Yes! A cat."]
        assert messages[1].mode == "learning"

        attempts = await repository.recent_counted_attempts(session.id, 2, 10)
        assert [attempt.item_id for attempt in attempts] == ["l2-cat"]

        events = await repository.recent_level_events(session.id, 10)
        assert [(event.from_level, event.to_level) for event in events] == [(1, 2)]

    async def test_persist_turn_unknown_session_raises(
        self, repository: Repository
    ) -> None:
        with pytest.raises(UnknownSessionError):
            await repository.persist_turn(
                TurnCommit(session_id=uuid.uuid4(), session=_update())
            )

    async def test_turn_state_empty(self, repository: Repository) -> None:
        session = await _create(repository)
        state = await repository.get_turn_state(session.id)
        assert state is not None
        assert state.session == session
        assert state.messages == ()
        assert state.recent_attempts == ()
        assert state.skill_accuracy == {}
        assert state.recent_wins == ()

    async def test_turn_state_missing_returns_none(self, repository: Repository) -> None:
        assert await repository.get_turn_state(uuid.uuid4()) is None

    async def test_turn_state_populated(self, repository: Repository) -> None:
        session = await _create(repository)
        await repository.persist_turn(
            TurnCommit(
                session_id=session.id,
                session=_update(level=2),
                messages=(
                    NewMessage(role="child", content="hi"),
                    NewMessage(role="bot", content="hello", mode="learning"),
                ),
                attempts=(
                    NewAttempt(
                        item_id="l2-a",
                        level=2,
                        skill_tag="animals",
                        attempt_no=1,
                        result="correct",
                        counted=True,
                    ),
                    NewAttempt(
                        item_id="l2-b",
                        level=2,
                        skill_tag="colors",
                        attempt_no=1,
                        result="incorrect",
                        counted=True,
                    ),
                    NewAttempt(
                        item_id="l1-c",
                        level=1,
                        skill_tag="animals",
                        attempt_no=1,
                        result="correct",
                        counted=True,
                    ),
                ),
            )
        )
        state = await repository.get_turn_state(session.id)
        assert state is not None
        assert state.session.level == 2
        assert [message.content for message in state.messages] == ["hi", "hello"]
        assert [attempt.item_id for attempt in state.recent_attempts] == ["l2-a", "l2-b"]
        assert state.skill_accuracy["animals"] == pytest.approx(1.0)
        assert state.skill_accuracy["colors"] == pytest.approx(0.0)
        assert [win.item_id for win in state.recent_wins] == ["l1-c", "l2-a"]
        assert all(win.day_label == "today" for win in state.recent_wins)
