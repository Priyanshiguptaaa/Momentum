"""Simple in-process TTL cache for expensive coaching / reasoning calls."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}

# Coaching packs are expensive (LLM). 1 hour is enough for a morning brief.
DEFAULT_TTL_SECONDS = 3600


def cache_get(key: str) -> Any | None:
    with _lock:
        item = _store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            del _store[key]
            return None
        return value


def cache_set(key: str, value: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    with _lock:
        _store[key] = (time.time() + ttl_seconds, value)


def cache_clear(prefix: str | None = None) -> None:
    with _lock:
        if prefix is None:
            _store.clear()
            return
        for k in list(_store):
            if k.startswith(prefix):
                del _store[k]


def cached(key: str, factory: Callable[[], T], ttl_seconds: int = DEFAULT_TTL_SECONDS) -> T:
    hit = cache_get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    value = factory()
    cache_set(key, value, ttl_seconds=ttl_seconds)
    return value
