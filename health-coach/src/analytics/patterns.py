"""Detect and persist personal physiology patterns from daily summaries."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DailySummary, PhysiologyPattern, User

LOOKBACK_DAYS = 60
MIN_SUPPORT = 3


def _by_date(rows: list[DailySummary]) -> dict[date, DailySummary]:
    return {r.date: r for r in rows}


def _next_morning_delta(by_day: dict[date, DailySummary], day: date) -> Optional[float]:
    nxt = by_day.get(day + timedelta(days=1))
    if nxt is None or nxt.weight_change_from_yesterday_kg is None:
        return None
    return float(nxt.weight_change_from_yesterday_kg)


def _confidence(support: int, mean_delta: float) -> float:
    # More events + clearer effect → higher confidence (capped).
    base = min(0.85, 0.35 + 0.08 * support)
    effect = min(0.15, abs(mean_delta) * 0.12)
    return round(min(0.92, base + effect), 2)


def _upsert_pattern(
    db: Session,
    *,
    user_id: int,
    pattern_key: str,
    title: str,
    description: str,
    trigger: str,
    effect: str,
    deltas: list[tuple[date, float]],
    counterevidence: list[str],
) -> Optional[PhysiologyPattern]:
    if len(deltas) < MIN_SUPPORT:
        return None
    values = [d for _, d in deltas]
    avg = mean(values)
    # Only keep directional patterns that are practically meaningful.
    if abs(avg) < 0.15:
        return None

    support = len(deltas)
    last_seen = max(d for d, _ in deltas)
    evidence = [
        f"{d.isoformat()}: next-morning weight change {delta:+.2f} kg" for d, delta in deltas[-5:]
    ]
    conf = _confidence(support, avg)

    existing = db.scalar(
        select(PhysiologyPattern).where(
            PhysiologyPattern.user_id == user_id,
            PhysiologyPattern.pattern_key == pattern_key,
        )
    )
    if existing is None:
        existing = PhysiologyPattern(
            user_id=user_id,
            pattern_key=pattern_key,
            title=title,
            description=description,
            trigger=trigger,
            effect=effect,
            unit="kg",
            source="auto",
        )
        db.add(existing)

    existing.title = title
    existing.description = description
    existing.trigger = trigger
    existing.effect = effect
    existing.typical_delta = round(avg, 3)
    existing.support_count = support
    existing.confidence = conf
    existing.evidence = evidence
    existing.counterevidence = counterevidence
    existing.last_seen_date = last_seen
    existing.updated_at = datetime.now(UTC)
    existing.metadata_json = {
        "sample_deltas_kg": [round(v, 3) for v in values[-8:]],
        "mean_delta_kg": round(avg, 3),
    }
    return existing


TriggerFn = Callable[[DailySummary], bool]


def _collect_trigger_deltas(
    rows: list[DailySummary],
    trigger_fn: TriggerFn,
) -> list[tuple[date, float]]:
    by_day = _by_date(rows)
    out: list[tuple[date, float]] = []
    for row in rows:
        if not trigger_fn(row):
            continue
        delta = _next_morning_delta(by_day, row.date)
        if delta is None:
            continue
        out.append((row.date, delta))
    return out


def refresh_physiology_patterns(db: Session, user_id: int) -> list[PhysiologyPattern]:
    """Recompute auto patterns for a user from recent daily summaries."""
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS - 1)
    rows = list(
        db.scalars(
            select(DailySummary)
            .where(
                DailySummary.user_id == user_id,
                DailySummary.date >= start,
                DailySummary.date <= end,
            )
            .order_by(DailySummary.date.asc())
        ).all()
    )
    if len(rows) < 5:
        return []

    sodium_vals = [r.sodium_mg for r in rows if r.sodium_mg is not None]
    sodium_hi = None
    if len(sodium_vals) >= 5:
        ordered = sorted(sodium_vals)
        sodium_hi = ordered[int(0.75 * (len(ordered) - 1))]

    sleep_vals = [r.sleep_hours for r in rows if r.sleep_hours is not None]
    sleep_lo = None
    if len(sleep_vals) >= 5:
        ordered = sorted(sleep_vals)
        sleep_lo = ordered[int(0.25 * (len(ordered) - 1))]

    specs: list[dict[str, Any]] = [
        {
            "pattern_key": "restaurant_next_morning_bump",
            "title": "Restaurant day → next-morning scale bump",
            "trigger": "restaurant_meal",
            "effect": "next_morning_weight_change",
            "trigger_fn": lambda r: bool(r.restaurant_meal),
            "description_fn": lambda avg, n: (
                f"Across {n} restaurant days in the last {LOOKBACK_DAYS} days, "
                f"next-morning weight change averaged {avg:+.2f} kg. "
                "Association only — sodium, volume, and timing may contribute."
            ),
        },
        {
            "pattern_key": "alcohol_next_morning_bump",
            "title": "Alcohol → next-morning scale bump",
            "trigger": "alcohol_servings",
            "effect": "next_morning_weight_change",
            "trigger_fn": lambda r: (r.alcohol_servings or 0) > 0,
            "description_fn": lambda avg, n: (
                f"Across {n} days with alcohol, next-morning weight change averaged {avg:+.2f} kg. "
                "Not proof of fat gain; fluid and glycogen shifts are common."
            ),
        },
        {
            "pattern_key": "strength_day_next_morning_bump",
            "title": "Strength training → next-morning scale bump",
            "trigger": "strength_training",
            "effect": "next_morning_weight_change",
            "trigger_fn": lambda r: (r.strength_training_minutes or 0) >= 30,
            "description_fn": lambda avg, n: (
                f"Across {n} strength days (≥30 min), next-morning weight change averaged {avg:+.2f} kg. "
                "Often inflammation/glycogen — usually temporary."
            ),
        },
    ]
    if sodium_hi is not None:
        hi = sodium_hi
        specs.append(
            {
                "pattern_key": "high_sodium_next_morning_bump",
                "title": "Higher-sodium day → next-morning scale bump",
                "trigger": "high_sodium",
                "effect": "next_morning_weight_change",
                "trigger_fn": lambda r, threshold=hi: r.sodium_mg is not None
                and r.sodium_mg >= threshold,
                "description_fn": lambda avg, n, threshold=hi: (
                    f"On {n} higher-sodium days (≥{threshold:.0f} mg vs your recent distribution), "
                    f"next-morning weight change averaged {avg:+.2f} kg. Association, not causation."
                ),
            }
        )
    if sleep_lo is not None:
        lo = sleep_lo
        specs.append(
            {
                "pattern_key": "low_sleep_next_morning_bump",
                "title": "Shorter sleep → next-morning scale bump",
                "trigger": "low_sleep",
                "effect": "next_morning_weight_change",
                "trigger_fn": lambda r, threshold=lo: r.sleep_hours is not None
                and r.sleep_hours <= threshold,
                "description_fn": lambda avg, n, threshold=lo: (
                    f"On {n} shorter-sleep days (≤{threshold:.1f} h), "
                    f"next-morning weight change averaged {avg:+.2f} kg."
                ),
            }
        )

    kept_keys: set[str] = set()
    results: list[PhysiologyPattern] = []
    for spec in specs:
        deltas = _collect_trigger_deltas(rows, spec["trigger_fn"])
        if len(deltas) < MIN_SUPPORT:
            continue
        avg = mean(d for _, d in deltas)
        counter: list[str] = []
        if any(d <= 0 for _, d in deltas):
            counter.append("Some trigger days were not followed by a scale increase")
        pattern = _upsert_pattern(
            db,
            user_id=user_id,
            pattern_key=spec["pattern_key"],
            title=spec["title"],
            description=spec["description_fn"](avg, len(deltas)),
            trigger=spec["trigger"],
            effect=spec["effect"],
            deltas=deltas,
            counterevidence=counter,
        )
        if pattern is not None:
            kept_keys.add(pattern.pattern_key)
            results.append(pattern)

    # Drop stale auto patterns that no longer meet criteria.
    existing_auto = db.scalars(
        select(PhysiologyPattern).where(
            PhysiologyPattern.user_id == user_id,
            PhysiologyPattern.source == "auto",
        )
    ).all()
    for row in existing_auto:
        if row.pattern_key not in kept_keys:
            db.delete(row)

    db.commit()
    return results


def list_patterns_for_user(db: Session, user_id: int) -> list[PhysiologyPattern]:
    return list(
        db.scalars(
            select(PhysiologyPattern)
            .where(PhysiologyPattern.user_id == user_id)
            .order_by(PhysiologyPattern.confidence.desc(), PhysiologyPattern.support_count.desc())
        ).all()
    )


def refresh_patterns_for_primary_user(db: Session) -> list[PhysiologyPattern]:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        return []
    return refresh_physiology_patterns(db, user.id)


def pattern_to_dict(p: PhysiologyPattern) -> dict[str, Any]:
    return {
        "pattern_key": p.pattern_key,
        "title": p.title,
        "description": p.description,
        "trigger": p.trigger,
        "effect": p.effect,
        "typical_delta": p.typical_delta,
        "unit": p.unit,
        "support_count": p.support_count,
        "confidence": p.confidence,
        "evidence": p.evidence or [],
        "counterevidence": p.counterevidence or [],
        "last_seen_date": p.last_seen_date.isoformat() if p.last_seen_date else None,
        "caveat": "Association from your history — not proven causation.",
    }
