"""FastAPI application factory and ASGI entrypoint (app.main:app)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resolved: Settings = app.state.settings
    app.state.llm = GroqClient(
        api_key=resolved.groq_api_key,
        model=resolved.groq_model,
        timeout_s=resolved.llm_timeout_s,
    )
    try:
        yield
    finally:
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
