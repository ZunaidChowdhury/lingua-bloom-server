"""asyncpg implementation of the repository protocol (ADR-008).

Every statement is a module-level constant with positional placeholders; no SQL
is built from user data. Writes for a turn run in a single transaction (ADR-010).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import asyncpg

from app.repositories.base import (
    AttemptRecord,
    LevelEventRecord,
    MessageRecord,
    NewAttempt,
    NewMessage,
    NewSession,
    RecentWin,
    SessionRecord,
    TurnCommit,
    TurnState,
    UnknownSessionError,
    accuracy_ratio,
    relative_day_label,
)

INSERT_SESSION = """
insert into sessions (token_hash, nickname, avatar, expires_at)
values ($1, $2, $3, $4)
returning id, token_hash, nickname, avatar, level, learning_streak,
          turns_since_checkin, turn_count, pending_item_id, pending_attempts,
          last_feeling, created_at, last_active_at, expires_at
"""

SELECT_BY_TOKEN_HASH = """
select id, token_hash, nickname, avatar, level, learning_streak,
       turns_since_checkin, turn_count, pending_item_id, pending_attempts,
       last_feeling, created_at, last_active_at, expires_at
from sessions
where token_hash = $1
"""

SELECT_BY_ID = """
select id, token_hash, nickname, avatar, level, learning_streak,
       turns_since_checkin, turn_count, pending_item_id, pending_attempts,
       last_feeling, created_at, last_active_at, expires_at
from sessions
where id = $1
"""

UPDATE_LAST_ACTIVE = "update sessions set last_active_at = $2 where id = $1"

UPDATE_SESSION = """
update sessions set
  level = $2,
  learning_streak = $3,
  turns_since_checkin = $4,
  turn_count = $5,
  pending_item_id = $6,
  pending_attempts = $7,
  last_feeling = $8,
  last_active_at = $9
where id = $1
"""

DELETE_SESSION = "delete from sessions where id = $1"

DELETE_EXPIRED_SESSIONS = "delete from sessions where expires_at < $1"

COUNT_EXPIRED_SESSIONS = "select count(*) from sessions where expires_at < $1"

INSERT_MESSAGE = """
insert into messages (session_id, role, content, mode)
values ($1, $2, $3, $4)
returning id, session_id, role, content, mode, created_at
"""

SELECT_RECENT_MESSAGES = """
select id, session_id, role, content, mode, created_at
from messages
where session_id = $1
order by id desc
limit $2
"""

INSERT_ATTEMPT = """
insert into attempts (session_id, item_id, level, skill_tag, attempt_no, result, counted)
values ($1, $2, $3, $4, $5, $6, $7)
returning id, session_id, item_id, level, skill_tag, attempt_no, result, counted, created_at
"""

SELECT_RECENT_COUNTED_ATTEMPTS = """
select id, session_id, item_id, level, skill_tag, attempt_no, result, counted, created_at
from attempts
where session_id = $1 and level = $2 and counted
order by id desc
limit $3
"""

SELECT_RECENT_LEVEL_EVENTS = """
select id, session_id, from_level, to_level, created_at
from level_events
where session_id = $1
order by id desc
limit $2
"""

INSERT_LEVEL_EVENT = """
insert into level_events (session_id, from_level, to_level)
values ($1, $2, $3)
"""

TURN_STATE = """
with target as (
    select level from sessions where id = $1
),
recent_messages as (
    select id, session_id, role, content, mode, created_at
    from messages
    where session_id = $1
    order by id desc
    limit 6
),
recent_attempts as (
    select a.id, a.session_id, a.item_id, a.level, a.skill_tag,
           a.attempt_no, a.result, a.counted, a.created_at
    from attempts a
    join target t on a.level = t.level
    where a.session_id = $1 and a.counted
    order by a.id desc
    limit 5
),
skill_stats as (
    select skill_tag,
           sum(case when result = 'correct' then 1 else 0 end) as correct_count,
           count(*) as total_count
    from attempts
    where session_id = $1 and counted
    group by skill_tag
),
recent_wins as (
    select item_id, created_at
    from attempts
    where session_id = $1 and counted and result = 'correct'
    order by id desc
    limit 3
)
select
    (select coalesce(json_agg(m order by m.id), '[]'::json) from recent_messages m) as messages,
    (select coalesce(json_agg(a order by a.id), '[]'::json) from recent_attempts a) as attempts,
    (select coalesce(json_agg(s), '[]'::json) from skill_stats s) as skills,
    (select coalesce(json_agg(w order by w.created_at desc), '[]'::json) from recent_wins w) as wins
