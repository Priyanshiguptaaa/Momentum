"""User preferences — calorie target resolved from body data by default."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.energy_plan import estimate_energy_plan
from src.db.config import settings
from src.db.models import User


def _primary_user(db: Session) -> User | None:
    return db.scalar(select(User).order_by(User.id).limit(1))


def get_calorie_target(db: Session) -> float:
    """Working intake target: manual override if set, else inferred from body data."""
    user = _primary_user(db)
    if user is not None and user.calorie_target is not None:
        return float(user.calorie_target)
    plan = estimate_energy_plan(db)
    return float(plan["suggested_target"])


def get_preferences(db: Session) -> dict[str, Any]:
    user = _primary_user(db)
    plan = estimate_energy_plan(db)

    if user is not None and user.calorie_target is not None:
        return {
            "calorie_target": float(user.calorie_target),
            "source": "manual",
            "mode": "manual",
            "display_name": user.display_name,
            "estimated_maintenance": plan.get("estimated_maintenance"),
            "auto_suggested_target": plan.get("suggested_target"),
            "confidence": plan.get("confidence"),
            "rationale": (
                "Manual override in use. Auto estimate from your data would be "
                f"~{plan.get('suggested_target')} kcal"
                + (
                    f" (maintenance ~{plan.get('estimated_maintenance')})."
                    if plan.get("estimated_maintenance")
                    else "."
                )
            ),
            "energy_plan": plan,
        }

    return {
        "calorie_target": float(plan["suggested_target"]),
        "source": plan.get("source") or "body_data",
        "mode": "auto",
        "display_name": user.display_name if user else None,
        "estimated_maintenance": plan.get("estimated_maintenance"),
        "auto_suggested_target": plan.get("suggested_target"),
        "confidence": plan.get("confidence"),
        "rationale": plan.get("rationale"),
        "energy_plan": plan,
    }


def update_preferences(
    db: Session,
    *,
    calorie_target: float | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Set manual target, or mode='auto' to clear override and use body-derived target."""
    user = _primary_user(db)
    if user is None:
        raise LookupError("No users found. Sync or import data first.")

    if mode == "auto":
        user.calorie_target = None
    elif calorie_target is not None:
        if calorie_target < 800 or calorie_target > 6000:
            raise ValueError("calorie_target must be between 800 and 6000 kcal")
        user.calorie_target = float(calorie_target)

    db.commit()
    db.refresh(user)
    return get_preferences(db)
