"""Status-code matrix tests: body shape and absence of internal details (ARCH 8.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import ForbiddenError
from app.core.rate_limit import SlidingWindowLimiter
from app.core.tokens import generate_token, hash_token
from app.domain.curriculum.loader import get_item_by_id
from app.llm import FakeLLM, LLMOutput
from app.main import create_app
from app.repositories.base import NewSession, SessionRecord, SessionUpdate, TurnCommit
from app.repositories.memory import InMemoryRepository

GOOD_LLM = LLMOutput(
    reply="Hi friend! Nice to see you.",
    suggested_mode="conversation",
    confidence=0.9,
    mood="positive",
)

LEAK_MARKERS = (
    "traceback",
    "asyncpg",
    'file "',
    "exception",
    "conn lost",
    "/app/",
    "stack",
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


def _app(llm: FakeLLM | None = None) -> FastAPI:
    app = create_app(_settings())
    app.state.repository = InMemoryRepository()
    app.state.llm = llm or FakeLLM(GOOD_LLM)
    return app


async def _auth_header(app: FastAPI, **updates: object) -> dict[str, str]:
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
    if updates:
        await repo.persist_turn(
            TurnCommit(
                session_id=session.id,
                session=SessionUpdate(
                    level=1,
                    learning_streak=0,
                    turns_since_checkin=0,
                    turn_count=0,
                    pending_item_id=updates.get("pending_item_id"),  # type: ignore[arg-type]
                    pending_attempts=updates.get("pending_attempts", 0),  # type: ignore[arg-type]
                    last_feeling=None,
                    last_active_at=now,
                ),
            )
        )
    return {"Authorization": f"Bearer {token}"}


def _assert_error_body(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    message = body["error"]["message"].lower()
    for marker in LEAK_MARKERS:
        assert marker not in message, f"leaked {marker!r} in {message!r}"


async def test_401_unauthorized() -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "hi"})
    _assert_error_body(response, 401, "unauthorized")


async def test_403_forbidden() -> None:
    app = _app()

    @app.get("/_test/forbidden")
    async def _forbidden() -> None:
        raise ForbiddenError()

    async with _client(app) as client:
        response = await client.get("/_test/forbidden")
    _assert_error_body(response, 403, "forbidden")


async def test_404_not_found() -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.get("/v1/does-not-exist")
    _assert_error_body(response, 404, "not_found")


async def test_422_invalid_choice() -> None:
    app = _app()
    item = get_item_by_id("l1-objects-clock")
    assert item is not None
    headers = await _auth_header(app, pending_item_id=item.id, pending_attempts=0)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"choice_id": "zzz"}, headers=headers
        )
    _assert_error_body(response, 422, "invalid_input")


async def test_429_rate_limited() -> None:
    app = _app()
    app.state.rate_turn = SlidingWindowLimiter(1, 60)
    headers = await _auth_header(app)
    async with _client(app) as client:
        first = await client.post("/v1/chat/turns", json={"text": "hi"}, headers=headers)
        assert first.status_code == 200
        second = await client.post("/v1/chat/turns", json={"text": "hi"}, headers=headers)
    _assert_error_body(second, 429, "rate_limited")
    assert "Retry-After" in second.headers


class _BrokenRepository(InMemoryRepository):
    async def get_by_token_hash(self, token_hash: str) -> SessionRecord:
        raise asyncpg.PostgresError("conn lost")


async def test_503_database_outage() -> None:
    app = _app()
    app.state.repository = _BrokenRepository()
    token = generate_token()
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns",
            json={"text": "hi"},
            headers={"Authorization": f"Bearer {token}"},
        )
    _assert_error_body(response, 503, "service_unavailable")


async def test_llm_failure_returns_200_fallback() -> None:
    app = _app(FakeLLM(RuntimeError("boom")))
    headers = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
    assert response.status_code == 200
    assert response.json()["meta"]["fallback"] is True