"""


def _session_from_row(row: asyncpg.Record) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        token_hash=row["token_hash"],
        nickname=row["nickname"],
        avatar=row["avatar"],
        level=row["level"],
        learning_streak=row["learning_streak"],
        turns_since_checkin=row["turns_since_checkin"],
        turn_count=row["turn_count"],
        pending_item_id=row["pending_item_id"],
        pending_attempts=row["pending_attempts"],
        last_feeling=row["last_feeling"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
        expires_at=row["expires_at"],
    )


def _message_from_row(row: asyncpg.Record) -> MessageRecord:
    return MessageRecord(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        mode=row["mode"],
        created_at=row["created_at"],
    )


def _attempt_from_row(row: asyncpg.Record) -> AttemptRecord:
    return AttemptRecord(
        id=row["id"],
        session_id=row["session_id"],
        item_id=row["item_id"],
        level=row["level"],
        skill_tag=row["skill_tag"],
        attempt_no=row["attempt_no"],
        result=row["result"],
        counted=row["counted"],
        created_at=row["created_at"],
    )


def _level_event_from_row(row: asyncpg.Record) -> LevelEventRecord:
    return LevelEventRecord(
        id=row["id"],
        session_id=row["session_id"],
        from_level=row["from_level"],
        to_level=row["to_level"],
        created_at=row["created_at"],
    )


def _affected(status: str) -> int:
    parts = status.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _message_from_payload(session_id: uuid.UUID, payload: dict[str, Any]) -> MessageRecord:
    return MessageRecord(
        id=payload["id"],
        session_id=session_id,
        role=payload["role"],
        content=payload["content"],
        mode=payload["mode"],
        created_at=_as_datetime(payload["created_at"]),
    )


def _attempt_from_payload(session_id: uuid.UUID, payload: dict[str, Any]) -> AttemptRecord:
    return AttemptRecord(
        id=payload["id"],
        session_id=session_id,
        item_id=payload["item_id"],
        level=payload["level"],
        skill_tag=payload["skill_tag"],
        attempt_no=payload["attempt_no"],
        result=payload["result"],
        counted=payload["counted"],
        created_at=_as_datetime(payload["created_at"]),
    )


class PostgresRepository:
    """The `Repository` protocol backed by an asyncpg pool."""

    def __init__(
        self, pool: asyncpg.Pool, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._pool = pool
        self._now = clock or _utcnow

    async def create_session(self, new: NewSession) -> SessionRecord:
        row = await self._pool.fetchrow(
            INSERT_SESSION, new.token_hash, new.nickname, new.avatar, new.expires_at
        )
        assert row is not None
        return _session_from_row(row)

    async def get_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        row = await self._pool.fetchrow(SELECT_BY_TOKEN_HASH, token_hash)
        return _session_from_row(row) if row is not None else None

    async def get_by_id(self, session_id: uuid.UUID) -> SessionRecord | None:
        row = await self._pool.fetchrow(SELECT_BY_ID, session_id)
        return _session_from_row(row) if row is not None else None

    async def touch_last_active(self, session_id: uuid.UUID, when: datetime) -> None:
        await self._pool.execute(UPDATE_LAST_ACTIVE, session_id, when)

    async def delete_session(self, session_id: uuid.UUID) -> None:
        await self._pool.execute(DELETE_SESSION, session_id)

    async def purge_expired(self, now: datetime) -> int:
        status = await self._pool.execute(DELETE_EXPIRED_SESSIONS, now)
        return _affected(status)

    async def count_expired(self, now: datetime) -> int:
        count = await self._pool.fetchval(COUNT_EXPIRED_SESSIONS, now)
        return int(count or 0)

    async def add_message(self, session_id: uuid.UUID, new: NewMessage) -> MessageRecord:
        row = await self._pool.fetchrow(
            INSERT_MESSAGE, session_id, new.role, new.content, new.mode
        )
        assert row is not None
        return _message_from_row(row)

    async def recent_messages(
        self, session_id: uuid.UUID, limit: int
    ) -> list[MessageRecord]:
        if limit <= 0:
            return []
        rows = await self._pool.fetch(SELECT_RECENT_MESSAGES, session_id, limit)
        return [_message_from_row(row) for row in reversed(rows)]

    async def add_attempt(self, session_id: uuid.UUID, new: NewAttempt) -> AttemptRecord:
        row = await self._pool.fetchrow(
            INSERT_ATTEMPT,
            session_id,
            new.item_id,
            new.level,
            new.skill_tag,
            new.attempt_no,
            new.result,
            new.counted,
        )
        assert row is not None
        return _attempt_from_row(row)

    async def recent_counted_attempts(
        self, session_id: uuid.UUID, level: int, limit: int
    ) -> list[AttemptRecord]:
        if limit <= 0:
            return []
        rows = await self._pool.fetch(
            SELECT_RECENT_COUNTED_ATTEMPTS, session_id, level, limit
        )
        return [_attempt_from_row(row) for row in reversed(rows)]

    async def recent_level_events(
        self, session_id: uuid.UUID, limit: int
    ) -> list[LevelEventRecord]:
        if limit <= 0:
            return []
        rows = await self._pool.fetch(SELECT_RECENT_LEVEL_EVENTS, session_id, limit)
        return [_level_event_from_row(row) for row in reversed(rows)]

    async def persist_turn(self, commit: TurnCommit) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            status = await connection.execute(
                UPDATE_SESSION,
                commit.session_id,
                commit.session.level,
                commit.session.learning_streak,
                commit.session.turns_since_checkin,
                commit.session.turn_count,
                commit.session.pending_item_id,
                commit.session.pending_attempts,
                commit.session.last_feeling,
                commit.session.last_active_at,
            )
            if _affected(status) == 0:
                raise UnknownSessionError(f"unknown session: {commit.session_id}")
            for message in commit.messages:
                await connection.execute(
                    INSERT_MESSAGE,
                    commit.session_id,
                    message.role,
                    message.content,
                    message.mode,
                )
            for attempt in commit.attempts:
                await connection.execute(
                    INSERT_ATTEMPT,
                    commit.session_id,
                    attempt.item_id,
                    attempt.level,
                    attempt.skill_tag,
                    attempt.attempt_no,
                    attempt.result,
                    attempt.counted,
                )
            for event in commit.level_events:
                await connection.execute(
                    INSERT_LEVEL_EVENT,
                    commit.session_id,
                    event.from_level,
                    event.to_level,
                )

    async def get_turn_state(self, session_id: uuid.UUID) -> TurnState | None:
        session_row, context_row = await asyncio.gather(
            self._pool.fetchrow(SELECT_BY_ID, session_id),
            self._pool.fetchrow(TURN_STATE, session_id),
        )
        if session_row is None or context_row is None:
            return None

        session = _session_from_row(session_row)
        messages = tuple(
            _message_from_payload(session_id, payload)
            for payload in json.loads(context_row["messages"])
        )
        recent_attempts = tuple(
            _attempt_from_payload(session_id, payload)
            for payload in json.loads(context_row["attempts"])
        )
        skill_accuracy = {
            payload["skill_tag"]: accuracy_ratio(
                int(payload["correct_count"]), int(payload["total_count"])
            )
            for payload in json.loads(context_row["skills"])
        }
        now = self._now()
        recent_wins = tuple(
            RecentWin(
                item_id=payload["item_id"],
                day_label=relative_day_label(_as_datetime(payload["created_at"]), now),
            )
            for payload in json.loads(context_row["wins"])
        )
        return TurnState(
            session=session,
            messages=messages,
            recent_attempts=recent_attempts,
            skill_accuracy=skill_accuracy,
            recent_wins=recent_wins,
        )
