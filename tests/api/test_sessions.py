"""Tests for POST /v1/sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.tokens import hash_token
from app.domain.safety import validate_reply
from app.main import create_app
from app.repositories.memory import InMemoryRepository

AVATARS = ["sprout", "sun", "cloud", "butterfly"]


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


def _app() -> FastAPI:
    app = create_app(_settings())
    app.state.repository = InMemoryRepository()
    return app


async def test_create_session_happy_path() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    payload = {"nickname": "Mimi", "avatar": "sprout"}
    async with _client(app) as client:
        response = await client.post("/v1/sessions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert "session_token" in body
    assert len(body["session_token"]) >= 32
    assert body["session"] == {"level": 1, "nickname": "Mimi", "avatar": "sprout"}
    assert body["activity"] is None
    assert isinstance(body["messages"], list) and len(body["messages"]) == 1
    msg = body["messages"][0]
    assert msg["role"] == "bot"
    assert msg["mode"] == "conversation"
    assert isinstance(msg["content"], str) and msg["content"]
    assert msg["id"] == 1
    assert validate_reply(msg["content"], 1) == (True, [])
    token_hash = hash_token(body["session_token"])
    found = await repo.get_by_token_hash(token_hash)
    assert found is not None
    assert found.token_hash == token_hash
    assert body["session_token"] != token_hash


async def test_nickname_optional() -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.post("/v1/sessions", json={})
    assert response.status_code == 201
    body = response.json()
    assert body["session"]["nickname"] is None


@pytest.mark.parametrize("avatar", AVATARS)
async def test_avatar_enum(avatar: str) -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.post("/v1/sessions", json={"avatar": avatar})
    assert response.status_code == 201


async def test_nickname_length_validated() -> None:
    app = _app()
    async with _client(app) as client:
        too_long = "x" * 21
        response = await client.post("/v1/sessions", json={"nickname": too_long})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_nickname_with_pii_rejected() -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.post(
            "/v1/sessions", json={"nickname": "mimi@example.com"}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_nickname_whitespace_collapsed_to_none() -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.post("/v1/sessions", json={"nickname": "   "})
    assert response.status_code == 201
    assert response.json()["session"]["nickname"] is None
