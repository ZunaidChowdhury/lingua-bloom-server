"""Unit tests for the production Groq client (no network: AsyncGroq is faked)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import groq
import httpx
import pytest

from app.llm.client import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, GroqClient, LLMUnavailable
from app.llm.schema import LLMOutput

API_KEY = "gsk-secret-key-never-log-me"


def _completion(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


VALID_CONTENT = (
    '{"reply": "Hi friend!", "suggested_mode": "conversation",'
    ' "confidence": 0.9, "mood": "positive"}'
)


class FakeCompletions:
    def __init__(self, behaviour: Any) -> None:
        self._behaviour = behaviour
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if isinstance(self._behaviour, Exception):
            raise self._behaviour
        if callable(self._behaviour):
            return await self._behaviour(kwargs)
        if isinstance(self._behaviour, float):
            await asyncio.sleep(self._behaviour)
            return _completion(VALID_CONTENT)
        return self._behaviour


class FakeAsyncGroq:
    def __init__(self, behaviour: Any) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(behaviour))
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _client(
    monkeypatch: pytest.MonkeyPatch, behaviour: Any, timeout_s: float = 1.5
) -> tuple[GroqClient, FakeCompletions]:
    fake = FakeAsyncGroq(behaviour)
    monkeypatch.setattr("app.llm.client.AsyncGroq", lambda **kwargs: fake)
    client = GroqClient(api_key=API_KEY, model="test-model", timeout_s=timeout_s)
    return client, fake.chat.completions


_MESSAGES = [{"role": "user", "content": "hello"}]


async def test_valid_json_returns_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, _completion(VALID_CONTENT))
    output = await client.complete(_MESSAGES)
    assert isinstance(output, LLMOutput)
    assert output.reply == "Hi friend!"
    assert output.suggested_mode == "conversation"
    assert output.confidence == 0.9
    assert output.mood == "positive"


async def test_request_uses_json_mode_temperature_and_token_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client(monkeypatch, _completion(VALID_CONTENT))
    await client.complete(_MESSAGES)
    call = completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["temperature"] == DEFAULT_TEMPERATURE == 0.6
    assert call["max_tokens"] == DEFAULT_MAX_TOKENS == 200
    assert call["model"] == "test-model"


async def test_timeout_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, 5.0, timeout_s=0.01)
    with pytest.raises(LLMUnavailable, match="llm timeout"):
        await client.complete(_MESSAGES)


async def test_rate_limit_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.groq.com")
    response = httpx.Response(429, request=request)
    error = groq.RateLimitError("rate limited", response=response, body=None)
    client, _ = _client(monkeypatch, error)
    with pytest.raises(LLMUnavailable, match="llm request failed"):
        await client.complete(_MESSAGES)


async def test_http_error_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.groq.com")
    response = httpx.Response(500, request=request)
    error = groq.APIStatusError("server error", response=response, body=None)
    client, _ = _client(monkeypatch, error)
    with pytest.raises(LLMUnavailable, match="llm request failed"):
        await client.complete(_MESSAGES)


async def test_connection_error_raises_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.groq.com")
    error = groq.APIConnectionError(request=request)
    client, _ = _client(monkeypatch, error)
    with pytest.raises(LLMUnavailable, match="llm request failed"):
        await client.complete(_MESSAGES)


async def test_invalid_json_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, _completion("not json {"))
    with pytest.raises(LLMUnavailable, match="llm output was not valid"):
        await client.complete(_MESSAGES)


async def test_schema_failure_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, _completion('{"reply": "hi"}'))
    with pytest.raises(LLMUnavailable, match="llm output was not valid"):
        await client.complete(_MESSAGES)


async def test_empty_content_raises_llm_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, _completion(None))
    with pytest.raises(LLMUnavailable, match="llm output was not valid"):
        await client.complete(_MESSAGES)


async def test_warmup_sends_tiny_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client, completions = _client(monkeypatch, _completion(VALID_CONTENT))
    await client.warmup()
    assert len(completions.calls) == 1
    assert completions.calls[0]["max_tokens"] == 1


async def test_warmup_failure_only_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = _client(monkeypatch, TimeoutError("slow"))
    with caplog.at_level(logging.WARNING, logger="app.llm"):
        await client.warmup()
    assert any("llm_warmup_failed" in record.message for record in caplog.records)


async def test_api_key_is_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    request = httpx.Request("POST", "https://api.groq.com")
    response = httpx.Response(500, request=request)
    error = groq.APIStatusError("server error", response=response, body=None)
    client, _ = _client(monkeypatch, error)
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        with pytest.raises(LLMUnavailable):
            await client.complete(_MESSAGES)
        await client.warmup()
    for record in caplog.records:
        assert API_KEY not in record.message
        assert API_KEY not in record.args.__repr__()


async def test_close_closes_underlying_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAsyncGroq(_completion(VALID_CONTENT))
    monkeypatch.setattr("app.llm.client.AsyncGroq", lambda **kwargs: fake)
    client = GroqClient(api_key=API_KEY, model="test-model", timeout_s=1.5)
    await client.close()
    assert fake.closed is True
