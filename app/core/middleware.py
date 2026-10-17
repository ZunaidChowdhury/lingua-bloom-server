"""Request-scoped middleware: request id, timing, and structured logging."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign an X-Request-ID, time the request, and log one JSON line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_PATTERN.match(incoming) else uuid4().hex
        request.state.request_id = request_id
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._log(request, request_id, status=500, start=start)
            raise
        self._log(request, request_id, status=response.status_code, start=start)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _log(request: Request, request_id: str, *, status: int, start: float) -> None:
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "route": request.url.path,
                "method": request.method,
                "status": status,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
            },
        )
