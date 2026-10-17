"""Authentication dependency: success, each rejection case, and log hygiene."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.api.deps import get_current_session
from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.core.tokens import generate_token, hash_token
from app.main import create_app
from app.repositories.base import NewSession, SessionRecord
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


def _app(repository: InMemoryRepository) -> FastAPI:
    app = create_app(_settings())
    app.state.repository = repository

    @app.get("/__me")
    async def _me(
        session: Annotated[SessionRecord, Depends(get_current_session)],
    ) -> dict[str, str]:
        return {"id": str(session.id), "level": str(session.level)}

    return app


async def _seed(
    repository: InMemoryRepository, token: str, *, days: int = 30
) -> SessionRecord:
    return await repository.create_session(
        NewSession(
            token_hash=hash_token(token),
            nickname="Mimi",
            avatar="sprout",
            expires_at=datetime.now(UTC) + timedelta(days=days),
        )
    )


async def test_valid_token_returns_session() -> None:
    repository = InMemoryRepository()
    token = generate_token()
    session = await _seed(repository, token)
    async with _client(_app(repository)) as client:
        response = await client.get("/__me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"id": str(session.id), "level": str(session.level)}


async def test_valid_token_updates_last_active() -> None:
    repository = InMemoryRepository()
    token = generate_token()
    session = await _seed(repository, token)
    async with _client(_app(repository)) as client:
        response = await client.get("/__me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    refreshed = await repository.get_by_id(session.id)
    assert refreshed is not None
    assert refreshed.last_active_at > session.last_active_at


async def test_missing_header_is_401() -> None:
    repository = InMemoryRepository()
    async with _client(_app(repository)) as client:
        response = await client.get("/__me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "abc", "Bearer a b"])
async def test_malformed_header_is_401(header: str) -> None:
    repository = InMemoryRepository()
    async with _client(_app(repository)) as client:
        response = await client.get("/__me", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_unknown_token_is_401() -> None:
    repository = InMemoryRepository()
    async with _client(_app(repository)) as client:
        response = await client.get(
            "/__me", headers={"Authorization": f"Bearer {generate_token()}"}
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_expired_token_is_401_and_deletes_session() -> None:
    repository = InMemoryRepository()
    token = generate_token()
    session = await _seed(repository, token, days=-1)
    async with _client(_app(repository)) as client:
        response = await client.get("/__me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert await repository.get_by_id(session.id) is None


async def test_token_is_not_logged() -> None:
    repository = InMemoryRepository()
    token = generate_token()
    await _seed(repository, token)

    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(self.format(record))

    handler = _Capture()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        async with _client(_app(repository)) as client:
            response = await client.get(
                "/__me", headers={"Authorization": f"Bearer {token}"}
            )
    finally:
        root.removeHandler(handler)

    assert response.status_code == 200
    assert captured
    assert token not in "".join(captured)
