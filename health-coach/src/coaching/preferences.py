"""User preferences — calorie target and similar plan settings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.config import settings
from src.db.models import User


def _primary_user(db: Session) -> User | None:
    return db.scalar(select(User).order_by(User.id).limit(1))


def get_calorie_target(db: Session) -> float:
    """User's planned intake target. Env HC_CALORIE_TARGET is only the seed default."""
    user = _primary_user(db)
    if user is not None and user.calorie_target is not None:
        return float(user.calorie_target)
    return float(settings.calorie_target)


def get_preferences(db: Session) -> dict[str, Any]:
    user = _primary_user(db)
    target = get_calorie_target(db)
    return {
        "calorie_target": target,
        "source": (
            "user"
            if user is not None and user.calorie_target is not None
            else "default"
        ),
        "display_name": user.display_name if user else None,
    }


def update_preferences(db: Session, *, calorie_target: float | None = None) -> dict[str, Any]:
    user = _primary_user(db)
    if user is None:
        raise LookupError("No users found. Sync or import data first.")
    if calorie_target is not None:
        if calorie_target < 800 or calorie_target > 6000:
            raise ValueError("calorie_target must be between 800 and 6000 kcal")
        user.calorie_target = float(calorie_target)
    db.commit()
    db.refresh(user)
    return get_preferences(db)
