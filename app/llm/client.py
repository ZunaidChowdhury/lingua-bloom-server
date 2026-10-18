"""Production Groq client: one structured call per turn (FR-5.2, FR-5.4)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, cast

import groq
from groq import AsyncGroq
from groq.types.chat import ChatCompletionMessageParam
from pydantic import ValidationError

from app.llm.schema import LLMOutput

logger = logging.getLogger("app.llm")

DEFAULT_TEMPERATURE = 0.6
DEFAULT_MAX_TOKENS = 600


class LLMUnavailable(Exception):
    """The LLM could not produce a valid output; callers fall back to a template."""

    def __init__(
        self,
        message: str = "llm unavailable",
        reason: str = "api_error",
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.detail = detail


class GroqClient:
    """Single long-lived AsyncGroq instance implementing the LLMClient protocol."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> None:
        http_client: Any = None
        if os.name == "nt":
            import ssl

            import httpx

            ctx = ssl.create_default_context()
            pems = "".join(ssl.DER_cert_to_PEM_cert(c[0]) for c in ssl.enum_certificates("ROOT"))
            if pems:
                ctx.load_verify_locations(cadata=pems)
            http_client = httpx.AsyncClient(verify=ctx)
        self._client = AsyncGroq(api_key=api_key, max_retries=0, http_client=http_client)
        self._model = model
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def complete(self, messages: list[dict[str, Any]]) -> LLMOutput:
        """Return a schema-valid LLMOutput or raise LLMUnavailable."""

        try:
            completion = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=cast("list[ChatCompletionMessageParam]", messages),
                    response_format={"type": "json_object"},
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                ),
                timeout=self._timeout_s,
            )
        except TimeoutError as exc:
            logger.warning("llm_timeout model=%s", self._model)
            raise LLMUnavailable("llm timeout", reason="timeout") from exc
        except groq.APIError as exc:
            logger.warning("llm_api_error model=%s type=%s", self._model, type(exc).__name__)
            raise LLMUnavailable(
                "llm request failed", reason="api_error", detail=type(exc).__name__
            ) from exc
        except Exception as exc:
            logger.warning("llm_error model=%s type=%s", self._model, type(exc).__name__)
            raise LLMUnavailable(
                "llm request failed", reason="api_error", detail=type(exc).__name__
            ) from exc

        content = completion.choices[0].message.content or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("llm_invalid_output type=JSONDecodeError")
            raise LLMUnavailable(
                "llm output was not valid", reason="invalid_json", detail="JSONDecodeError"
            ) from exc

        try:
            return LLMOutput(**data)
        except (ValidationError, TypeError) as exc:
            logger.warning("llm_invalid_output type=%s", type(exc).__name__)
            raise LLMUnavailable(
                "llm output was not valid", reason="schema_mismatch", detail=type(exc).__name__
            ) from exc

    async def warmup(self) -> None:
        """Send one tiny request so the first real turn reuses a warm connection."""

        try:
            await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                ),
                timeout=self._timeout_s,
            )
        except Exception as exc:
            logger.warning("llm_warmup_failed type=%s", type(exc).__name__)

    async def close(self) -> None:
        await self._client.close()
