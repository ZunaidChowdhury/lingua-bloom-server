"""Unit tests for the in-memory sliding-window rate limiter."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.errors import RateLimitedError
from app.core.rate_limit import (
    DEFAULT_IP_LIMIT,
    DEFAULT_IP_WINDOW,
    DEFAULT_SESSION_CREATE_LIMIT,
    DEFAULT_SESSION_CREATE_WINDOW,
    DEFAULT_TURN_LIMIT,
    DEFAULT_TURN_WINDOW,
    SlidingWindowLimiter,
    get_client_ip,
)


class MockClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def _mock_request(
    headers: dict[str, str] | None = None,
    client: tuple[str, int] | None = None,
) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": raw_headers,
        "client": client,
    }
    return Request(scope)


def test_rate_limit_constants() -> None:
    assert DEFAULT_TURN_LIMIT == 30
    assert DEFAULT_TURN_WINDOW == 60
    assert DEFAULT_IP_LIMIT == 120
    assert DEFAULT_IP_WINDOW == 60
    assert DEFAULT_SESSION_CREATE_LIMIT == 10
    assert DEFAULT_SESSION_CREATE_WINDOW == 3600


def test_sliding_window_under_limit_succeeds() -> None:
    clock = MockClock(100.0)
    limiter = SlidingWindowLimiter(max_count=3, window_seconds=60, clock=clock)

    limiter.check("user-1")
    clock.advance(10)
    limiter.check("user-1")
    clock.advance(10)
    limiter.check("user-1")

    # 3 calls recorded within 60s
    assert limiter.key_count() == 1


def test_sliding_window_exceed_limit_raises_with_retry_after() -> None:
    clock = MockClock(100.0)
    limiter = SlidingWindowLimiter(max_count=2, window_seconds=60, clock=clock)

    limiter.check("key-1")  # at 100.0, expires at 160.0
    clock.advance(20.0)
    limiter.check("key-1")  # at 120.0, expires at 180.0

    # 3rd check at 120.0 should fail; oldest was 100.0, so 40s remain
    with pytest.raises(RateLimitedError) as exc_info:
        limiter.check("key-1")

    err = exc_info.value
    assert err.status_code == 429
    assert err.code == "rate_limited"
    assert err.headers.get("Retry-After") == "40"


def test_sliding_window_recovers_after_window_passes() -> None:
    clock = MockClock(100.0)
    limiter = SlidingWindowLimiter(max_count=2, window_seconds=60, clock=clock)

    limiter.check("key-1")
    clock.advance(10.0)
    limiter.check("key-1")

    with pytest.raises(RateLimitedError):
        limiter.check("key-1")

    # Advance past the first item's window (100.0 + 60 = 160.0)
    clock.advance(55.0)  # current time = 165.0; first item expired, second remains
    limiter.check("key-1")  # succeeds, now 2 items in bucket (110.0, 165.0)

    # 3rd item still fails
    with pytest.raises(RateLimitedError):
        limiter.check("key-1")


def test_sliding_window_isolated_keys() -> None:
    clock = MockClock(100.0)
    limiter = SlidingWindowLimiter(max_count=1, window_seconds=60, clock=clock)

    limiter.check("key-A")
    with pytest.raises(RateLimitedError):
        limiter.check("key-A")

    # key-B is unaffected
    limiter.check("key-B")
    with pytest.raises(RateLimitedError):
        limiter.check("key-B")


def test_prune_all_bounds_memory() -> None:
    clock = MockClock(100.0)
    limiter = SlidingWindowLimiter(max_count=5, window_seconds=30, clock=clock)

    limiter.check("k1")
    limiter.check("k2")
    limiter.check("k3")
    assert limiter.key_count() == 3

    # Advance clock so all entries expire
    clock.advance(35.0)
    pruned = limiter.prune_all()
    assert pruned == 3
    assert limiter.key_count() == 0


def test_auto_prune_on_interval() -> None:
    clock = MockClock(100.0)
    limiter = SlidingWindowLimiter(
        max_count=100, window_seconds=10, clock=clock, prune_interval=5
    )

    for i in range(4):
        limiter.check(f"k{i}")
    assert limiter.key_count() == 4

    # Expire all
    clock.advance(15.0)
    # The 5th check triggers auto-prune
    limiter.check("k_trigger")
    # All k0-k3 should have been pruned, leaving only k_trigger
    assert limiter.key_count() == 1


def test_get_client_ip_forwarded_for_first_entry() -> None:
    req = _mock_request(
        headers={"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
    )
    assert get_client_ip(req) == "203.0.113.195"


def test_get_client_ip_socket_fallback() -> None:
    req = _mock_request(client=("192.168.1.50", 12345))
    assert get_client_ip(req) == "192.168.1.50"


def test_get_client_ip_whitespace_forwarded_falls_back() -> None:
    req = _mock_request(
        headers={"X-Forwarded-For": "   "},
        client=("10.0.0.1", 54321),
    )
    assert get_client_ip(req) == "10.0.0.1"


def test_get_client_ip_unknown_fallback() -> None:
    req = _mock_request()
    assert get_client_ip(req) == "unknown"
