"""Chat turn route: one authenticated, rate-limited child turn (ARCHITECTURE 8.2)."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

import asyncpg
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_current_session, get_repository
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.locks import SessionLocks
from app.core.rate_limit import SlidingWindowLimiter
from app.domain.curriculum.models import PublicItem
from app.domain.sel import FeelingCheckin
from app.repositories.base import (
    AttemptResultName,
    ModeName,
    Repository,
    SessionRecord,
)
from app.services.turn import (
    ProgressSnapshot,
    TurnCommand,
    TurnMeta,
    TurnOutcome,
    TurnService,
)

logger = logging.getLogger("app.turn")

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class TurnRequest(BaseModel):
    """Exactly one of text, choice_id, or feeling must be present."""

    text: str | None = Field(default=None, max_length=200)
    choice_id: str | None = None
    feeling: str | None = None

    @model_validator(mode="after")
    def exactly_one_input(self) -> TurnRequest:
        provided = (self.text is not None, self.choice_id is not None, self.feeling is not None)
        if sum(provided) != 1:
            raise ValueError("exactly one of text, choice_id, or feeling is required")
        return self


class TurnMessageResponse(BaseModel):
    id: int
    role: Literal["bot", "child"]
    content: str
    mode: ModeName | None = None


class FeedbackOut(BaseModel):
    result: AttemptResultName | None = None
    hint: str | None = None


class TurnResponse(BaseModel):
    messages: list[TurnMessageResponse]
    mode: ModeName
    level: int
    level_up: bool | None
    feedback: FeedbackOut
    activity: PublicItem | FeelingCheckin | None = None
    progress: ProgressSnapshot
    meta: TurnMeta


def _to_command(payload: TurnRequest, request_id: str) -> TurnCommand:
    return TurnCommand(
        text=payload.text or "",
        choice_id=payload.choice_id,
        feeling=payload.feeling,
        request_id=request_id,
    )


async def _map_messages(
    repository: Repository,
    session: SessionRecord,
    outcome: TurnOutcome,
) -> list[TurnMessageResponse]:
    """Attach persisted message ids to the outcome messages by position."""

    recent = await repository.recent_messages(session.id, limit=len(outcome.messages))
    tail = recent[-len(outcome.messages) :] if recent else []
    responses: list[TurnMessageResponse] = []
    for index, message in enumerate(outcome.messages):
        record_id = tail[index].id if index < len(tail) else 0
        responses.append(
            TurnMessageResponse(
                id=record_id,
                role=message.role,
                content=message.content,
                mode=message.mode,
            )
        )
    return responses


@router.post("/turns", response_model=TurnResponse)
async def create_turn(
    payload: TurnRequest,
    request: Request,
    response: Response,
    session: Annotated[SessionRecord, Depends(get_current_session)],
    repository: Annotated[Repository, Depends(get_repository)],
) -> TurnResponse:
    """Run one child turn through the orchestrator and return the chat response."""

    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "rate_turn", None)
    if limiter is not None:
        limiter.check(str(session.id))

    settings: Settings = request.app.state.settings
    service = TurnService(repository, request.app.state.llm, settings)
    locks: SessionLocks = request.app.state.session_locks
    try:
        async with locks.hold(str(session.id)):
            outcome = await service.run(
                session, _to_command(payload, request.state.request_id)
            )
            messages = await _map_messages(repository, session, outcome)
    except (asyncpg.PostgresError, OSError) as exc:
        raise ServiceUnavailableError() from exc

    response.headers["Server-Timing"] = (
        f"llm;dur={outcome.meta.llm_ms}, total;dur={outcome.meta.total_ms}"
    )
    logger.info(
        "turn",
        extra={
            "request_id": request.state.request_id,
            "route": "/v1/chat/turns",
            "status": 200,
            "total_ms": outcome.meta.total_ms,
            "llm_ms": outcome.meta.llm_ms,
            "mode": outcome.mode,
            "level": outcome.level,
            "fallback": outcome.meta.fallback,
        },
    )

    return TurnResponse(
        messages=messages,
        mode=outcome.mode,
        level=outcome.level,
        level_up=True if outcome.level_up else None,
        feedback=FeedbackOut(result=outcome.result, hint=outcome.hint),
        activity=outcome.activity,
        progress=outcome.progress,
        meta=outcome.meta,
    )
