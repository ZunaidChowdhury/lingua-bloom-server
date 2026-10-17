"""Tests for GET /v1/sessions/me."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.core.tokens import generate_token, hash_token
from app.main import create_app
from app.repositories.base import NewAttempt, NewMessage, NewSession, SessionUpdate, TurnCommit
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


def _walk_keys(data: Any) -> list[str]:
    """Recursively collect every key present in a JSON-like data structure."""

    keys: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            keys.append(str(k))
            keys.extend(_walk_keys(v))
    elif isinstance(data, list):
        for item in data:
            keys.extend(_walk_keys(item))
    return keys


async def test_get_sessions_me_unauthorized_cases() -> None:
    app = _app()
    async with _client(app) as client:
        # Missing header
        res_missing = await client.get("/v1/sessions/me")
        assert res_missing.status_code == 401
        assert res_missing.json()["error"]["code"] == "unauthorized"

        # Malformed header
        res_malformed = await client.get(
            "/v1/sessions/me", headers={"Authorization": "Token invalid"}
        )
        assert res_malformed.status_code == 401

        # Unknown token
        res_unknown = await client.get(
            "/v1/sessions/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert res_unknown.status_code == 401


async def test_get_sessions_me_expired_token_rejected() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    past = datetime.now(UTC) - timedelta(days=1)

    await repo.create_session(
        NewSession(
            token_hash=token_hash,
            nickname="Old",
            avatar="sprout",
            expires_at=past,
        )
    )

    async with _client(app) as client:
        res = await client.get(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {raw_token}"}
        )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


async def test_get_sessions_me_happy_path_restores_state() -> None:
    app = _app()
    async with _client(app) as client:
        # 1. Create a session
        create_res = await client.post(
            "/v1/sessions", json={"nickname": "Leo", "avatar": "sun"}
        )
        assert create_res.status_code == 201
        token = create_res.json()["session_token"]

        # 2. Call GET /v1/sessions/me
        me_res = await client.get(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {token}"}
        )

    assert me_res.status_code == 200
    body = me_res.json()
    assert body["session"] == {"level": 1, "nickname": "Leo", "avatar": "sun"}
    assert body["activity"] is None
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "bot"
    assert body["messages"][0]["mode"] == "conversation"
    assert body["progress"] == {
        "level": 1,
        "correct_in_window": 0,
        "window": 5,
        "required": 4,
    }


async def test_get_sessions_me_limits_to_last_20_messages_chronological() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)

    session = await repo.create_session(
        NewSession(
            token_hash=token_hash,
            nickname="Test",
            avatar="cloud",
            expires_at=now + timedelta(days=30),
        )
    )

    # Insert 25 messages
    for i in range(1, 26):
        role = "child" if i % 2 == 1 else "bot"
        mode = "learning" if role == "bot" else None
        await repo.add_message(
            session.id,
            NewMessage(role=role, content=f"Message {i}", mode=mode),  # type: ignore[arg-type]
        )

    async with _client(app) as client:
        res = await client.get(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {raw_token}"}
        )

    assert res.status_code == 200
    messages = res.json()["messages"]
    assert len(messages) == 20
    # Must be the last 20 messages (IDs 6 through 25) in ascending order
    assert messages[0]["content"] == "Message 6"
    assert messages[-1]["content"] == "Message 25"
    assert [m["id"] for m in messages] == sorted(m["id"] for m in messages)


async def test_get_sessions_me_pending_activity_deterministic_and_no_secret_keys() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)

    session = await repo.create_session(
        NewSession(
            token_hash=token_hash,
            nickname="Kira",
            avatar="butterfly",
            expires_at=now + timedelta(days=30),
        )
    )

    # Set pending item to an existing curriculum choice item
    await repo.persist_turn(
        TurnCommit(
            session_id=session.id,
            session=SessionUpdate(
                level=session.level,
                learning_streak=session.learning_streak,
                turns_since_checkin=session.turns_since_checkin,
                turn_count=session.turn_count,
                pending_item_id="l1-colors-banana",
                pending_attempts=0,
                last_feeling=session.last_feeling,
                last_active_at=now,
            ),
        )
    )

    async with _client(app) as client:
        res1 = await client.get(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {raw_token}"}
        )
        res2 = await client.get(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {raw_token}"}
        )

    assert res1.status_code == 200
    assert res2.status_code == 200
    data1 = res1.json()
    data2 = res2.json()

    # Activity present
    activity1 = data1["activity"]
    activity2 = data2["activity"]
    assert activity1 is not None
    assert activity2 is not None

    assert activity1["id"] == "l1-colors-banana"
    assert activity1["level"] == 1
    assert activity1["skill"] == "colors"
    assert activity1["type"] == "choice"
    assert len(activity1["choices"]) >= 2

    # Deterministic choice order across two separate calls
    choice_ids_1 = [c["id"] for c in activity1["choices"]]
    choice_ids_2 = [c["id"] for c in activity2["choices"]]
    assert choice_ids_1 == choice_ids_2

    # Verify no secret keys exist in the entire JSON response
    forbidden_keys = {"answer", "accepted_words", "rubric", "reveal"}
    all_keys = set(_walk_keys(data1))
    leaked = all_keys.intersection(forbidden_keys)
    assert not leaked, f"Response leaked forbidden keys: {leaked}"


async def test_get_sessions_me_progress_with_counted_attempts() -> None:
    app = _app()
    repo: InMemoryRepository = app.state.repository  # type: ignore[assignment]
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)

    session = await repo.create_session(
        NewSession(
            token_hash=token_hash,
            nickname="Sam",
            avatar="sprout",
            expires_at=now + timedelta(days=30),
        )
    )

    # Add 3 correct counted attempts and 1 incorrect counted attempt
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
    await repo.add_attempt(
        session.id,
        NewAttempt(
            item_id="l1-colors-grass",
            level=1,
            skill_tag="colors",
            attempt_no=1,
            result="correct",
            counted=True,
        ),
    )
    await repo.add_attempt(
        session.id,
        NewAttempt(
            item_id="l1-animals-cat",
            level=1,
            skill_tag="animals",
            attempt_no=1,
            result="incorrect",
            counted=True,
        ),
    )
    await repo.add_attempt(
        session.id,
        NewAttempt(
            item_id="l1-animals-dog",
            level=1,
            skill_tag="animals",
            attempt_no=1,
            result="correct",
            counted=True,
        ),
    )
    # Add an uncounted attempt (e.g. second attempt on an item) which must not affect progress
    await repo.add_attempt(
        session.id,
        NewAttempt(
            item_id="l1-animals-cat",
            level=1,
            skill_tag="animals",
            attempt_no=2,
            result="correct",
            counted=False,
        ),
    )

    async with _client(app) as client:
        res = await client.get(
            "/v1/sessions/me", headers={"Authorization": f"Bearer {raw_token}"}
        )

    assert res.status_code == 200
    progress = res.json()["progress"]
    # 3 correct out of 4 counted attempts in the window of 5
    assert progress == {
        "level": 1,
        "correct_in_window": 3,
        "window": 5,
        "required": 4,
    }
