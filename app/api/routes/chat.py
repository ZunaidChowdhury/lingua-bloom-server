"""Chat turn route: one authenticated, rate-limited child turn (ARCHITECTURE 8.2)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_current_session, get_repository
from app.core.config import Settings
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


def _to_command(payload: TurnRequest) -> TurnCommand:
    return TurnCommand(
        text=payload.text or "",
        choice_id=payload.choice_id,
        feeling=payload.feeling,
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
    session: Annotated[SessionRecord, Depends(get_current_session)],
    repository: Annotated[Repository, Depends(get_repository)],
) -> TurnResponse:
    """Run one child turn through the orchestrator and return the chat response."""

    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "rate_turn", None)
    if limiter is not None:
        limiter.check(str(session.id))

    settings: Settings = request.app.state.settings
    service = TurnService(repository, request.app.state.llm, settings)
    outcome = await service.run(session, _to_command(payload))

    messages = await _map_messages(repository, session, outcome)
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
