"""Ingest Health Auto Export (iOS) REST API JSON payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DailyContext, Measurement, SourceFile, User, Workout
from src.ingestion.csv_daily import get_or_create_user
from src.normalization.units import METRIC_UNITS, normalize_weight_to_kg

# Health Auto Export metric name → (internal metric_type, default unit)
HAE_METRIC_MAP: dict[str, tuple[str, str]] = {
    "weight_body_mass": ("weight", "kg"),
    "step_count": ("steps", "count"),
    "active_energy": ("active_energy", "kcal"),
    "basal_energy_burned": ("resting_energy", "kcal"),
    "dietary_energy": ("calories", "kcal"),
    "protein": ("protein", "g"),
    "fiber": ("fiber", "g"),
    "sodium": ("sodium", "mg"),
    "carbohydrates": ("carbohydrates", "g"),
    "total_fat": ("fat", "g"),
    "resting_heart_rate": ("resting_heart_rate", "bpm"),
    "sleep_analysis": ("sleep_duration", "hours"),
    "number_of_alcoholic_beverages": ("alcohol_servings", "count"),
}


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date_parser.parse(text)


def _qty(entry: dict[str, Any]) -> Optional[float]:
    for key in ("qty", "Avg", "avg", "totalSleep", "asleep"):
        if key in entry and entry[key] is not None:
            try:
                return float(entry[key])
            except (TypeError, ValueError):
                continue
    return None


def _source_label(entry: dict[str, Any], fallback: str = "apple_health") -> str:
    raw = entry.get("source")
    if not raw:
        return fallback
    text = str(raw).lower()
    if "macrofactor" in text or "macro factor" in text:
        return "macrofactor"
    if "vesync" in text or "etekcity" in text:
        return "smart_scale"
    if "garmin" in text:
        return "garmin"
    if "hevy" in text:
        return "hevy"
    if "watch" in text:
        return "apple_watch"
    if "iphone" in text:
        return "iphone"
    return fallback


def _normalize_value(metric_type: str, value: float, unit: str) -> tuple[float, str]:
    unit_l = (unit or "").lower()
    if metric_type == "weight":
        try:
            return normalize_weight_to_kg(value, unit or "kg"), "kg"
        except ValueError:
            # Some exports omit unit or use "kg" already.
            if unit_l in {"lb", "lbs"}:
                return value * 0.45359237, "kg"
            return value, "kg"
    if metric_type == "sleep_duration":
        # Aggregated HAE sleep is usually hours; raw qty may be hours already.
        if unit_l in {"hr", "hrs", "hour", "hours", ""}:
            return value, "hours"
        if unit_l in {"min", "mins", "minute", "minutes"}:
            return value / 60.0, "hours"
        return value, "hours"
    if metric_type in {"active_energy", "resting_energy", "calories"}:
        if unit_l in {"kj", "kilojoule", "kilojoules"}:
            return value / 4.184, "kcal"
        return value, "kcal"
    return value, METRIC_UNITS.get(metric_type, unit or "unknown")


def ingest_health_auto_export(
    db: Session,
    payload: dict[str, Any],
    *,
    user_email: str,
    user_name: str,
) -> dict[str, Any]:
    """Parse a Health Auto Export JSON body and upsert measurements/workouts/context."""
    data = payload.get("data", payload)
    metrics = data.get("metrics") or []
    workouts = data.get("workouts") or []
    cycle_tracking = data.get("cycleTracking") or []

    user = get_or_create_user(db, user_email, user_name)
    batch = SourceFile(
        user_id=user.id,
        source="health_auto_export",
        filename=f"hae_sync_{datetime.now(UTC).isoformat(timespec='seconds')}",
        row_count=0,
        metadata_json={
            "metric_groups": len(metrics),
            "workouts": len(workouts),
            "cycle_tracking": len(cycle_tracking),
        },
    )
    db.add(batch)
    db.flush()

    measurements_imported = 0
    workouts_imported = 0
    contexts_touched = 0
    skipped = 0

    for group in metrics:
        name = str(group.get("name") or "").strip().lower()
        units = str(group.get("units") or "")
        mapped = HAE_METRIC_MAP.get(name)
        if not mapped:
            skipped += 1
            continue
        metric_type, default_unit = mapped
        entries = group.get("data") or []
        for entry in entries:
            if not isinstance(entry, dict):
                skipped += 1
                continue
            ts = _parse_ts(entry.get("date") or entry.get("sleepEnd") or entry.get("endDate"))
            value = _qty(entry)
            if ts is None or value is None:
                skipped += 1
                continue
            value, unit = _normalize_value(metric_type, value, units or default_unit)
            source = _source_label(entry)
            record_id = f"hae:{metric_type}:{ts.isoformat()}:{source}"

            if metric_type == "alcohol_servings":
                day = ts.date()
                ctx = db.scalar(
                    select(DailyContext).where(
                        DailyContext.user_id == user.id, DailyContext.date == day
                    )
                )
                if ctx:
                    ctx.alcohol_servings = float(value)
                    ctx.import_batch_id = batch.id
                else:
                    db.add(
                        DailyContext(
                            user_id=user.id,
                            date=day,
                            alcohol_servings=float(value),
                            source=source,
                            import_batch_id=batch.id,
                        )
                    )
                    contexts_touched += 1
                continue

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
                existing.unit = unit
                existing.import_batch_id = batch.id
                existing.metadata_json = {"hae_name": name, "raw": entry}
            else:
                db.add(
                    Measurement(
                        user_id=user.id,
                        metric_type=metric_type,
                        timestamp=ts,
                        value=value,
                        unit=unit,
                        source=source,
                        source_record_id=record_id,
                        confidence=0.9,
                        metadata_json={"hae_name": name, "raw_keys": list(entry.keys())},
                        import_batch_id=batch.id,
                    )
                )
                measurements_imported += 1

    for workout in workouts:
        if not isinstance(workout, dict):
            skipped += 1
            continue
        start = _parse_ts(workout.get("start"))
        end = _parse_ts(workout.get("end"))
        if start is None:
            skipped += 1
            continue
        wid = str(workout.get("id") or f"{start.isoformat()}:{workout.get('name')}")
        existing = db.scalar(
            select(Workout).where(
                Workout.user_id == user.id,
                Workout.source == "apple_health",
                Workout.start_time == start,
            )
        )
        duration_minutes = None
        if workout.get("duration") is not None:
            duration_minutes = float(workout["duration"]) / 60.0
        elif end is not None:
            duration_minutes = (end - start).total_seconds() / 60.0

        active_cal = None
        energy = workout.get("activeEnergyBurned") or workout.get("activeEnergy") or workout.get("totalEnergy")
        if isinstance(energy, dict) and energy.get("qty") is not None:
            active_cal = float(energy["qty"])
            if str(energy.get("units", "")).lower() in {"kj", "kilojoule", "kilojoules"}:
                active_cal = active_cal / 4.184

        avg_hr = None
        hr = workout.get("avgHeartRate")
        if isinstance(hr, dict) and hr.get("qty") is not None:
            avg_hr = float(hr["qty"])

        if existing:
            existing.end_time = end
            existing.workout_type = workout.get("name")
            existing.duration_minutes = duration_minutes
            existing.active_calories = active_cal
            existing.average_heart_rate = avg_hr
            existing.import_batch_id = batch.id
            existing.metadata_json = {"hae_workout_id": wid}
        else:
            db.add(
                Workout(
                    user_id=user.id,
                    start_time=start,
                    end_time=end,
                    workout_type=workout.get("name"),
                    duration_minutes=duration_minutes,
                    active_calories=active_cal,
                    average_heart_rate=avg_hr,
                    source="apple_health",
                    confidence=0.9,
                    metadata_json={"hae_workout_id": wid},
                    import_batch_id=batch.id,
                )
            )
            workouts_imported += 1

    # Lightweight cycle context if present.
    for cycle in cycle_tracking:
        if not isinstance(cycle, dict):
            continue
        day = _parse_ts(cycle.get("date") or cycle.get("start") or cycle.get("day"))
        if day is None:
            continue
        day_d = day.date()
        ctx = db.scalar(
            select(DailyContext).where(DailyContext.user_id == user.id, DailyContext.date == day_d)
        )
        status = cycle.get("period_status") or cycle.get("flow") or cycle.get("value")
        kwargs = {
            "period_status": str(status) if status is not None else None,
            "menstrual_cycle_day": int(cycle["cycleDay"])
            if cycle.get("cycleDay") is not None
            else None,
            "source": "apple_health",
            "import_batch_id": batch.id,
            "metadata_json": {"hae_cycle": cycle},
        }
        if ctx:
            for key, value in kwargs.items():
                if value is not None:
                    setattr(ctx, key, value)
        else:
            db.add(DailyContext(user_id=user.id, date=day_d, **kwargs))
            contexts_touched += 1

    batch.row_count = measurements_imported + workouts_imported + contexts_touched
    db.commit()
    return {
        "user_id": user.id,
        "source": "health_auto_export",
        "measurements_imported": measurements_imported,
        "workouts_imported": workouts_imported,
        "contexts_imported": contexts_touched,
        "skipped_groups_or_rows": skipped,
        "import_batch_id": batch.id,
    }
