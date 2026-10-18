"""In-memory per-session locks for turn serialisation (single instance)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class SessionLocks:
    """Keyed asyncio locks; unused locks are removed when the last holder exits."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def __len__(self) -> int:
        return len(self._locks)

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                yield
        finally:
            if self._locks.get(key) is lock and not lock.locked():
                del self._locks[key]
