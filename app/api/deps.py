"""Shared request dependencies (repository access and bearer authentication)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast

import asyncpg
from fastapi import Depends, Header, Request

from app.core.errors import ServiceUnavailableError, UnauthorizedError
from app.core.tokens import hash_token
from app.repositories.base import Repository, SessionRecord
from app.repositories.postgres import PostgresRepository


async def get_repository(request: Request) -> Repository:
    """Return the configured repository, or build one from the pool."""

    configured = getattr(request.app.state, "repository", None)
    if configured is not None:
        return cast(Repository, configured)
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        from app.main import _open_pool

        pool = await _open_pool(request.app.state.settings)
        if pool is not None:
            request.app.state.pool = pool
    if pool is None:
        raise ServiceUnavailableError()
    repository = PostgresRepository(pool)
    request.app.state.repository = repository
    return repository


def parse_bearer(header: str | None) -> str:
    """Extract the token from an Authorization header, or raise 401."""

    parts = header.split() if header else []
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise UnauthorizedError()
    return parts[1]


async def get_current_session(
    repository: Annotated[Repository, Depends(get_repository)],
    authorization: Annotated[str | None, Header()] = None,
) -> SessionRecord:
    """Resolve the bearer token to a live session, refreshing last_active_at.

    A missing, malformed, unknown, or expired token is rejected with 401.
    The token value is never logged.
    """

    token = parse_bearer(authorization)
    try:
        session = await repository.get_by_token_hash(hash_token(token))
        now = datetime.now(UTC)
        if session is None:
            raise UnauthorizedError()
        if session.expires_at <= now:
            await repository.delete_session(session.id)
            raise UnauthorizedError()
        await repository.touch_last_active(session.id, now)
    except (asyncpg.PostgresError, OSError) as exc:
        raise ServiceUnavailableError() from exc
    return session
