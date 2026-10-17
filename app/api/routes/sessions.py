"""Session creation and retrieval routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_current_session, get_repository
from app.core.config import Settings
from app.core.errors import InvalidInputError
from app.core.rate_limit import SlidingWindowLimiter, get_client_ip
from app.core.tokens import generate_token, hash_token
from app.domain.curriculum.loader import get_item_by_id
from app.domain.curriculum.models import PublicChoice, PublicItem, public_view
from app.domain.curriculum.selector import shuffled_choices
from app.domain.progression import CountedAttempt, evaluate_progress
from app.domain.safety import sanitize, validate_reply
from app.fallbacks.templates import pick_template
from app.repositories.base import (
    NewMessage,
    NewSession,
    Repository,
    SessionRecord,
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


class ProgressOut(BaseModel):
    level: int
    correct_in_window: int
    window: int
    required: int


class GetSessionResponse(BaseModel):
    session: SessionSummary
    messages: list[MessageOut]
    progress: ProgressOut
    activity: PublicItem | None = None


def build_pending_activity(
    item_id: str | None,
    session_id: uuid.UUID,
) -> PublicItem | None:
    """Build a child-safe public view of the pending item with deterministic choices."""

    if not item_id:
        return None
    item = get_item_by_id(item_id)
    if item is None:
        return None
    if item.choices:
        ordered = shuffled_choices(item, str(session_id))
        return public_view(item).model_copy(
            update={
                "choices": [
                    PublicChoice(id=c.id, label=c.label, emoji=c.emoji)
                    for c in ordered
                ]
            }
        )
    return public_view(item)


@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    repository: Annotated[Repository, Depends(get_repository)],
) -> CreateSessionResponse:
    """Create a new anonymous session and store a template greeting."""

    limiter: SlidingWindowLimiter | None = getattr(
        request.app.state, "rate_session_create", None
    )
    if limiter is not None:
        ip = get_client_ip(request)
        limiter.check(ip)

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
                role=message.role,
                content=message.content,
                mode=message.mode,
            )
        ],
        activity=None,
    )


@router.get("/me", response_model=GetSessionResponse)
async def get_session_me(
    request: Request,
    session: Annotated[SessionRecord, Depends(get_current_session)],
    repository: Annotated[Repository, Depends(get_repository)],
) -> GetSessionResponse:
    """Restore state, recent messages, progress, and any pending activity."""

    settings: Settings = request.app.state.settings

    raw_messages = await repository.recent_messages(session.id, limit=20)
    messages = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            mode=m.mode,
        )
        for m in raw_messages
    ]

    attempts = await repository.recent_counted_attempts(
        session.id, session.level, limit=settings.progress_window
    )
    counted = [
        CountedAttempt(skill=a.skill_tag, correct=(a.result == "correct"))
        for a in attempts
    ]
    progress_decision = evaluate_progress(counted, session.level, settings)
    progress = ProgressOut(
        level=session.level,
        correct_in_window=progress_decision.correct_in_window,
        window=settings.progress_window,
        required=settings.progress_required_correct,
    )

    activity = build_pending_activity(session.pending_item_id, session.id)

    return GetSessionResponse(
        session=SessionSummary(
            level=session.level,
            nickname=session.nickname,
            avatar=session.avatar,
        ),
        messages=messages,
        progress=progress,
        activity=activity,
    )


@router.delete("/me", status_code=204)
async def delete_session_me(
    session: Annotated[SessionRecord, Depends(get_current_session)],
    repository: Annotated[Repository, Depends(get_repository)],
) -> Response:
    """Delete the current session and all dependent rows (delete my data)."""

    await repository.delete_session(session.id)
    return Response(status_code=204)
