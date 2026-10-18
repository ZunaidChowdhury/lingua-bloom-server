"""LLM output schema definitions."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMOutput(BaseModel):
    """Structured output from the LLM for each turn."""

    reply: str = Field(max_length=240)
    suggested_mode: Literal["learning", "conversation", "engagement", "support"]
    confidence: float = Field(ge=0.0, le=1.0)
    mood: Literal["positive", "neutral", "low", "unsure"]
