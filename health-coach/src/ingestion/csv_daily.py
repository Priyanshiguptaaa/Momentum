"""CSV importer for synthetic / normalized daily metric exports."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DailyContext, Measurement, SourceFile, User
from src.normalization.units import METRIC_UNITS


METRIC_COLUMNS: dict[str, tuple[str, str]] = {
    "weight_kg": ("weight", "kg"),
    "calories": ("calories", "kcal"),
    "protein_g": ("protein", "g"),
    "fiber_g": ("fiber", "g"),
    "sodium_mg": ("sodium", "mg"),
    "steps": ("steps", "count"),
    "sleep_hours": ("sleep_duration", "hours"),
    "active_energy_kcal": ("active_energy", "kcal"),
    "strength_minutes": ("strength_minutes", "minutes"),
    "cardio_minutes": ("cardio_minutes", "minutes"),
}


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_or_create_user(db: Session, email: str, display_name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(email=email, display_name=display_name)
    db.add(user)
    db.flush()
    return user


def import_daily_metrics_csv(
    db: Session,
    csv_path: Path | str,
    *,
    user_email: str,
    user_name: str,
    source: str = "synthetic",
) -> dict[str, Any]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)
    required = {"date", "weight_kg"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    user = get_or_create_user(db, user_email, user_name)
    batch = SourceFile(
        user_id=user.id,
        source=source,
        filename=path.name,
        checksum=_file_checksum(path),
        row_count=len(df),
        metadata_json={"columns": list(df.columns)},
    )
    db.add(batch)
    db.flush()

    measurements_imported = 0
    contexts_imported = 0

    for _, row in df.iterrows():
        day = pd.to_datetime(row["date"]).date()
        ts = datetime.combine(day, datetime.min.time())

        for col, (metric_type, unit) in METRIC_COLUMNS.items():
            if col not in df.columns or pd.isna(row.get(col)):
                continue
            value = float(row[col])
            record_id = f"{path.stem}:{day.isoformat()}:{metric_type}"
            existing = db.scalar(
                select(Measurement).where(
                    Measurement.user_id == user.id,
                    Measurement.metric_type == metric_type,
                    Measurement.timestamp == ts,
                    Measurement.source == source,
                    Measurement.source_record_id == record_id,
                )
            )
            if existing:
                existing.value = value
                existing.unit = unit or METRIC_UNITS.get(metric_type, unit)
                existing.import_batch_id = batch.id
            else:
                db.add(
                    Measurement(
                        user_id=user.id,
                        metric_type=metric_type,
                        timestamp=ts,
                        value=value,
                        unit=unit or METRIC_UNITS.get(metric_type, "unknown"),
                        source=source,
                        source_record_id=record_id,
                        confidence=1.0,
                        import_batch_id=batch.id,
                    )
                )
                measurements_imported += 1

        context = db.scalar(
            select(DailyContext).where(DailyContext.user_id == user.id, DailyContext.date == day)
        )
        context_kwargs = {
            "menstrual_cycle_day": int(row["cycle_day"]) if "cycle_day" in df.columns and not pd.isna(row.get("cycle_day")) else None,
            "period_status": str(row["period_status"]) if "period_status" in df.columns and not pd.isna(row.get("period_status")) else None,
            "restaurant_meal": bool(int(row["restaurant_meal"])) if "restaurant_meal" in df.columns and not pd.isna(row.get("restaurant_meal")) else False,
            "alcohol_servings": float(row["alcohol_servings"]) if "alcohol_servings" in df.columns and not pd.isna(row.get("alcohol_servings")) else 0.0,
            "stress_rating": float(row["stress_rating"]) if "stress_rating" in df.columns and not pd.isna(row.get("stress_rating")) else None,
            "hunger_rating": float(row["hunger_rating"]) if "hunger_rating" in df.columns and not pd.isna(row.get("hunger_rating")) else None,
            "notes": str(row["notes"]) if "notes" in df.columns and not pd.isna(row.get("notes")) and str(row["notes"]).strip() else None,
            "source": source,
            "import_batch_id": batch.id,
        }
        if context:
            for key, value in context_kwargs.items():
                setattr(context, key, value)
        else:
            db.add(DailyContext(user_id=user.id, date=day, **context_kwargs))
            contexts_imported += 1

    db.commit()
    return {
        "user_id": user.id,
        "source": source,
        "filename": path.name,
        "measurements_imported": measurements_imported,
        "contexts_imported": contexts_imported,
        "import_batch_id": batch.id,
    }
