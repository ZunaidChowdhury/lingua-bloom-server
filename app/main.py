"""FastAPI application factory and ASGI entrypoint (app.main:app)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes.health import router as health_router
from app.api.routes.slice import router as slice_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.llm.client import GroqClient

logger = logging.getLogger("app.main")


async def _open_pool(settings: Settings) -> asyncpg.Pool | None:
    """Create the shared pool, tolerating an unreachable database at startup."""

    try:
        return await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.db_min_pool_size,
            max_size=settings.db_max_pool_size,
            statement_cache_size=0,
            command_timeout=settings.db_command_timeout_s,
        )
    except (OSError, asyncpg.PostgresError, ValueError) as exc:
        logger.warning("database pool unavailable at startup: %s", type(exc).__name__)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resolved: Settings = app.state.settings
    app.state.llm = GroqClient(
        api_key=resolved.groq_api_key,
        model=resolved.groq_model,
        timeout_s=resolved.llm_timeout_s,
    )
    app.state.pool = await _open_pool(resolved)
    try:
        yield
    finally:
        if app.state.pool is not None:
            await app.state.pool.close()
        await app.state.llm.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    app = FastAPI(title="LinguaBloom API", version=__version__, lifespan=lifespan)
    app.state.settings = resolved

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.frontend_origin],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Server-Timing"],
        allow_credentials=False,
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(slice_router)
    return app


app = create_app()
