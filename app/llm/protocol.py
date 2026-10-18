"""LLM client protocol."""
from __future__ import annotations

from typing import Any, Protocol

from app.llm.schema import LLMOutput


class LLMClient(Protocol):
    """Typed protocol for LLM clients."""

    async def complete(self, messages: list[dict[str, Any]]) -> LLMOutput:
        """Return a structured LLM output for the given messages."""
        ...
