"""Simple TTL cache for external API responses."""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_store: dict[str, tuple[float, Any]] = {}

DEFAULT_TTL = 3600  # 1 hour


def cached(key: str, ttl: int = DEFAULT_TTL) -> Callable[[Callable[[], T | None]], Callable[[], T | None]]:
    def decorator(fn: Callable[[], T | None]) -> Callable[[], T | None]:
        def wrapper() -> T | None:
            now = time.monotonic()
            if key in _store:
                expires_at, value = _store[key]
                if now < expires_at:
                    return value
            result = fn()
            if result is not None:
                _store[key] = (now + ttl, result)
            return result
        return wrapper
    return decorator
