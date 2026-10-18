"""Progress route: level, window snapshot, and per-skill accuracy (FR-1.8)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_current_session, get_repository
from app.core.errors import NotFoundError
from app.repositories.base import Repository, SessionRecord
from app.services.turn import build_progress_snapshot

router = APIRouter(prefix="/v1", tags=["progress"])


class ProgressResponse(BaseModel):
    level: int
    correct_in_window: int
    window: int
    required: int
    skills: dict[str, float]


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    request: Request,
    session: Annotated[SessionRecord, Depends(get_current_session)],
    repository: Annotated[Repository, Depends(get_repository)],
) -> ProgressResponse:
    """Return the session's progress snapshot and per-skill accuracy summary."""

    state = await repository.get_turn_state(session.id)
    if state is None:
        raise NotFoundError("We could not find that.")
    snapshot = build_progress_snapshot(state, request.app.state.settings)
    return ProgressResponse(
        level=snapshot.level,
        correct_in_window=snapshot.correct_in_window,
        window=snapshot.window,
        required=snapshot.required,
        skills=dict(state.skill_accuracy),
    )
