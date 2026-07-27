"""Unit helpers and metric name constants."""

from __future__ import annotations

METRIC_UNITS: dict[str, str] = {
    "weight": "kg",
    "calories": "kcal",
    "protein": "g",
    "fiber": "g",
    "sodium": "mg",
    "steps": "count",
    "sleep_duration": "hours",
    "active_energy": "kcal",
    "resting_energy": "kcal",
    "strength_minutes": "minutes",
    "cardio_minutes": "minutes",
}


def normalize_weight_to_kg(value: float, unit: str) -> float:
    unit_l = unit.lower().strip()
    if unit_l in {"kg", "kilogram", "kilograms"}:
        return value
    if unit_l in {"lb", "lbs", "pound", "pounds"}:
        return value * 0.45359237
    raise ValueError(f"Unsupported weight unit: {unit}")


def completeness_score(present: dict[str, bool], weights: dict[str, float] | None = None) -> float:
    """Weighted fraction of available core fields."""
    weights = weights or {
        "weight": 0.25,
        "calories": 0.2,
        "protein": 0.1,
        "steps": 0.15,
        "sleep": 0.15,
        "sodium": 0.1,
        "context": 0.05,
    }
    total = sum(weights.values())
    earned = sum(w for key, w in weights.items() if present.get(key, False))
    return round(earned / total, 3) if total else 0.0
