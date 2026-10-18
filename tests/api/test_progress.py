"""Tests for GET /v1/progress (FR-1.8)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.tokens import generate_token, hash_token
from app.domain.curriculum.loader import get_item_by_id
from app.domain.curriculum.models import Item
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


def _answer_payload(item: Item) -> dict[str, str]:
    """Build the correct reply payload for a served item."""

    if item.choices:
        assert item.answer is not None and item.answer.choice_id is not None
        return {"choice_id": item.answer.choice_id}
    assert item.answer is not None
    return {"text": item.answer.accepted_words[0]}


async def test_requires_auth() -> None:
    app = _app()
    async with _client(app) as client:
        response = await client.get("/v1/progress")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_fresh_session_shape() -> None:
    app = _app()
    headers = await _auth_header(app)
    async with _client(app) as client:
        response = await client.get("/v1/progress", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"level", "correct_in_window", "window", "required", "skills"}
    assert body["level"] == 1
    assert body["correct_in_window"] == 0
    assert body["window"] == 5
    assert body["required"] == 4
    assert body["skills"] == {}


async def test_values_match_turn_response() -> None:
    app = _app()
    headers = await _auth_header(app)
    async with _client(app) as client:
        learning = await client.post(
            "/v1/chat/turns", json={"text": "i want to learn"}, headers=headers
        )
        assert learning.status_code == 200
        activity = learning.json()["activity"]
        assert activity is not None
        item = get_item_by_id(activity["id"])
        assert item is not None

        attempt = await client.post(
            "/v1/chat/turns", json=_answer_payload(item), headers=headers
        )
        assert attempt.status_code == 200
        turn_progress = attempt.json()["progress"]

        progress = await client.get("/v1/progress", headers=headers)
    assert progress.status_code == 200
    body = progress.json()
    assert body["level"] == turn_progress["level"]
    assert body["correct_in_window"] == turn_progress["correct_in_window"]
    assert body["window"] == turn_progress["window"]
    assert body["required"] == turn_progress["required"]


async def test_skills_summary_after_attempts() -> None:
    app = _app()
    headers = await _auth_header(app)
    async with _client(app) as client:
        learning = await client.post(
            "/v1/chat/turns", json={"text": "i want to learn"}, headers=headers
        )
        assert learning.status_code == 200
        activity = learning.json()["activity"]
        assert activity is not None
        item = get_item_by_id(activity["id"])
        assert item is not None

        attempt = await client.post(
            "/v1/chat/turns", json=_answer_payload(item), headers=headers
        )
        assert attempt.status_code == 200

        progress = await client.get("/v1/progress", headers=headers)
    assert progress.status_code == 200
    skills: dict[str, float] = progress.json()["skills"]
    assert item.skill in skills
    assert 0.0 <= skills[item.skill] <= 1.0
    assert skills[item.skill] == 1.0
