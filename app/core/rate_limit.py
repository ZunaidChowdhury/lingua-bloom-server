"""In-memory sliding-window rate limiter (FR-6.5)."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import RateLimitedError, error_body

DEFAULT_TURN_LIMIT = 30
DEFAULT_TURN_WINDOW = 60

DEFAULT_IP_LIMIT = 120
DEFAULT_IP_WINDOW = 60

DEFAULT_SESSION_CREATE_LIMIT = 10
DEFAULT_SESSION_CREATE_WINDOW = 3600


def _default_clock() -> float:
    return datetime.now(UTC).timestamp()


class SlidingWindowLimiter:
    """Count events per key in a sliding window. Raises RateLimitedError on excess."""

    def __init__(
        self,
        max_count: int,
        window_seconds: int,
        clock: Callable[[], float] | None = None,
        prune_interval: int = 500,
    ) -> None:
        self._max_count = max_count
        self._window = float(window_seconds)
        self._clock = clock or _default_clock
        self._buckets: defaultdict[str, deque[float]] = defaultdict(deque)
        self._prune_interval = prune_interval
        self._ops_since_prune = 0

    @property
    def max_count(self) -> int:
        return self._max_count

    @property
    def window_seconds(self) -> float:
        return self._window

    def check(self, key: str) -> None:
        """Record one event for *key* and raise if the limit is exceeded."""

        now = self._clock()
        cutoff = now - self._window
        bucket = self._buckets[key]

        # Prune expired entries for this specific key
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._max_count:
            retry_after = max(1, math.ceil(bucket[0] + self._window - now))
            raise RateLimitedError(retry_after=retry_after)

        bucket.append(now)

        self._ops_since_prune += 1
        if self._ops_since_prune >= self._prune_interval:
            self.prune_all()
            self._ops_since_prune = 0

    def prune_all(self) -> int:
        """Remove stale entries and delete empty buckets to keep memory bounded."""

        now = self._clock()
        cutoff = now - self._window
        empty_keys: list[str] = []
        for key, bucket in list(self._buckets.items()):
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                empty_keys.append(key)
        for key in empty_keys:
            self._buckets.pop(key, None)
        return len(empty_keys)

    def key_count(self) -> int:
        """Return the number of tracked keys."""
        return len(self._buckets)


def get_client_ip(request: Request) -> str:
    """Extract client IP from the first X-Forwarded-For entry or socket address."""

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce the global IP rate limit (120 req/min)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method != "OPTIONS" and not request.url.path.startswith("/health"):
            limiter: SlidingWindowLimiter | None = getattr(
                request.app.state, "rate_ip", None
            )
            if limiter is not None:
                ip = get_client_ip(request)
                try:
                    limiter.check(ip)
                except RateLimitedError as exc:
                    response = JSONResponse(
                        status_code=exc.status_code,
                        content=error_body(exc.code, exc.message),
                        headers=exc.headers,
                    )
                    request_id = getattr(request.state, "request_id", None)
                    if request_id:
                        response.headers["X-Request-ID"] = request_id
                    return response
        return await call_next(request)
