"""Fake LLM implementation for testing."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.llm.schema import LLMOutput


class FakeLLM:
    """Fake LLM that can be configured to return scripted behaviours."""

    def __init__(
        self,
        result: LLMOutput | dict[str, Any] | str | Exception | None = None,
    ) -> None:
        self._result = result
        self._delay: float = 0.0

    def set_delay(self, delay_s: float) -> None:
        """Simulate a processing delay."""
        self._delay = delay_s

    async def complete(self, messages: list[dict[str, Any]]) -> LLMOutput:
        """Return a scripted output, simulating configured behaviours."""
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        if isinstance(self._result, Exception):
            raise self._result

        if isinstance(self._result, LLMOutput):
            return self._result

        if isinstance(self._result, dict):
            return LLMOutput(**self._result)

        if isinstance(self._result, str):
            # Try to parse as JSON, otherwise raise as invalid JSON
            try:
                data = json.loads(self._result)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON from LLM") from exc
            return LLMOutput(**data)

        # Default valid output
        return LLMOutput(
            reply="Hi friend!",
            suggested_mode="conversation",
            confidence=0.9,
            mood="positive",
        )

    async def reply(self, text: str) -> str:
        """Legacy method for compatibility with existing code."""
        output = await self.complete([])
        return output.reply
