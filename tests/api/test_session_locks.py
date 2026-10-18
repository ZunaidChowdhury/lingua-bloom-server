"""Tests for the per-session turn lock (ARCH 5 ordering guarantees)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.tokens import generate_token, hash_token
from app.llm import FakeLLM, LLMOutput
from app.main import create_app
from app.repositories.base import NewSession
from app.repositories.memory import InMemoryRepository

GOOD_LLM = LLMOutput(
    reply="Hi friend! Nice to see you.",
    suggested_mode="conversation",
    confidence=0.9,
    mood="positive",
)


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
    llm = FakeLLM(GOOD_LLM)
    llm.set_delay(0.02)
    app.state.llm = llm
    return app


async def _auth_header(app: FastAPI) -> tuple[dict[str, str], object]:
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    token = generate_token()
    now = datetime.now(UTC)
    session = await repo.create_session(
        NewSession(
            token_hash=hash_token(token),
            nickname="Mimi",
            avatar="sprout",
            expires_at=now + timedelta(days=30),
        )
    )
    return {"Authorization": f"Bearer {token}"}, session.id


async def test_concurrent_turns_serialise() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    headers, session_id = await _auth_header(app)

    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.post("/v1/chat/turns", json={"text": "i want to learn"}, headers=headers),
            client.post("/v1/chat/turns", json={"text": "hello again"}, headers=headers),
        )

    assert first.status_code == 200
    assert second.status_code == 200

    session = await repo.get_by_id(session_id)  # type: ignore[arg-type]
    assert session is not None
    assert session.turn_count == 2

    messages = await repo.recent_messages(session_id, limit=10)  # type: ignore[arg-type]
    assert len(messages) == 4
    ids = [message.id for message in messages]
    assert ids == sorted(ids)
    assert len(set(ids)) == 4

    assert len(app.state.session_locks) == 0


async def test_locks_removed_after_use() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
    assert response.status_code == 200
    assert len(app.state.session_locks) == 0
