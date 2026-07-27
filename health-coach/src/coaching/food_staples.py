"""CRUD for foods/recipes the user eats consistently."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import FoodStaple, User


def _primary_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise LookupError("No users found. Import data first.")
    return user


def staple_to_dict(row: FoodStaple) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "meal_slot": row.meal_slot,
        "description": row.description,
        "ingredients": row.ingredients,
        "is_packaged": bool(row.is_packaged),
        "brand": row.brand,
        "frequency": row.frequency,
        "estimated_calories": row.estimated_calories,
        "estimated_protein_g": row.estimated_protein_g,
        "estimated_carbs_g": row.estimated_carbs_g,
        "estimated_fat_g": row.estimated_fat_g,
        "estimated_fiber_g": row.estimated_fiber_g,
        "estimated_sugar_g": row.estimated_sugar_g,
        "notes": row.notes,
        "quality_flags": row.quality_flags or [],
        "quality_notes": row.quality_notes,
        "learned_profile": row.learned_profile,
        "times_logged": int(row.times_logged or 0),
        "source": row.source,
    }


def list_food_staples(db: Session) -> list[FoodStaple]:
    user = _primary_user(db)
    return list(
        db.scalars(
            select(FoodStaple)
            .where(FoodStaple.user_id == user.id)
            .order_by(FoodStaple.updated_at.desc())
        ).all()
    )


def create_food_staple(db: Session, payload: dict[str, Any]) -> FoodStaple:
    user = _primary_user(db)
    row = FoodStaple(
        user_id=user.id,
        name=str(payload["name"]).strip(),
        meal_slot=payload.get("meal_slot"),
        description=payload.get("description"),
        ingredients=payload.get("ingredients"),
        is_packaged=bool(payload.get("is_packaged") or False),
        brand=payload.get("brand"),
        frequency=payload.get("frequency") or "often",
        estimated_calories=payload.get("estimated_calories"),
        estimated_protein_g=payload.get("estimated_protein_g"),
        estimated_carbs_g=payload.get("estimated_carbs_g"),
        estimated_fat_g=payload.get("estimated_fat_g"),
        estimated_fiber_g=payload.get("estimated_fiber_g"),
        estimated_sugar_g=payload.get("estimated_sugar_g"),
        notes=payload.get("notes"),
        source=payload.get("source") or "manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_food_staple(db: Session, staple_id: int) -> None:
    user = _primary_user(db)
    row = db.scalar(
        select(FoodStaple).where(FoodStaple.id == staple_id, FoodStaple.user_id == user.id)
    )
    if row is None:
        raise LookupError(f"Food staple {staple_id} not found")
    db.delete(row)
    db.commit()


def update_staple_quality(
    db: Session,
    staple_id: int,
    *,
    quality_flags: list[str],
    quality_notes: str,
) -> FoodStaple:
    user = _primary_user(db)
    row = db.scalar(
        select(FoodStaple).where(FoodStaple.id == staple_id, FoodStaple.user_id == user.id)
    )
    if row is None:
        raise LookupError(f"Food staple {staple_id} not found")
    row.quality_flags = quality_flags
    row.quality_notes = quality_notes
    row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row
