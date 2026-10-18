"""Health routes: liveness (no dependencies) and readiness (database)."""

import asyncio

from fastapi import APIRouter, Request

from app.core.errors import ServiceUnavailableError

router = APIRouter()

READY_TIMEOUT_S = 3.0


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request) -> dict[str, str]:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        from app.main import _open_pool

        pool = await _open_pool(request.app.state.settings)
        if pool is not None:
            request.app.state.pool = pool
    if pool is None:
        raise ServiceUnavailableError()
    try:
        await asyncio.wait_for(pool.fetchval("select 1"), timeout=READY_TIMEOUT_S)
    except Exception as exc:
        raise ServiceUnavailableError() from exc
    return {"status": "ready"}
