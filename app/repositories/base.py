"""Repository protocols and record types shared by every storage backend.

Services and the API depend on these protocols, never on a concrete backend, so
tests run against the in-memory implementation with no network.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Role = Literal["child", "bot"]
ModeName = Literal["learning", "conversation", "engagement", "support"]
AttemptResultName = Literal["correct", "incorrect", "unsure", "skipped", "revealed"]


class UnknownSessionError(LookupError):
    """Raised when a write targets a session that does not exist."""


@dataclass(frozen=True)
class SessionRecord:
    id: uuid.UUID
    token_hash: str
    nickname: str | None
    avatar: str
    level: int
    learning_streak: int
    turns_since_checkin: int
    turn_count: int
    pending_item_id: str | None
    pending_attempts: int
    last_feeling: str | None
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    id: int
    session_id: uuid.UUID
    role: Role
    content: str
    mode: ModeName | None
    created_at: datetime


@dataclass(frozen=True)
class AttemptRecord:
    id: int
    session_id: uuid.UUID
    item_id: str
    level: int
    skill_tag: str
    attempt_no: int
    result: AttemptResultName
    counted: bool
    created_at: datetime


@dataclass(frozen=True)
class LevelEventRecord:
    id: int
    session_id: uuid.UUID
    from_level: int
    to_level: int
    created_at: datetime


@dataclass(frozen=True)
class NewSession:
    token_hash: str
    nickname: str | None
    avatar: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionUpdate:
    level: int
    learning_streak: int
    turns_since_checkin: int
    turn_count: int
    pending_item_id: str | None
    pending_attempts: int
    last_feeling: str | None
    last_active_at: datetime


@dataclass(frozen=True)
class NewMessage:
    role: Role
    content: str
    mode: ModeName | None = None


@dataclass(frozen=True)
class NewAttempt:
    item_id: str
    level: int
    skill_tag: str
    attempt_no: int
    result: AttemptResultName
    counted: bool


@dataclass(frozen=True)
class NewLevelEvent:
    from_level: int
    to_level: int


@dataclass(frozen=True)
class TurnCommit:
    session_id: uuid.UUID
    session: SessionUpdate
    messages: tuple[NewMessage, ...] = ()
    attempts: tuple[NewAttempt, ...] = ()
    level_events: tuple[NewLevelEvent, ...] = ()


class SessionRepository(Protocol):
    async def create_session(self, new: NewSession) -> SessionRecord: ...

    async def get_by_token_hash(self, token_hash: str) -> SessionRecord | None: ...

    async def get_by_id(self, session_id: uuid.UUID) -> SessionRecord | None: ...

    async def touch_last_active(self, session_id: uuid.UUID, when: datetime) -> None: ...

    async def delete_session(self, session_id: uuid.UUID) -> None: ...

    async def purge_expired(self, now: datetime) -> int: ...

    async def count_expired(self, now: datetime) -> int: ...


class MessageRepository(Protocol):
    async def add_message(
        self, session_id: uuid.UUID, new: NewMessage
    ) -> MessageRecord: ...

    async def recent_messages(
        self, session_id: uuid.UUID, limit: int
    ) -> list[MessageRecord]: ...


class AttemptRepository(Protocol):
    async def add_attempt(
        self, session_id: uuid.UUID, new: NewAttempt
    ) -> AttemptRecord: ...

    async def recent_counted_attempts(
        self, session_id: uuid.UUID, level: int, limit: int
    ) -> list[AttemptRecord]: ...


class LevelEventRepository(Protocol):
    async def recent_level_events(
        self, session_id: uuid.UUID, limit: int
    ) -> list[LevelEventRecord]: ...


class TurnRepository(Protocol):
    async def persist_turn(self, commit: TurnCommit) -> None: ...


class Repository(
    SessionRepository,
    MessageRepository,
    AttemptRepository,
    LevelEventRepository,
    TurnRepository,
    Protocol,
):
    """The full storage contract implemented by every backend."""
