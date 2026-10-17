from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.routes.slice import FALLBACK_REPLY
from app.core.config import Settings
from app.main import create_app


class FakeLLM:
    def __init__(self, result: str | Exception) -> None:
        self._result = result

    async def reply(self, text: str) -> str:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _settings() -> Settings:
    return Settings(
        groq_api_key="test-key",
        database_url="postgresql://localhost:5432/postgres",
        _env_file=None,
    )


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _app_with(llm: FakeLLM) -> FastAPI:
    app = create_app(_settings())
    app.state.llm = llm
    return app


async def test_returns_bot_message_and_meta() -> None:
    app = _app_with(FakeLLM("Hi friend!"))
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["messages"] == [{"role": "bot", "content": "Hi friend!"}]
    assert isinstance(body["meta"]["llm_ms"], int)
    assert isinstance(body["meta"]["total_ms"], int)
    assert body["meta"]["fallback"] is False


async def test_reply_is_truncated_to_max_chars() -> None:
    app = _app_with(FakeLLM("a" * 500))
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "hello"})
    content = response.json()["messages"][0]["content"]
    assert len(content) <= 240


async def test_groq_error_returns_fallback() -> None:
    app = _app_with(FakeLLM(RuntimeError("boom")))
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["messages"][0]["content"] == FALLBACK_REPLY
    assert body["meta"]["fallback"] is True


async def test_timeout_returns_fallback() -> None:
    app = _app_with(FakeLLM(TimeoutError("slow")))
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["messages"][0]["content"] == FALLBACK_REPLY
    assert body["meta"]["fallback"] is True


async def test_text_over_limit_is_422() -> None:
    app = _app_with(FakeLLM("ok"))
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "x" * 201})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
