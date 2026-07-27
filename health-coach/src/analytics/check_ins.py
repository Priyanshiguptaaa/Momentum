"""Subjective check-ins: hunger, energy, stress, cravings, bloating."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DailySummary, SubjectiveCheckIn, User


def _primary_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise LookupError("No users found. Import data first.")
    return user


def check_in_to_dict(row: SubjectiveCheckIn) -> dict[str, Any]:
    return {
        "id": row.id,
        "logged_at": row.logged_at.isoformat() if row.logged_at else None,
        "period": row.period,
        "hunger": row.hunger,
        "energy": row.energy,
        "stress": row.stress,
        "cravings": row.cravings,
        "bloating": row.bloating,
        "digestion": row.digestion,
        "notes": row.notes,
        "meal_event_id": row.meal_event_id,
        "source": row.source,
    }


def list_check_ins(db: Session, *, days: int = 30, limit: int = 100) -> list[SubjectiveCheckIn]:
    user = _primary_user(db)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return list(
        db.scalars(
            select(SubjectiveCheckIn)
            .where(SubjectiveCheckIn.user_id == user.id, SubjectiveCheckIn.logged_at >= cutoff)
            .order_by(SubjectiveCheckIn.logged_at.desc())
            .limit(limit)
        ).all()
    )


def create_check_in(db: Session, payload: dict[str, Any]) -> SubjectiveCheckIn:
    user = _primary_user(db)
    logged_at = payload.get("logged_at")
    if isinstance(logged_at, str):
        logged_at = datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
    if logged_at is None:
        logged_at = datetime.now(UTC)
    if logged_at.tzinfo is None:
        logged_at = logged_at.replace(tzinfo=UTC)

    # Infer period from hour if not provided
    period = payload.get("period")
    if not period:
        hour = logged_at.hour
        if hour < 11:
            period = "morning"
        elif hour < 17:
            period = "afternoon"
        else:
            period = "evening"

    row = SubjectiveCheckIn(
        user_id=user.id,
        logged_at=logged_at,
        period=period,
        hunger=payload.get("hunger"),
        energy=payload.get("energy"),
        stress=payload.get("stress"),
        cravings=payload.get("cravings"),
        bloating=payload.get("bloating"),
        digestion=payload.get("digestion"),
        notes=payload.get("notes"),
        meal_event_id=payload.get("meal_event_id"),
        source=payload.get("source") or "manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_check_in(db: Session, check_in_id: int) -> None:
    user = _primary_user(db)
    row = db.scalar(
        select(SubjectiveCheckIn).where(
            SubjectiveCheckIn.id == check_in_id, SubjectiveCheckIn.user_id == user.id
        )
    )
    if row is None:
        raise LookupError(f"Check-in {check_in_id} not found")
    db.delete(row)
    db.commit()


def _avg(vals: list[float]) -> Optional[float]:
    return round(mean(vals), 2) if vals else None


def detect_decision_patterns(db: Session) -> list[dict[str, Any]]:
    """Link objective metrics to subjective feel — digital twin of decisions."""
    user = _primary_user(db)
    check_ins = list_check_ins(db, days=60, limit=200)
    if len(check_ins) < 3:
        return []

    summaries = {
        r.date: r
        for r in db.scalars(
            select(DailySummary)
            .where(DailySummary.user_id == user.id)
            .order_by(DailySummary.date.desc())
            .limit(60)
        ).all()
    }

    patterns: list[dict[str, Any]] = []

    # Poor sleep → evening hunger/cravings
    poor_sleep_hunger: list[float] = []
    good_sleep_hunger: list[float] = []
    poor_sleep_cravings: list[float] = []
    good_sleep_cravings: list[float] = []
    for c in check_ins:
        if (c.period or "") != "evening" and c.logged_at.hour < 17:
            continue
        day = c.logged_at.date()
        # Sleep from previous night ≈ summary for that calendar day
        s = summaries.get(day)
        if s is None or s.sleep_hours is None:
            continue
        if c.hunger is not None:
            if s.sleep_hours < 6.5:
                poor_sleep_hunger.append(float(c.hunger))
            elif s.sleep_hours >= 7.5:
                good_sleep_hunger.append(float(c.hunger))
        if c.cravings is not None:
            if s.sleep_hours < 6.5:
                poor_sleep_cravings.append(float(c.cravings))
            elif s.sleep_hours >= 7.5:
                good_sleep_cravings.append(float(c.cravings))

    if len(poor_sleep_hunger) >= 3 and len(good_sleep_hunger) >= 3:
        delta = mean(poor_sleep_hunger) - mean(good_sleep_hunger)
        if delta >= 1.0:
            patterns.append(
                {
                    "key": "poor_sleep_evening_hunger",
                    "category": "decision",
                    "title": "Poor sleep → higher evening hunger",
                    "insight": (
                        f"After nights under 6.5h sleep, evening hunger averages "
                        f"{mean(poor_sleep_hunger):.1f}/10 vs {mean(good_sleep_hunger):.1f}/10 "
                        f"after 7.5h+ nights. You're more likely to overeat 6–8 PM after poor sleep."
                    ),
                    "confidence": min(0.85, 0.45 + 0.05 * len(poor_sleep_hunger)),
                    "support": len(poor_sleep_hunger) + len(good_sleep_hunger),
                }
            )
    if len(poor_sleep_cravings) >= 3 and len(good_sleep_cravings) >= 3:
        delta = mean(poor_sleep_cravings) - mean(good_sleep_cravings)
        if delta >= 1.0:
            patterns.append(
                {
                    "key": "poor_sleep_cravings",
                    "category": "decision",
                    "title": "Poor sleep → stronger evening cravings",
                    "insight": (
                        f"Evening cravings average {mean(poor_sleep_cravings):.1f}/10 after short sleep "
                        f"vs {mean(good_sleep_cravings):.1f}/10 after longer sleep."
                    ),
                    "confidence": min(0.8, 0.4 + 0.05 * len(poor_sleep_cravings)),
                    "support": len(poor_sleep_cravings) + len(good_sleep_cravings),
                }
            )

    # High stress → cravings
    high_stress_crave: list[float] = []
    low_stress_crave: list[float] = []
    for c in check_ins:
        if c.stress is None or c.cravings is None:
            continue
        if c.stress >= 7:
            high_stress_crave.append(float(c.cravings))
        elif c.stress <= 3:
            low_stress_crave.append(float(c.cravings))
    if len(high_stress_crave) >= 3 and len(low_stress_crave) >= 3:
        if mean(high_stress_crave) - mean(low_stress_crave) >= 1.5:
            patterns.append(
                {
                    "key": "stress_cravings",
                    "category": "decision",
                    "title": "High stress days → more cravings",
                    "insight": (
                        f"When stress is ≥7, cravings average {mean(high_stress_crave):.1f}/10 "
                        f"vs {mean(low_stress_crave):.1f}/10 on low-stress days."
                    ),
                    "confidence": min(0.8, 0.4 + 0.05 * len(high_stress_crave)),
                    "support": len(high_stress_crave) + len(low_stress_crave),
                }
            )

    # Recent averages for coaching
    recent = check_ins[:14]
    hunger_vals = [float(c.hunger) for c in recent if c.hunger is not None]
    energy_vals = [float(c.energy) for c in recent if c.energy is not None]
    if hunger_vals and mean(hunger_vals) >= 7:
        patterns.append(
            {
                "key": "chronic_hunger",
                "category": "decision",
                "title": "Hunger running high lately",
                "insight": (
                    f"Average hunger {mean(hunger_vals):.1f}/10 over recent check-ins — "
                    "fiber, protein, meal timing, or sleep may beat cutting calories further."
                ),
                "confidence": 0.65,
                "support": len(hunger_vals),
            }
        )
    if energy_vals and mean(energy_vals) <= 4:
        patterns.append(
            {
                "key": "low_energy",
                "category": "decision",
                "title": "Energy running low",
                "insight": (
                    f"Average energy {mean(energy_vals):.1f}/10 — recovery, sleep, or deficit "
                    "aggressiveness may need attention before adding training volume."
                ),
                "confidence": 0.6,
                "support": len(energy_vals),
            }
        )

    patterns.sort(key=lambda p: (-(p.get("confidence") or 0), -(p.get("support") or 0)))
    return patterns[:8]


def check_in_summary(db: Session) -> dict[str, Any]:
    try:
        rows = list_check_ins(db, days=14, limit=50)
    except LookupError:
        return {"count": 0, "averages": {}, "patterns": [], "recent": []}

    def collect(field: str) -> list[float]:
        return [float(getattr(r, field)) for r in rows if getattr(r, field) is not None]

    return {
        "count": len(rows),
        "averages": {
            "hunger": _avg(collect("hunger")),
            "energy": _avg(collect("energy")),
            "stress": _avg(collect("stress")),
            "cravings": _avg(collect("cravings")),
            "bloating": _avg(collect("bloating")),
        },
        "patterns": detect_decision_patterns(db),
        "recent": [check_in_to_dict(r) for r in rows[:10]],
    }
