"""Source priority rules for daily summary construction."""

from __future__ import annotations

# Lower index = higher priority.
SOURCE_PRIORITY: dict[str, list[str]] = {
    "weight": ["smart_scale", "manual", "macrofactor", "apple_health", "garmin", "synthetic"],
    "calories": ["macrofactor", "manual", "synthetic"],
    "protein": ["macrofactor", "manual", "synthetic"],
    "fiber": ["macrofactor", "manual", "synthetic"],
    "sodium": ["macrofactor", "manual", "synthetic"],
    "steps": ["apple_watch", "garmin", "apple_health", "iphone", "synthetic"],
    "sleep_duration": ["garmin", "apple_watch", "apple_health", "synthetic"],
    "active_energy": ["apple_watch", "garmin", "apple_health", "synthetic"],
}


def prefer_source(metric_type: str, candidates: list[str]) -> str | None:
    if not candidates:
        return None
    priorities = SOURCE_PRIORITY.get(metric_type, [])
    ranked = sorted(
        candidates,
        key=lambda s: priorities.index(s) if s in priorities else len(priorities),
    )
    return ranked[0]
