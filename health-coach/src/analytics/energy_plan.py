"""Estimate maintenance and intake target from the user's own data.

Mindset: derive a better decision from body response than a hardcoded number.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.config import settings
from src.db.models import DailySummary, User

# ~7700 kcal ≈ 1 kg body mass (rough; used only for energy-balance inference)
KCAL_PER_KG = 7700.0
MIN_DAYS = 7


def _primary_user(db: Session) -> User | None:
    return db.scalar(select(User).order_by(User.id).limit(1))


def _avg(vals: list[float]) -> Optional[float]:
    return mean(vals) if vals else None


def estimate_energy_plan(db: Session, *, lookback_days: int = 21) -> dict[str, Any]:
    """Infer maintenance and a suggested intake target from recent summaries.

    Uses:
    - Average logged intake
    - Weight trend (kg/week) → implied energy balance
    - Active + resting energy when present (Apple Health / wearables)

    Returns a plan dict; never invents false precision.
    """
    user = _primary_user(db)
    if user is None:
        return {
            "suggested_target": float(settings.calorie_target),
            "estimated_maintenance": None,
            "source": "seed_default",
            "confidence": 0.2,
            "rationale": "No user data yet — using seed default until syncs arrive.",
            "method": "none",
            "inputs": {},
        }

    rows = list(
        db.scalars(
            select(DailySummary)
            .where(DailySummary.user_id == user.id)
            .order_by(DailySummary.date.desc())
            .limit(lookback_days)
        ).all()
    )
    if not rows:
        return {
            "suggested_target": float(settings.calorie_target),
            "estimated_maintenance": None,
            "source": "seed_default",
            "confidence": 0.2,
            "rationale": "No daily summaries yet.",
            "method": "none",
            "inputs": {},
        }

    intakes = [float(r.calories) for r in rows if r.calories is not None]
    trends = [
        float(r.weight_trend_kg_per_week)
        for r in rows
        if r.weight_trend_kg_per_week is not None
    ]
    expenditures: list[float] = []
    for r in rows:
        if r.active_energy_kcal is not None and r.resting_energy_kcal is not None:
            expenditures.append(float(r.active_energy_kcal) + float(r.resting_energy_kcal))
        elif r.active_energy_kcal is not None and r.resting_energy_kcal is None:
            # Incomplete — skip rather than undercount
            pass

    avg_intake = _avg(intakes)
    avg_trend = _avg(trends)
    avg_exp = _avg(expenditures)
    n_intake = len(intakes)
    n_trend = len(trends)

    maintenance_candidates: list[tuple[str, float, float]] = []  # method, value, weight

    # 1) Intake + weight trend → implied maintenance
    #    maintenance ≈ intake - (trend_kg/week * 7700 / 7)
    if avg_intake is not None and avg_trend is not None and n_intake >= MIN_DAYS and n_trend >= 3:
        daily_balance = avg_trend * (KCAL_PER_KG / 7.0)
        implied = avg_intake - daily_balance
        # Sanity bounds
        if 1200 <= implied <= 4500:
            conf_w = 0.55 if n_intake >= 14 else 0.4
            maintenance_candidates.append(("intake_plus_weight_trend", implied, conf_w))

    # 2) Wearable expenditure (active + resting)
    if avg_exp is not None and len(expenditures) >= MIN_DAYS:
        if 1200 <= avg_exp <= 4500:
            maintenance_candidates.append(
                ("wearable_expenditure", avg_exp, 0.45 if len(expenditures) >= 14 else 0.35)
            )

    # 3) Flat weight near current intake ≈ maintenance
    if (
        avg_intake is not None
        and avg_trend is not None
        and abs(avg_trend) < 0.08
        and n_intake >= MIN_DAYS
    ):
        maintenance_candidates.append(("flat_weight_at_intake", avg_intake, 0.5))

    estimated_maintenance: Optional[float] = None
    method = "none"
    confidence = 0.25
    if maintenance_candidates:
        # Weighted average of candidates
        total_w = sum(w for _, _, w in maintenance_candidates)
        estimated_maintenance = sum(v * w for _, v, w in maintenance_candidates) / total_w
        method = "+".join(m for m, _, _ in maintenance_candidates)
        confidence = min(0.85, max(w for _, _, w in maintenance_candidates) + 0.1 * (len(maintenance_candidates) - 1))

    # Suggested target: modest deficit (~15% or 400 kcal, whichever smaller) when losing
    # is the goal — but if already losing well, stay near current intake.
    suggested: Optional[float] = None
    rationale_parts: list[str] = []

    if estimated_maintenance is not None:
        if avg_trend is not None and avg_trend < -0.15 and avg_intake is not None:
            # Already losing — keep current average intake as the working target
            suggested = avg_intake
            rationale_parts.append(
                f"Weight trend ~{avg_trend:+.2f} kg/week at ~{avg_intake:.0f} kcal intake — "
                f"keeping your recent average as the working target (estimated maintenance ~{estimated_maintenance:.0f})."
            )
        elif avg_trend is not None and avg_trend > 0.15 and avg_intake is not None:
            # Gaining — suggest maintenance − ~300–400
            cut = min(400.0, estimated_maintenance * 0.15)
            suggested = estimated_maintenance - cut
            rationale_parts.append(
                f"Weight trending up (~{avg_trend:+.2f} kg/week). "
                f"Estimated maintenance ~{estimated_maintenance:.0f}; suggested target ~{suggested:.0f} "
                f"(~{cut:.0f} kcal below maintenance)."
            )
        else:
            cut = min(350.0, estimated_maintenance * 0.12)
            suggested = estimated_maintenance - cut
            rationale_parts.append(
                f"Estimated maintenance ~{estimated_maintenance:.0f} from your data ({method}). "
                f"Suggested working target ~{suggested:.0f}."
            )
        source = "body_data"
    elif avg_intake is not None and n_intake >= MIN_DAYS:
        suggested = avg_intake
        source = "recent_intake"
        confidence = 0.35
        rationale_parts.append(
            f"Not enough trend signal for maintenance yet — using your recent average intake "
            f"(~{avg_intake:.0f} kcal) as the working target."
        )
        method = "recent_intake_average"
    else:
        suggested = float(settings.calorie_target)
        source = "seed_default"
        confidence = 0.15
        rationale_parts.append(
            "Insufficient intake/weight history — temporary seed default until more days sync."
        )
        method = "seed"

    # Clamp
    suggested = max(1200.0, min(4000.0, float(suggested)))
    if estimated_maintenance is not None:
        estimated_maintenance = max(1200.0, min(4500.0, float(estimated_maintenance)))

    return {
        "suggested_target": round(suggested),
        "estimated_maintenance": round(estimated_maintenance) if estimated_maintenance else None,
        "source": source,
        "confidence": round(confidence, 2),
        "rationale": " ".join(rationale_parts),
        "method": method,
        "inputs": {
            "days": len(rows),
            "avg_intake": round(avg_intake) if avg_intake else None,
            "avg_trend_kg_per_week": round(avg_trend, 3) if avg_trend is not None else None,
            "avg_wearable_expenditure": round(avg_exp) if avg_exp else None,
            "intake_days": n_intake,
            "trend_days": n_trend,
            "expenditure_days": len(expenditures),
        },
    }
