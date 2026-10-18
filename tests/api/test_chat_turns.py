"""Tests for POST /v1/chat/turns (ARCHITECTURE 8.2)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.tokens import generate_token, hash_token
from app.domain.curriculum.loader import get_item_by_id
from app.llm import FakeLLM, LLMOutput
from app.main import create_app
from app.repositories.base import NewSession, SessionUpdate, TurnCommit
from app.repositories.memory import InMemoryRepository

GOOD_LLM = LLMOutput(
    reply="Hi friend! Nice to see you.",
    suggested_mode="conversation",
    confidence=0.9,
    mood="positive",
)

FORBIDDEN_KEYS = {"answer", "accepted_words", "rubric", "reveal", "choice_id"}


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


def _app(llm: Any = None) -> FastAPI:
    app = create_app(_settings())
    app.state.repository = InMemoryRepository()
    app.state.llm = llm or FakeLLM(GOOD_LLM)
    return app


async def _auth_header(app: FastAPI, **updates: Any) -> tuple[dict[str, str], uuid.UUID]:
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
                    level=updates.get("level", 1),
                    learning_streak=updates.get("learning_streak", 0),
                    turns_since_checkin=updates.get("turns_since_checkin", 0),
                    turn_count=updates.get("turn_count", 0),
                    pending_item_id=updates.get("pending_item_id"),
                    pending_attempts=updates.get("pending_attempts", 0),
                    last_feeling=updates.get("last_feeling"),
                    last_active_at=now,
                ),
            )
        )
    return {"Authorization": f"Bearer {token}"}, session.id


def _walk_keys(obj: Any, path: str = "$") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key not in FORBIDDEN_KEYS, f"forbidden key {key!r} at {path}"
            _walk_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _walk_keys(value, f"{path}[{index}]")


PROSE_KEYS = {"content", "prompt", "hint", "label", "result"}


def _collect_prose(obj: Any) -> str:
    """Collect child-visible prose strings; ids/slugs are not scanned."""

    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PROSE_KEYS and isinstance(value, str):
                    parts.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(obj)
    return " ".join(parts).lower()


async def test_zero_inputs_rejected() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_two_inputs_rejected() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hi", "feeling": "sad"}, headers=headers
        )
    assert response.status_code == 422


async def test_over_length_text_rejected() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "a" * 201}, headers=headers
        )
    assert response.status_code == 422


async def test_requires_auth() -> None:
    """The old unauthenticated slice endpoint is gone: no token means 401."""

    app = _app()
    async with _client(app) as client:
        response = await client.post("/v1/chat/turns", json={"text": "hello"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_happy_path_shape() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "messages",
        "mode",
        "level",
        "level_up",
        "feedback",
        "activity",
        "progress",
        "meta",
    }
    assert body["level_up"] is None
    assert set(body["feedback"]) == {"result", "hint"}
    assert set(body["meta"]) == {"fallback", "llm_ms", "total_ms", "request_id"}
    assert isinstance(body["meta"]["request_id"], str) and body["meta"]["request_id"]
    assert set(body["progress"]) == {"level", "correct_in_window", "window", "required"}
    message = body["messages"][-1]
    assert set(message) == {"id", "role", "content", "mode"}
    assert isinstance(message["id"], int) and message["id"] > 0
    assert message["role"] == "bot"
    assert body["mode"] in ("learning", "conversation", "engagement", "support")


async def test_feeling_input() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"feeling": "sad"}, headers=headers
        )
    assert response.status_code == 200
    assert response.json()["mode"] == "conversation"


async def test_choice_input() -> None:
    app = _app()
    item = get_item_by_id("l1-objects-clock")
    assert item is not None and item.choices
    headers, _ = await _auth_header(
        app, pending_item_id=item.id, pending_attempts=0
    )
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns",
            json={"choice_id": item.choices[0].id},
            headers=headers,
        )
    assert response.status_code == 200


async def test_rate_limit_per_session() -> None:
    app = _app()
    app.state.rate_turn = SlidingWindowLimiter(2, 60)
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        for _ in range(2):
            first = await client.post(
                "/v1/chat/turns", json={"text": "hello"}, headers=headers
            )
            assert first.status_code == 200
        third = await client.post("/v1/chat/turns", json={"text": "hello"}, headers=headers)
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in third.headers


async def test_no_answer_key_exposed() -> None:
    app = _app()
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "i want to learn"}, headers=headers
        )
    assert response.status_code == 200
    body = response.json()

    _walk_keys(body)

    activity = body["activity"]
    assert activity is not None and activity["type"] != "feeling_checkin"
    item = get_item_by_id(activity["id"])
    assert item is not None
    if item.type != "choice" and item.answer is not None:
        prose = _collect_prose(body)
        for word in item.answer.accepted_words:
            assert word.lower() not in prose


@pytest.mark.parametrize(
    "failing_llm",
    [
        FakeLLM(TimeoutError("timeout")),
        FakeLLM("{not valid json"),
        FakeLLM(
            LLMOutput(
                reply="You are bad. Visit http://evil.com now.",
                suggested_mode="conversation",
                confidence=0.9,
                mood="neutral",
            )
        ),
    ],
    ids=["timeout", "invalid_json", "unsafe_output"],
)
async def test_llm_failures_return_http_200_with_fallback_true(failing_llm: FakeLLM) -> None:
    app = _app(llm=failing_llm)
    headers, _ = await _auth_header(app)
    async with _client(app) as client:
        response = await client.post(
            "/v1/chat/turns", json={"text": "hello"}, headers=headers
        )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["fallback"] is True
    assert len(body["messages"]) > 0
    bot_reply = body["messages"][-1]["content"]
    assert bot_reply
    assert "bad" not in bot_reply
    assert "http" not in bot_reply
