"""Session creation and retrieval routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_repository
from app.core.config import Settings
from app.core.errors import InvalidInputError
from app.core.tokens import generate_token, hash_token
from app.domain.safety import sanitize, validate_reply
from app.fallbacks.templates import pick_template
from app.repositories.base import (
    NewMessage,
    NewSession,
    Repository,
)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

ModeName = Literal["learning", "conversation", "engagement", "support"]


class CreateSessionRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=20)
    avatar: Literal["sprout", "sun", "cloud", "butterfly"] = "sprout"


class SessionSummary(BaseModel):
    level: int
    nickname: str | None
    avatar: str


class MessageOut(BaseModel):
    id: int
    role: Literal["bot", "child"]
    content: str
    mode: ModeName | None = None


class CreateSessionResponse(BaseModel):
    session_token: str
    session: SessionSummary
    messages: list[MessageOut]
    activity: None


@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
) -> CreateSessionResponse:
    """Create a new anonymous session and store a template greeting."""

    sanitized_nickname, flags = sanitize(payload.nickname or "")
    if flags.pii:
        raise InvalidInputError("The nickname is not allowed.")
    nickname = sanitized_nickname or None

    settings: Settings = request.app.state.settings
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.session_ttl_days)

    raw_token = generate_token()
    token_hash = hash_token(raw_token)

    session = await repository.create_session(
        NewSession(
            token_hash=token_hash,
            nickname=nickname,
            avatar=payload.avatar,
            expires_at=expires_at,
        )
    )

    seed = session.id.int
    greeting = pick_template("conversation", session.level, "greeting", seed, nickname)

    ok, _ = validate_reply(greeting, session.level)
    if not ok:
        greeting = pick_template("conversation", session.level, "generic", seed, nickname)

    message = await repository.add_message(
        session.id,
        NewMessage(role="bot", content=greeting, mode="conversation"),
    )

    return CreateSessionResponse(
        session_token=raw_token,
        session=SessionSummary(
            level=session.level,
            nickname=session.nickname,
            avatar=session.avatar,
        ),
        messages=[
            MessageOut(
                id=message.id,
                role="bot",
                content=message.content,
                mode=message.mode,
            )
        ],
        activity=None,
    )
