import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.main import create_app

ALLOWED = "http://localhost:3000"
DISALLOWED = "http://evil.example"


def _settings() -> Settings:
    return Settings(
        groq_api_key="test-key",
        database_url="postgresql://localhost:5432/postgres",
        frontend_origin=ALLOWED,
        _env_file=None,
    )


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def app() -> FastAPI:
    return create_app(_settings())


async def test_health_ok(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_request_id_header_generated(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/health")
    assert response.headers.get("X-Request-ID")


async def test_request_id_header_echoed(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert response.headers["X-Request-ID"] == "trace-123"


async def test_not_found_body_shape(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


async def test_validation_body_shape(app: FastAPI) -> None:
    class Payload(BaseModel):
        name: str

    @app.post("/__validate")
    async def _validate(payload: Payload) -> dict[str, str]:
        return {"echo": payload.name}

    async with _client(app) as client:
        response = await client.post("/__validate", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_cors_allows_frontend_origin(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.get("/health", headers={"Origin": ALLOWED})
    assert response.headers.get("access-control-allow-origin") == ALLOWED


async def test_cors_preflight_rejects_other_origin(app: FastAPI) -> None:
    async with _client(app) as client:
        response = await client.options(
            "/health",
            headers={"Origin": DISALLOWED, "Access-Control-Request-Method": "GET"},
        )
    assert "access-control-allow-origin" not in response.headers


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.LogRecord(
        name="app.request",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    record.request_id = "abc123"
    record.route = "/health"
    record.status = 200
    record.duration_ms = 1.25
    parsed = JsonFormatter().format(record)
    assert '"request_id": "abc123"' in parsed
    assert '"route": "/health"' in parsed
    assert '"status": 200' in parsed
    assert '"duration_ms": 1.25' in parsed
