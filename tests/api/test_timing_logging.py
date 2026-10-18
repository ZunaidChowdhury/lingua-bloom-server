"""Tests for Server-Timing and privacy-safe turn logging (FR-5.6, ARCH 16)."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
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

SERVER_TIMING_PATTERN = re.compile(r"^llm;dur=\d+, total;dur=\d+$")


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
    app.state.llm = FakeLLM(GOOD_LLM)
    return app


async def _auth_header(app: FastAPI) -> dict[str, str]:
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    token = generate_token()
    now = datetime.now(UTC)
    await repo.create_session(
        NewSession(
            token_hash=hash_token(token),
            nickname="Mimi",
            avatar="sprout",
            expires_at=now + timedelta(days=30),
        )
    )
    return {"Authorization": f"Bearer {token}"}


async def test_server_timing_header() -> None:
    app = _app()
    headers = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
    assert response.status_code == 200
    server_timing = response.headers.get("Server-Timing", "")
    assert SERVER_TIMING_PATTERN.match(server_timing), server_timing
    meta = response.json()["meta"]
    assert f"llm;dur={meta['llm_ms']}" in server_timing
    assert f"total;dur={meta['total_ms']}" in server_timing


async def test_turn_log_line_fields(caplog: pytest.LogCaptureFixture) -> None:
    app = _app()
    headers = await _auth_header(app)
    caplog.set_level(logging.INFO, logger="app.turn")
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
    assert response.status_code == 200

    turn_records = [
        r for r in caplog.records if r.name == "app.turn" and r.getMessage() == "turn"
    ]
    assert len(turn_records) == 1
    record = turn_records[0]
    assert record.request_id == response.headers["X-Request-ID"]  # type: ignore[attr-defined]
    assert record.route == "/v1/chat/turns"  # type: ignore[attr-defined]
    assert record.status == 200  # type: ignore[attr-defined]
    assert isinstance(record.total_ms, int) and record.total_ms >= 0  # type: ignore[attr-defined]
    assert isinstance(record.llm_ms, int) and record.llm_ms >= 0  # type: ignore[attr-defined]
    assert record.mode in ("learning", "conversation", "engagement", "support")  # type: ignore[attr-defined]
    assert record.level == 1  # type: ignore[attr-defined]
    assert record.fallback is False  # type: ignore[attr-defined]


async def test_child_text_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    app = _app()
    headers = await _auth_header(app)
    caplog.set_level(logging.INFO)
    sentinel = "xyzzyplughchildtext"
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": sentinel}, headers=headers
        )
    assert response.status_code == 200
    assert sentinel not in caplog.text
    for record in caplog.records:
        formatted = record.getMessage()
        assert sentinel not in formatted
        for value in record.__dict__.values():
            assert sentinel not in str(value)
