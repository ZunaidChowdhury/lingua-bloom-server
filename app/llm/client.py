"""Minimal asynchronous Groq wrapper for the temporary slice endpoint."""

from __future__ import annotations

import asyncio

from groq import AsyncGroq
from groq.types.chat import ChatCompletionMessageParam

_SYSTEM_PROMPT = (
    "You are Bloom, a kind helper for children under seven. "
    "Reply with one very short, cheerful sentence."
)


class GroqClient:
    """Wrap a single long-lived AsyncGroq instance."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float,
        max_tokens: int = 512,
    ) -> None:
        self._client = AsyncGroq(api_key=api_key, max_retries=0)
        self._model = model
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens

    async def reply(self, text: str) -> str:
        """Return a short reply, raising on timeout or provider error."""

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        completion = await asyncio.wait_for(
            self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=self._max_tokens,
                temperature=0.7,
                reasoning_effort="low",
            ),
            timeout=self._timeout_s,
        )
        content = completion.choices[0].message.content or ""
        return content.strip()

    async def close(self) -> None:
        await self._client.close()
