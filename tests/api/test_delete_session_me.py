"""Tests for DELETE /v1/sessions/me (delete my data)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.tokens import hash_token
from app.main import create_app
from app.repositories.base import NewAttempt
from app.repositories.memory import InMemoryRepository


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


async def test_delete_sessions_me_unauthorized_cases() -> None:
    app = _app()
    async with _client(app) as client:
        res_missing = await client.delete("/v1/sessions/me")
        assert res_missing.status_code == 401
        assert res_missing.json()["error"]["code"] == "unauthorized"

        res_malformed = await client.delete(
            "/v1/sessions/me", headers={"Authorization": "Token invalid"}
        )
        assert res_malformed.status_code == 401

        res_unknown = await client.delete(
            "/v1/sessions/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert res_unknown.status_code == 401


async def test_delete_sessions_me_returns_204_and_removes_all_rows() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]

    async with _client(app) as client:
        create_res = await client.post(
            "/v1/sessions", json={"nickname": "Mia", "avatar": "cloud"}
        )
        assert create_res.status_code == 201
        token = create_res.json()["session_token"]

        session = await repo.get_by_token_hash(hash_token(token))
        assert session is not None

        await repo.add_attempt(
            session.id,
            NewAttempt(
                item_id="l1-colors-banana",
                level=1,
                skill_tag="colors",
                attempt_no=1,
                result="correct",
                counted=True,
            ),
        )
        assert len(await repo.recent_messages(session.id, limit=100)) >= 1
        assert len(await repo.recent_counted_attempts(session.id, 1, limit=100)) == 1

        delete_res = await client.delete(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {token}"}
        )

    assert delete_res.status_code == 204
    assert delete_res.content == b""

    assert await repo.get_by_id(session.id) is None
    assert await repo.get_by_token_hash(hash_token(token)) is None
    assert await repo.recent_messages(session.id, limit=100) == []
    assert await repo.recent_counted_attempts(session.id, 1, limit=100) == []
    assert await repo.recent_level_events(session.id, limit=100) == []


async def test_delete_sessions_me_token_reuse_returns_401() -> None:
    app = _app()
    async with _client(app) as client:
        create_res = await client.post(
            "/v1/sessions", json={"nickname": "Noa", "avatar": "sun"}
        )
        assert create_res.status_code == 201
        token = create_res.json()["session_token"]
        headers = {"Authorization": f"Bearer {token}"}

        first = await client.delete("/v1/sessions/me", headers=headers)
        assert first.status_code == 204

        get_res = await client.get("/v1/sessions/me", headers=headers)
        assert get_res.status_code == 401
        assert get_res.json()["error"]["code"] == "unauthorized"

        second = await client.delete("/v1/sessions/me", headers=headers)
        assert second.status_code == 401
