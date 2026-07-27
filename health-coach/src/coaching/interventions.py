"""Intervention experiments: start, list, evaluate against weight trends."""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DailySummary, Intervention, User


def _primary_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise LookupError("No users found. Import data first.")
    return user


def create_intervention(
    db: Session,
    *,
    name: str,
    hypothesis: str,
    start_date: date,
    category: str | None = None,
    instructions: str | None = None,
    target_metrics: list[str] | None = None,
    end_date: date | None = None,
) -> Intervention:
    user = _primary_user(db)
    row = Intervention(
        user_id=user.id,
        name=name.strip(),
        hypothesis=hypothesis.strip(),
        start_date=start_date,
        end_date=end_date,
        category=category,
        instructions=instructions,
        target_metrics=target_metrics or ["weight_trend"],
        source="manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_interventions(db: Session) -> list[Intervention]:
    user = _primary_user(db)
    return list(
        db.scalars(
            select(Intervention)
            .where(Intervention.user_id == user.id)
            .order_by(Intervention.start_date.desc())
        ).all()
    )


def _avg_weight(rows: list[DailySummary]) -> Optional[float]:
    vals = [r.morning_weight_kg for r in rows if r.morning_weight_kg is not None]
    return mean(vals) if vals else None


def _avg_trend(rows: list[DailySummary]) -> Optional[float]:
    vals = [r.weight_trend_kg_per_week for r in rows if r.weight_trend_kg_per_week is not None]
    return mean(vals) if vals else None


def evaluate_intervention(db: Session, intervention_id: int) -> Intervention:
    """Compare pre-window vs active-window weight averages/trends (associative only)."""
    user = _primary_user(db)
    item = db.scalar(
        select(Intervention).where(
            Intervention.id == intervention_id, Intervention.user_id == user.id
        )
    )
    if item is None:
        raise LookupError(f"Intervention {intervention_id} not found")

    end = item.end_date or date.today()
    start = item.start_date
    if end < start:
        raise ValueError("end_date before start_date")

    pre_end = start - timedelta(days=1)
    pre_start = pre_end - timedelta(days=13)
    active_rows = list(
        db.scalars(
            select(DailySummary)
            .where(
                DailySummary.user_id == user.id,
                DailySummary.date >= start,
                DailySummary.date <= end,
            )
            .order_by(DailySummary.date.asc())
        ).all()
    )
    pre_rows = list(
        db.scalars(
            select(DailySummary)
            .where(
                DailySummary.user_id == user.id,
                DailySummary.date >= pre_start,
                DailySummary.date <= pre_end,
            )
            .order_by(DailySummary.date.asc())
        ).all()
    )

    pre_w = _avg_weight(pre_rows)
    act_w = _avg_weight(active_rows)
    pre_t = _avg_trend(pre_rows)
    act_t = _avg_trend(active_rows)

    confounds: list[str] = []
    if any(r.restaurant_meal for r in active_rows):
        confounds.append("Restaurant meals during intervention window")
    if any((r.alcohol_servings or 0) > 0 for r in active_rows):
        confounds.append("Alcohol logged during intervention window")
    if len(active_rows) < 5:
        confounds.append("Short active window — low statistical power")

    delta_w = (act_w - pre_w) if pre_w is not None and act_w is not None else None
    delta_t = (act_t - pre_t) if pre_t is not None and act_t is not None else None

    confidence = 0.35
    if len(active_rows) >= 7 and len(pre_rows) >= 7:
        confidence = 0.55
    if len(active_rows) >= 14 and len(pre_rows) >= 10:
        confidence = 0.65
    if confounds:
        confidence = max(0.2, confidence - 0.1 * min(3, len(confounds)))

    results: dict[str, Any] = {
        "pre_window": {
            "start": pre_start.isoformat(),
            "end": pre_end.isoformat(),
            "days": len(pre_rows),
            "avg_morning_weight_kg": round(pre_w, 3) if pre_w is not None else None,
            "avg_trend_kg_per_week": round(pre_t, 3) if pre_t is not None else None,
        },
        "active_window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": len(active_rows),
            "avg_morning_weight_kg": round(act_w, 3) if act_w is not None else None,
            "avg_trend_kg_per_week": round(act_t, 3) if act_t is not None else None,
        },
        "delta_avg_weight_kg": round(delta_w, 3) if delta_w is not None else None,
        "delta_trend_kg_per_week": round(delta_t, 3) if delta_t is not None else None,
        "interpretation": (
            "Associative comparison only — not a controlled trial. "
            "Prefer multi-week trends and note confounds before changing the plan."
        ),
    }

    item.results = results
    item.confounding_factors = confounds
    item.result_confidence = round(confidence, 2)
    db.commit()
    db.refresh(item)
    return item


def intervention_to_dict(item: Intervention) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "hypothesis": item.hypothesis,
        "start_date": item.start_date.isoformat() if item.start_date else None,
        "end_date": item.end_date.isoformat() if item.end_date else None,
        "category": item.category,
        "instructions": item.instructions,
        "target_metrics": item.target_metrics,
        "adherence": item.adherence,
        "results": item.results,
        "confounding_factors": item.confounding_factors,
        "result_confidence": item.result_confidence,
        "status": (
            "active"
            if item.end_date is None or item.end_date >= date.today()
            else "completed"
        ),
    }
