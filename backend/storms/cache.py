"""A tiny single-value async TTL cache (stdlib only) — refresh-on-read when stale.

The repo has no TTL-cache or scheduler infra and no cache deps; this matches the existing
non-expiring module-global idiom (api/tornado.py) but adds an expiry so live feeds refresh
~every 15 min on read without a background task. Per-process (one cache per uvicorn worker).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float, loader: Callable[[], Awaitable[T]]) -> None:
        self._ttl = ttl_seconds
        self._loader = loader
        self._value: T | None = None
        self._at: float = 0.0
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool:
        return self._value is not None and (time.monotonic() - self._at) <= self._ttl

    async def get(self) -> T:
        if self._fresh():
            return self._value  # type: ignore[return-value]
        # Serialize refreshes so concurrent first-hits don't all stampede the (rate-limited) upstream.
        async with self._lock:
            if self._fresh():
                return self._value  # type: ignore[return-value]
            self._value = await self._loader()
            self._at = time.monotonic()
            return self._value
