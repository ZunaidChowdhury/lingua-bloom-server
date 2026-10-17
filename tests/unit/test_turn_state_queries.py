"""Turn-state query shape: exactly two round trips, parsed into the read model."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.repositories.postgres import SELECT_BY_ID, TURN_STATE, PostgresRepository

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
SESSION_ID = uuid.uuid4()


class FakePool:
    """Records every query and replays canned rows."""

    def __init__(
        self, session_row: dict | None, context_row: dict | None
    ) -> None:
        self._session_row = session_row
        self._context_row = context_row
        self.calls: list[str] = []

    async def fetchrow(self, query: str, *args: object) -> dict | None:
        self.calls.append(query)
        if query == SELECT_BY_ID:
            return self._session_row
        if query == TURN_STATE:
            return self._context_row
        raise AssertionError("unexpected query")


def _session_row() -> dict:
    return {
        "id": SESSION_ID,
        "token_hash": "hash",
        "nickname": "Mimi",
        "avatar": "sprout",
        "level": 2,
        "learning_streak": 0,
        "turns_since_checkin": 0,
        "turn_count": 3,
        "pending_item_id": None,
        "pending_attempts": 0,
        "last_feeling": None,
        "created_at": NOW,
        "last_active_at": NOW,
        "expires_at": NOW,
    }


def _empty_context() -> dict:
    return {"messages": "[]", "attempts": "[]", "skills": "[]", "wins": "[]"}


def _record(**overrides: object) -> dict:
    values: dict[str, object] = {
        "id": overrides.get("id", 1),
        "session_id": str(SESSION_ID),
        "role": "child",
        "content": "hi",
        "mode": None,
        "created_at": "2026-10-17T11:00:00+00:00",
    }
    values.update(overrides)
    return values


def _attempt(**overrides: object) -> dict:
    values: dict[str, object] = {
        "id": overrides.get("id", 10),
        "session_id": str(SESSION_ID),
        "item_id": "l2-a",
        "level": 2,
        "skill_tag": "animals",
        "attempt_no": 1,
        "result": "correct",
        "counted": True,
        "created_at": "2026-10-17T11:00:00+00:00",
    }
    values.update(overrides)
    return values


def _populated_context() -> dict:
    return {
        "messages": json.dumps(
            [
                _record(id=1, content="hi"),
                _record(id=2, role="bot", content="hello", mode="learning"),
            ]
        ),
        "attempts": json.dumps(
            [
                _attempt(id=10, item_id="l2-a", result="correct"),
                _attempt(id=11, item_id="l2-b", result="incorrect"),
            ]
        ),
        "skills": json.dumps(
            [
                {"skill_tag": "animals", "correct_count": 2, "total_count": 3},
                {"skill_tag": "colors", "correct_count": 0, "total_count": 1},
            ]
        ),
        "wins": json.dumps([{"item_id": "l2-a", "created_at": "2026-10-17T11:00:00+00:00"}]),
    }


def _repository(pool: FakePool) -> PostgresRepository:
    return PostgresRepository(pool, clock=lambda: NOW)


async def test_uses_exactly_two_round_trips() -> None:
    pool = FakePool(_session_row(), _empty_context())
    await _repository(pool).get_turn_state(SESSION_ID)
    assert len(pool.calls) == 2


async def test_empty_session_matches_fixture() -> None:
    pool = FakePool(_session_row(), _empty_context())
    state = await _repository(pool).get_turn_state(SESSION_ID)
    assert state is not None
    assert state.session.id == SESSION_ID
    assert state.session.nickname == "Mimi"
    assert state.messages == ()
    assert state.recent_attempts == ()
    assert state.skill_accuracy == {}
    assert state.recent_wins == ()


async def test_populated_session_matches_fixture() -> None:
    pool = FakePool(_session_row(), _populated_context())
    state = await _repository(pool).get_turn_state(SESSION_ID)
    assert state is not None

    assert [message.content for message in state.messages] == ["hi", "hello"]
    assert state.messages[1].mode == "learning"
    assert state.messages[0].created_at == datetime(2026, 10, 17, 11, 0, tzinfo=UTC)

    assert [attempt.item_id for attempt in state.recent_attempts] == ["l2-a", "l2-b"]

    assert state.skill_accuracy == {"animals": 2 / 3, "colors": 0.0}

    assert [win.item_id for win in state.recent_wins] == ["l2-a"]
    assert state.recent_wins[0].day_label == "today"


async def test_missing_session_returns_none() -> None:
    pool = FakePool(None, _empty_context())
    assert await _repository(pool).get_turn_state(SESSION_ID) is None
