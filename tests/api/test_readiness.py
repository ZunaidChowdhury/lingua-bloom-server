"""Readiness route and pool lifecycle tests (no real database needed)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.llm.client import GroqClient
from app.main import create_app

ALLOWED = "http://localhost:3000"
UNREACHABLE_DSN = "postgresql://invalid:invalid@127.0.0.1:1/invalid"


@pytest.fixture(autouse=True)
def _no_llm_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(self: object) -> None:
        return None

    monkeypatch.setattr(GroqClient, "warmup", _noop)


class FakePool:
    def __init__(self, *, value: int = 1, error: Exception | None = None) -> None:
        self._value = value
        self._error = error
        self.closed = False

    async def fetchval(self, query: str, *args: Any) -> int:
        if self._error is not None:
            raise self._error
        return self._value

    async def close(self) -> None:
        self.closed = True


def _settings(database_url: str = "postgresql://localhost:5432/postgres") -> Settings:
    return Settings(
        groq_api_key="test-key",
        database_url=database_url,
        frontend_origin=ALLOWED,
        _env_file=None,
    )


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@asynccontextmanager
async def _client_with_lifespan(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app), _client(app) as client:
        yield client


async def test_ready_returns_ready_when_pool_responds() -> None:
    app = create_app(_settings())
    app.state.pool = FakePool(value=1)

    async with _client(app) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_returns_503_when_query_fails() -> None:
    app = create_app(_settings())
    app.state.pool = FakePool(error=OSError("database is down"))

    async with _client(app) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


async def test_lifespan_creates_pool_with_expected_options_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    pool = FakePool()

    async def fake_create_pool(**kwargs: Any) -> FakePool:
        captured.update(kwargs)
        return pool

    monkeypatch.setattr("app.main.asyncpg.create_pool", fake_create_pool)
    settings = _settings()
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        assert app.state.pool is pool

    assert pool.closed
    assert captured["dsn"] == settings.database_url
    assert captured["min_size"] == 1
    assert captured["max_size"] == 5
    assert captured["statement_cache_size"] == 0
    assert captured["command_timeout"] == settings.db_command_timeout_s


async def test_lifespan_tolerates_unreachable_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_pool(**kwargs: Any) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr("app.main.asyncpg.create_pool", fake_create_pool)
    app = create_app(_settings())

    async with _client_with_lifespan(app) as client:
        ready = await client.get("/health/ready")
        health = await client.get("/health")

    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "service_unavailable"
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


async def test_ready_returns_503_for_invalid_dsn() -> None:
    app = create_app(_settings(database_url=UNREACHABLE_DSN))

    async with _client_with_lifespan(app) as client:
        ready = await client.get("/health/ready")
        health = await client.get("/health")

    assert ready.status_code == 503
    assert health.status_code == 200
