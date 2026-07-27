"""Build daily_summary rows from measurements + daily context."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.weight_trend import attach_weight_trends
from src.db.models import DailyContext, DailySummary, Measurement
from src.normalization.mappings import prefer_source
from src.normalization.units import completeness_score


def _metric_for_day(
    by_day_metric: dict[date, dict[str, list[Measurement]]],
    day: date,
    metric_type: str,
) -> Optional[float]:
    candidates = by_day_metric.get(day, {}).get(metric_type, [])
    if not candidates:
        return None
    sources = [m.source for m in candidates]
    chosen_source = prefer_source(metric_type, sources)
    chosen = next((m for m in candidates if m.source == chosen_source), candidates[0])
    return float(chosen.value)


def rebuild_daily_summaries(db: Session, user_id: int) -> int:
    measurements = db.scalars(
        select(Measurement).where(Measurement.user_id == user_id).order_by(Measurement.timestamp)
    ).all()
    contexts = {
        c.date: c
        for c in db.scalars(select(DailyContext).where(DailyContext.user_id == user_id)).all()
    }

    by_day_metric: dict[date, dict[str, list[Measurement]]] = defaultdict(lambda: defaultdict(list))
    days: set[date] = set(contexts.keys())
    for m in measurements:
        day = m.timestamp.date() if isinstance(m.timestamp, datetime) else m.timestamp
        by_day_metric[day][m.metric_type].append(m)
        days.add(day)

    if not days:
        return 0

    rows: list[dict] = []
    for day in sorted(days):
        weight = _metric_for_day(by_day_metric, day, "weight")
        calories = _metric_for_day(by_day_metric, day, "calories")
        protein = _metric_for_day(by_day_metric, day, "protein")
        fiber = _metric_for_day(by_day_metric, day, "fiber")
        sodium = _metric_for_day(by_day_metric, day, "sodium")
        steps = _metric_for_day(by_day_metric, day, "steps")
        sleep = _metric_for_day(by_day_metric, day, "sleep_duration")
        active_energy = _metric_for_day(by_day_metric, day, "active_energy")
        strength = _metric_for_day(by_day_metric, day, "strength_minutes")
        cardio = _metric_for_day(by_day_metric, day, "cardio_minutes")
        ctx = contexts.get(day)

        present = {
            "weight": weight is not None,
            "calories": calories is not None,
            "protein": protein is not None,
            "steps": steps is not None,
            "sleep": sleep is not None,
            "sodium": sodium is not None,
            "context": ctx is not None,
        }

        rows.append(
            {
                "date": day,
                "morning_weight_kg": weight,
                "calories": calories,
                "protein_g": protein,
                "fiber_g": fiber,
                "sodium_mg": sodium,
                "steps": steps,
                "active_energy_kcal": active_energy,
                "strength_training_minutes": strength,
                "cardio_minutes": cardio,
                "sleep_hours": sleep,
                "cycle_day": ctx.menstrual_cycle_day if ctx else None,
                "period_status": ctx.period_status if ctx else None,
                "restaurant_meal": bool(ctx.restaurant_meal) if ctx else False,
                "alcohol_servings": float(ctx.alcohol_servings) if ctx else 0.0,
                "data_completeness_score": completeness_score(present),
            }
        )

    frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    frame = attach_weight_trends(frame)

    # Clear and rewrite summaries for this user (prototype-friendly).
    existing = db.scalars(select(DailySummary).where(DailySummary.user_id == user_id)).all()
    for row in existing:
        db.delete(row)
    db.flush()

    for _, r in frame.iterrows():
        db.add(
            DailySummary(
                user_id=user_id,
                date=r["date"].date() if hasattr(r["date"], "date") else r["date"],
                morning_weight_kg=_maybe_float(r.get("morning_weight_kg")),
                weight_7d_average=_maybe_float(r.get("weight_7d_average")),
                weight_14d_average=_maybe_float(r.get("weight_14d_average")),
                weight_trend_kg_per_week=_maybe_float(r.get("weight_trend_kg_per_week")),
                weight_change_from_yesterday_kg=_maybe_float(r.get("weight_change_from_yesterday_kg")),
                calories=_maybe_float(r.get("calories")),
                protein_g=_maybe_float(r.get("protein_g")),
                fiber_g=_maybe_float(r.get("fiber_g")),
                sodium_mg=_maybe_float(r.get("sodium_mg")),
                steps=_maybe_float(r.get("steps")),
                active_energy_kcal=_maybe_float(r.get("active_energy_kcal")),
                strength_training_minutes=_maybe_float(r.get("strength_training_minutes")),
                cardio_minutes=_maybe_float(r.get("cardio_minutes")),
                sleep_hours=_maybe_float(r.get("sleep_hours")),
                cycle_day=int(r["cycle_day"]) if pd.notna(r.get("cycle_day")) else None,
                period_status=r.get("period_status") if pd.notna(r.get("period_status")) else None,
                restaurant_meal=bool(r.get("restaurant_meal")),
                alcohol_servings=float(r.get("alcohol_servings") or 0.0),
                data_completeness_score=float(r.get("data_completeness_score") or 0.0),
            )
        )

    db.commit()
    return len(frame)


def _maybe_float(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def get_summary_window(
    db: Session, user_id: int, target: date, lookback_days: int = 14
) -> list[DailySummary]:
    start = target - timedelta(days=lookback_days)
    return list(
        db.scalars(
            select(DailySummary)
            .where(
                DailySummary.user_id == user_id,
                DailySummary.date >= start,
                DailySummary.date <= target,
            )
            .order_by(DailySummary.date)
        ).all()
    )
