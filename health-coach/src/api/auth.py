"""Auth helpers for phone → backend sync bridges."""

from __future__ import annotations

from fastapi import Header, HTTPException

from src.db.config import settings


def require_sync_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = settings.sync_api_key
    if not expected:
        # Local prototype convenience: allow open ingest when unset.
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
