"""In-memory repository used by tests and local runs (no network)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from app.repositories.base import (
    TURN_STATE_ATTEMPTS,
    TURN_STATE_MESSAGES,
    TURN_STATE_WINS,
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InMemoryRepository:
    """Storage-agnostic implementation; each instance owns its own state."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._now = clock or _utcnow
        self._sessions: dict[uuid.UUID, SessionRecord] = {}
        self._messages: list[MessageRecord] = []
        self._attempts: list[AttemptRecord] = []
        self._level_events: list[LevelEventRecord] = []
        self._next_message_id = 1
        self._next_attempt_id = 1
        self._next_event_id = 1

    async def create_session(self, new: NewSession) -> SessionRecord:
        now = self._now()
        record = SessionRecord(
            id=uuid.uuid4(),
            token_hash=new.token_hash,
            nickname=new.nickname,
            avatar=new.avatar,
            level=1,
            learning_streak=0,
            turns_since_checkin=0,
            turn_count=0,
            pending_item_id=None,
            pending_attempts=0,
            last_feeling=None,
            created_at=now,
            last_active_at=now,
            expires_at=new.expires_at,
        )
        self._sessions[record.id] = record
        return record

    async def get_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        for record in self._sessions.values():
            if record.token_hash == token_hash:
                return record
        return None

    async def get_by_id(self, session_id: uuid.UUID) -> SessionRecord | None:
        return self._sessions.get(session_id)

    async def touch_last_active(self, session_id: uuid.UUID, when: datetime) -> None:
        record = self._sessions.get(session_id)
        if record is not None:
            self._sessions[session_id] = replace(record, last_active_at=when)

    async def delete_session(self, session_id: uuid.UUID) -> None:
        self._sessions.pop(session_id, None)
        self._messages = [m for m in self._messages if m.session_id != session_id]
        self._attempts = [a for a in self._attempts if a.session_id != session_id]
        self._level_events = [e for e in self._level_events if e.session_id != session_id]

    async def purge_expired(self, now: datetime) -> int:
        expired = [sid for sid, rec in self._sessions.items() if rec.expires_at < now]
        for session_id in expired:
            await self.delete_session(session_id)
        return len(expired)

    async def count_expired(self, now: datetime) -> int:
        return sum(1 for rec in self._sessions.values() if rec.expires_at < now)

    async def add_message(self, session_id: uuid.UUID, new: NewMessage) -> MessageRecord:
        record = MessageRecord(
            id=self._next_message_id,
            session_id=session_id,
            role=new.role,
            content=new.content,
            mode=new.mode,
            created_at=self._now(),
        )
        self._next_message_id += 1
        self._messages.append(record)
        return record

    async def recent_messages(
        self, session_id: uuid.UUID, limit: int
    ) -> list[MessageRecord]:
        if limit <= 0:
            return []
        matching = [m for m in self._messages if m.session_id == session_id]
        return matching[-limit:]

    async def add_attempt(self, session_id: uuid.UUID, new: NewAttempt) -> AttemptRecord:
        record = AttemptRecord(
            id=self._next_attempt_id,
            session_id=session_id,
            item_id=new.item_id,
            level=new.level,
            skill_tag=new.skill_tag,
            attempt_no=new.attempt_no,
            result=new.result,
            counted=new.counted,
            created_at=self._now(),
        )
        self._next_attempt_id += 1
        self._attempts.append(record)
        return record

    async def recent_counted_attempts(
        self, session_id: uuid.UUID, level: int, limit: int
    ) -> list[AttemptRecord]:
        if limit <= 0:
            return []
        matching = [
            a
            for a in self._attempts
            if a.session_id == session_id and a.level == level and a.counted
        ]
        return matching[-limit:]

    async def recent_level_events(
        self, session_id: uuid.UUID, limit: int
    ) -> list[LevelEventRecord]:
        if limit <= 0:
            return []
        matching = [e for e in self._level_events if e.session_id == session_id]
        return matching[-limit:]

    async def persist_turn(self, commit: TurnCommit) -> None:
        record = self._sessions.get(commit.session_id)
        if record is None:
            raise UnknownSessionError(f"unknown session: {commit.session_id}")

        messages_len = len(self._messages)
        attempts_len = len(self._attempts)
        events_len = len(self._level_events)
        snapshot = (
            record,
            messages_len,
            attempts_len,
            events_len,
            self._next_message_id,
            self._next_attempt_id,
            self._next_event_id,
        )
        try:
            self._sessions[commit.session_id] = replace(
                record,
                level=commit.session.level,
                learning_streak=commit.session.learning_streak,
                turns_since_checkin=commit.session.turns_since_checkin,
                turn_count=commit.session.turn_count,
                pending_item_id=commit.session.pending_item_id,
                pending_attempts=commit.session.pending_attempts,
                last_feeling=commit.session.last_feeling,
                last_active_at=commit.session.last_active_at,
            )
            for message in commit.messages:
                await self.add_message(commit.session_id, message)
            for attempt in commit.attempts:
                await self.add_attempt(commit.session_id, attempt)
            for event in commit.level_events:
                self._level_events.append(
                    LevelEventRecord(
                        id=self._next_event_id,
                        session_id=commit.session_id,
                        from_level=event.from_level,
                        to_level=event.to_level,
                        created_at=self._now(),
                    )
                )
                self._next_event_id += 1
        except Exception:
            (
                original,
                messages_len,
                attempts_len,
                events_len,
                self._next_message_id,
                self._next_attempt_id,
                self._next_event_id,
            ) = snapshot
            self._sessions[commit.session_id] = original
            del self._messages[messages_len:]
            del self._attempts[attempts_len:]
            del self._level_events[events_len:]
            raise

    async def get_turn_state(self, session_id: uuid.UUID) -> TurnState | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None

        messages = tuple(
            message for message in self._messages if message.session_id == session_id
        )[-TURN_STATE_MESSAGES:]
        recent_attempts = tuple(
            attempt
            for attempt in self._attempts
            if attempt.session_id == session_id
            and attempt.level == session.level
            and attempt.counted
        )[-TURN_STATE_ATTEMPTS:]

        counts: dict[str, list[int]] = {}
        for attempt in self._attempts:
            if attempt.session_id == session_id and attempt.counted:
                bucket = counts.setdefault(attempt.skill_tag, [0, 0])
                bucket[0] += 1 if attempt.result == "correct" else 0
                bucket[1] += 1
        skill_accuracy = {
            skill: accuracy_ratio(correct, total)
            for skill, (correct, total) in counts.items()
        }

        correct = [
            attempt
            for attempt in self._attempts
            if attempt.session_id == session_id
            and attempt.counted
            and attempt.result == "correct"
        ][-TURN_STATE_WINS:][::-1]
        now = self._now()
        recent_wins = tuple(
            RecentWin(
                item_id=attempt.item_id,
                day_label=relative_day_label(attempt.created_at, now),
            )
            for attempt in correct
        )

        return TurnState(
            session=session,
            messages=messages,
            recent_attempts=recent_attempts,
            skill_accuracy=skill_accuracy,
            recent_wins=recent_wins,
        )
