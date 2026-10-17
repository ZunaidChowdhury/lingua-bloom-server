"""API tests for rate limiting (FR-6.5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app
from app.repositories.memory import InMemoryRepository


class MockClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


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


def _app(clock: MockClock | None = None) -> FastAPI:
    app = create_app(_settings(), clock=clock)
    app.state.repository = InMemoryRepository()
    return app


async def test_session_creation_rate_limit_10_per_hour() -> None:
    clock = MockClock(1000.0)
    app = _app(clock)

    async with _client(app) as client:
        headers = {"X-Forwarded-For": "198.51.100.1"}

        # 10 session creations succeed
        for i in range(10):
            res = await client.post(
                "/v1/sessions", json={"nickname": f"User{i}"}, headers=headers
            )
            assert res.status_code == 201, f"Expected 201 on attempt {i+1}, got {res.status_code}"

        # 11th session creation is rate-limited
        blocked = await client.post(
            "/v1/sessions", json={"nickname": "Blocked"}, headers=headers
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["error"]["code"] == "rate_limited"
        assert "Retry-After" in blocked.headers
        retry_after = int(blocked.headers["Retry-After"])
        assert retry_after > 0

        # Different IP can still create a session
        other_ip_res = await client.post(
            "/v1/sessions",
            json={"nickname": "Other"},
            headers={"X-Forwarded-For": "198.51.100.2"},
        )
        assert other_ip_res.status_code == 201

        # Advance clock by 1 hour (3601s)
        clock.advance(3601.0)
        recovered = await client.post(
            "/v1/sessions", json={"nickname": "Recovered"}, headers=headers
        )
        assert recovered.status_code == 201


async def test_ip_rate_limit_120_per_minute() -> None:
    clock = MockClock(1000.0)
    app = _app(clock)

    async with _client(app) as client:
        headers = {"X-Forwarded-For": "198.51.100.10"}

        # Make 120 calls to an endpoint
        for i in range(120):
            res = await client.post(
                "/v1/chat/turns", json={"text": "hello"}, headers=headers
            )
            assert res.status_code == 200, f"Expected 200 on call {i+1}, got {res.status_code}"

        # 121st call is blocked
        blocked = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["error"]["code"] == "rate_limited"
        assert "Retry-After" in blocked.headers


async def test_health_route_exempt_from_rate_limits() -> None:
    clock = MockClock(1000.0)
    app = _app(clock)

    async with _client(app) as client:
        headers = {"X-Forwarded-For": "198.51.100.20"}

        # Health endpoint can be called well over 120 times without rate limiting
        for _ in range(130):
            res = await client.get("/health", headers=headers)
            assert res.status_code == 200
