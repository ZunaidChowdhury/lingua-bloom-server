"""Temporary vertical-slice turn endpoint.

This unauthenticated, database-free route exists only for the first
end-to-end deployment check. It is replaced by TASK-API-07.
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.config import Settings

router = APIRouter()

FALLBACK_REPLY = "I am right here with you!"


class TurnRequest(BaseModel):
    text: str = Field(max_length=200)


class TurnMessage(BaseModel):
    role: Literal["bot"] = "bot"
    content: str


class TurnMeta(BaseModel):
    llm_ms: int
    total_ms: int
    fallback: bool


class TurnResponse(BaseModel):
    messages: list[TurnMessage]
    meta: TurnMeta


@router.post("/v1/chat/turns")
async def create_turn(payload: TurnRequest, request: Request) -> TurnResponse:
    """Return one short bot reply. Replaced by TASK-API-07."""

    settings: Settings = request.app.state.settings
    llm = getattr(request.app.state, "llm", None)

    start = perf_counter()
    llm_start = perf_counter()
    fallback = False
    try:
        if llm is None:
            raise RuntimeError("llm client is not available")
        output = await llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are Bloom, a kind friend for young children. "
                        "Reply as JSON with keys reply (one short sentence), "
                        "suggested_mode (conversation), confidence (0.9), mood (positive)."
                    ),
                },
                {"role": "user", "content": payload.text},
            ]
        )
        content = output.reply
    except Exception:
        content = FALLBACK_REPLY
        fallback = True
    llm_ms = int((perf_counter() - llm_start) * 1000)

    content = content.strip()[: settings.max_reply_chars]
    if not content:
        content = FALLBACK_REPLY
        fallback = True

    total_ms = int((perf_counter() - start) * 1000)
    return TurnResponse(
        messages=[TurnMessage(role="bot", content=content)],
        meta=TurnMeta(llm_ms=llm_ms, total_ms=total_ms, fallback=fallback),
    )
