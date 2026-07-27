"""Hevy Pro API importer — workouts, body measurements, and account metadata."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import ExerciseSet, Measurement, SourceFile, User, Workout
from src.ingestion.csv_daily import get_or_create_user

HEVY_BASE_URL = "https://api.hevyapp.com"
HEVY_PAGE_SIZE = 10  # API max
DEFAULT_EXERCISE_HISTORY_LIMIT = 12


class HevyAPIError(RuntimeError):
    """Raised when the Hevy API returns an error response."""


class HevyClient:
    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=HEVY_BASE_URL, timeout=30.0)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HevyClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"api-key": self.api_key, "Accept": "application/json"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, headers=self._headers(), **kwargs)
        if response.status_code == 401:
            raise HevyAPIError("Hevy API key rejected (401). Check HC_HEVY_API_KEY / Hevy Pro.")
        if response.status_code >= 400:
            raise HevyAPIError(f"Hevy API error {response.status_code}: {response.text[:300]}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get_user_info(self) -> dict[str, Any]:
        payload = self._request("GET", "/v1/user/info")
        if not isinstance(payload, dict):
            raise HevyAPIError("Unexpected /v1/user/info response")
        return payload.get("data") if isinstance(payload.get("data"), dict) else payload

    def get_workout_count(self) -> int:
        payload = self._request("GET", "/v1/workouts/count")
        if isinstance(payload, dict):
            for key in ("workout_count", "count", "total"):
                if payload.get(key) is not None:
                    return int(payload[key])
        return 0

    def paginate(
        self,
        path: str,
        list_key: str,
        *,
        max_pages: int = 50,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        page_count = 1
        while page <= page_count and page <= max_pages:
            params: dict[str, Any] = {"page": page, "pageSize": HEVY_PAGE_SIZE}
            if extra_params:
                params.update(extra_params)
            payload = self._request("GET", path, params=params)
            if not isinstance(payload, dict):
                break
            page_count = int(payload.get("page_count") or 1)
            batch = payload.get(list_key) or []
            if not isinstance(batch, list):
                break
            rows.extend(item for item in batch if isinstance(item, dict))
            if not batch:
                break
            page += 1
        return rows

    def get_workouts(self, *, max_pages: int = 50) -> list[dict[str, Any]]:
        return self.paginate("/v1/workouts", "workouts", max_pages=max_pages)

    def get_body_measurements(self, *, max_pages: int = 50) -> list[dict[str, Any]]:
        return self.paginate("/v1/body_measurements", "body_measurements", max_pages=max_pages)

    def get_exercise_templates(self, *, max_pages: int = 20) -> list[dict[str, Any]]:
        return self.paginate("/v1/exercise_templates", "exercise_templates", max_pages=max_pages)

    def get_exercise_history(
        self,
        exercise_template_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        payload = self._request(
            "GET",
            f"/v1/exercise_history/{exercise_template_id}",
            params=params or None,
        )
        if not isinstance(payload, dict):
            return []
        history = payload.get("exercise_history") or []
        return [row for row in history if isinstance(row, dict)]


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 1e11:
            value = value / 1000.0
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
    if isinstance(value, str):
        try:
            parsed = date_parser.isoparse(value)
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return None


def _parse_day(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date_parser.isoparse(value).date()
        except (ValueError, TypeError):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    ts = _parse_ts(value)
    return ts.date() if ts else None


def _find_hevy_workout(db: Session, user_id: int, hevy_id: str) -> Optional[Workout]:
    for workout in db.scalars(
        select(Workout).where(Workout.user_id == user_id, Workout.source == "hevy")
    ):
        meta = workout.metadata_json or {}
        if meta.get("hevy_workout_id") == hevy_id:
            return workout
    return None


def fetch_hevy_user_info(api_key: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    with HevyClient(api_key, client=client) as hevy:
        return hevy.get_user_info()


def fetch_hevy_workouts(
    api_key: str,
    *,
    max_pages: int = 50,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    with HevyClient(api_key, client=client) as hevy:
        return hevy.get_workouts(max_pages=max_pages)


def _replace_sets(
    db: Session,
    workout: Workout,
    exercises: list[dict[str, Any]],
    *,
    template_titles: dict[str, str],
) -> int:
    for existing in db.scalars(
        select(ExerciseSet).where(ExerciseSet.workout_id == workout.id)
    ).all():
        db.delete(existing)
    db.flush()

    sets_imported = 0
    for exercise in exercises:
        if not isinstance(exercise, dict):
            continue
        template_id = str(exercise.get("exercise_template_id") or "")
        name = str(
            exercise.get("title")
            or template_titles.get(template_id)
            or template_id
            or "Unknown"
        )
        for raw_set in exercise.get("sets") or []:
            if not isinstance(raw_set, dict):
                continue
            idx = raw_set.get("index")
            set_number = int(idx) + 1 if idx is not None else sets_imported + 1
            set_type = str(raw_set.get("type") or raw_set.get("set_type") or "normal").lower()
            reps = raw_set.get("reps")
            weight = raw_set.get("weight_kg")
            rpe = raw_set.get("rpe")
            db.add(
                ExerciseSet(
                    workout_id=workout.id,
                    exercise_name=name[:128],
                    set_number=set_number,
                    weight=float(weight) if weight is not None else None,
                    repetitions=int(reps) if reps is not None else None,
                    rpe=float(rpe) if rpe is not None else None,
                    is_warmup=set_type == "warmup",
                    metadata_json={
                        "hevy_set_type": set_type,
                        "exercise_template_id": exercise.get("exercise_template_id"),
                        "distance_meters": raw_set.get("distance_meters"),
                        "duration_seconds": raw_set.get("duration_seconds"),
                        "notes": exercise.get("notes"),
                    },
                )
            )
            sets_imported += 1
    return sets_imported


def _upsert_measurement(
    db: Session,
    *,
    user_id: int,
    metric_type: str,
    unit: str,
    day: date,
    value: float,
    record_id: str,
    batch_id: int,
    metadata: dict[str, Any] | None = None,
) -> bool:
    noon = datetime(day.year, day.month, day.day, 12, 0, 0)
    existing = db.scalar(
        select(Measurement).where(
            Measurement.user_id == user_id,
            Measurement.metric_type == metric_type,
            Measurement.source == "hevy",
            Measurement.source_record_id == record_id,
        )
    )
    if existing:
        existing.value = value
        existing.timestamp = noon
        existing.import_batch_id = batch_id
        existing.metadata_json = metadata
        return False
    db.add(
        Measurement(
            user_id=user_id,
            metric_type=metric_type,
            timestamp=noon,
            value=value,
            unit=unit,
            source="hevy",
            source_record_id=record_id,
            confidence=0.85,
            metadata_json=metadata,
            import_batch_id=batch_id,
        )
    )
    return True


def _import_body_measurements(
    db: Session,
    *,
    user_id: int,
    rows: list[dict[str, Any]],
    batch_id: int,
) -> int:
    imported = 0
    for row in rows:
        day = _parse_day(row.get("date"))
        if day is None:
            continue
        if row.get("weight_kg") is not None:
            if _upsert_measurement(
                db,
                user_id=user_id,
                metric_type="weight",
                unit="kg",
                day=day,
                value=float(row["weight_kg"]),
                record_id=f"hevy-weight-{day.isoformat()}",
                batch_id=batch_id,
                metadata={"hevy_body_measurement": row},
            ):
                imported += 1
        fat = row.get("fat_percent")
        if fat is not None:
            if _upsert_measurement(
                db,
                user_id=user_id,
                metric_type="body_fat_percent",
                unit="percent",
                day=day,
                value=float(fat),
                record_id=f"hevy-fat-{day.isoformat()}",
                batch_id=batch_id,
                metadata={"hevy_body_measurement": row},
            ):
                imported += 1
    return imported


def _collect_exercise_template_ids(workouts: list[dict[str, Any]], limit: int) -> list[str]:
    seen: list[str] = []
    for workout in workouts:
        for exercise in workout.get("exercises") or []:
            if not isinstance(exercise, dict):
                continue
            template_id = str(exercise.get("exercise_template_id") or "").strip()
            if template_id and template_id not in seen:
                seen.append(template_id)
                if len(seen) >= limit:
                    return seen
    return seen


def _summarize_exercise_history(
  history_rows: list[dict[str, Any]],
  *,
  template_id: str,
  template_title: str,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for row in history_rows:
        if str(row.get("set_type") or row.get("type") or "normal").lower() == "warmup":
            continue
        weight = row.get("weight_kg")
        reps = row.get("reps")
        if weight is None:
            continue
        candidate = {
            "exercise_template_id": template_id,
            "exercise_title": template_title,
            "weight_kg": float(weight),
            "reps": int(reps) if reps is not None else None,
            "rpe": float(row["rpe"]) if row.get("rpe") is not None else None,
            "workout_start_time": row.get("workout_start_time"),
            "workout_title": row.get("workout_title"),
        }
        if best is None or candidate["weight_kg"] > best["weight_kg"]:
            best = candidate
    return best


def import_hevy_payload(
    db: Session,
    *,
    workouts: list[dict[str, Any]],
    body_measurements: list[dict[str, Any]] | None = None,
    user_info: dict[str, Any] | None = None,
    exercise_templates: list[dict[str, Any]] | None = None,
    exercise_history: dict[str, list[dict[str, Any]]] | None = None,
    workout_count: int | None = None,
    user_email: str,
    user_name: str,
) -> dict[str, Any]:
    """Persist Hevy API payloads into workouts, sets, and measurements."""
    user = get_or_create_user(db, user_email, user_name)
    template_titles = {
        str(row.get("id")): str(row.get("title"))
        for row in (exercise_templates or [])
        if row.get("id") and row.get("title")
    }
    personal_records: list[dict[str, Any]] = []
    for template_id, rows in (exercise_history or {}).items():
        summary = _summarize_exercise_history(
            rows,
            template_id=template_id,
            template_title=template_titles.get(template_id, template_id),
        )
        if summary:
            personal_records.append(summary)

    batch = SourceFile(
        user_id=user.id,
        source="hevy",
        filename=f"hevy-api-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json",
        checksum=None,
        row_count=len(workouts),
        metadata_json={
            "workout_count": len(workouts),
            "hevy_workout_count": workout_count,
            "hevy_account": user_info,
            "exercise_templates_cached": len(exercise_templates or []),
            "exercise_history_exercises": len(exercise_history or {}),
            "personal_records": personal_records,
        },
    )
    db.add(batch)
    db.flush()

    workouts_imported = 0
    workouts_updated = 0
    sets_imported = 0
    skipped = 0
    minutes_by_day: dict[date, float] = {}

    for payload in workouts:
        hevy_id = str(payload.get("id") or "").strip()
        start = _parse_ts(payload.get("start_time"))
        end = _parse_ts(payload.get("end_time"))
        if not hevy_id or start is None:
            skipped += 1
            continue

        duration_minutes = None
        if end is not None:
            duration_minutes = max((end - start).total_seconds() / 60.0, 0.0)
        if duration_minutes is not None and duration_minutes > 0:
            day = start.date()
            minutes_by_day[day] = minutes_by_day.get(day, 0.0) + duration_minutes

        title = payload.get("title") or "Hevy workout"
        meta = {
            "hevy_workout_id": hevy_id,
            "description": payload.get("description"),
            "updated_at": payload.get("updated_at"),
            "created_at": payload.get("created_at"),
        }

        existing = _find_hevy_workout(db, user.id, hevy_id)
        if existing:
            existing.start_time = start
            existing.end_time = end
            existing.workout_type = str(title)[:64]
            existing.duration_minutes = duration_minutes
            existing.import_batch_id = batch.id
            existing.metadata_json = meta
            existing.confidence = 1.0
            sets_imported += _replace_sets(
                db,
                existing,
                list(payload.get("exercises") or []),
                template_titles=template_titles,
            )
            workouts_updated += 1
        else:
            workout = Workout(
                user_id=user.id,
                start_time=start,
                end_time=end,
                workout_type=str(title)[:64],
                duration_minutes=duration_minutes,
                active_calories=None,
                average_heart_rate=None,
                source="hevy",
                confidence=1.0,
                metadata_json=meta,
                import_batch_id=batch.id,
            )
            db.add(workout)
            db.flush()
            sets_imported += _replace_sets(
                db,
                workout,
                list(payload.get("exercises") or []),
                template_titles=template_titles,
            )
            workouts_imported += 1

    strength_measurements = 0
    for day, minutes in minutes_by_day.items():
        if _upsert_measurement(
            db,
            user_id=user.id,
            metric_type="strength_minutes",
            unit="minutes",
            day=day,
            value=minutes,
            record_id=f"hevy-strength-{day.isoformat()}",
            batch_id=batch.id,
            metadata={"aggregated_from": "hevy_workouts"},
        ):
            strength_measurements += 1

    body_measurements_imported = _import_body_measurements(
        db,
        user_id=user.id,
        rows=body_measurements or [],
        batch_id=batch.id,
    )

    batch.row_count = (
        workouts_imported
        + workouts_updated
        + sets_imported
        + strength_measurements
        + body_measurements_imported
    )
    db.commit()
    return {
        "user_id": user.id,
        "source": "hevy",
        "hevy_username": _hevy_display_name(user_info),
        "hevy_workout_count": workout_count,
        "workouts_imported": workouts_imported,
        "workouts_updated": workouts_updated,
        "sets_imported": sets_imported,
        "strength_measurements_imported": strength_measurements,
        "body_measurements_imported": body_measurements_imported,
        "exercise_templates_cached": len(exercise_templates or []),
        "exercise_history_fetched": len(exercise_history or {}),
        "personal_records": personal_records,
        "skipped": skipped,
        "import_batch_id": batch.id,
    }


def import_hevy_workouts(
    db: Session,
    workouts: list[dict[str, Any]],
    *,
    user_email: str,
    user_name: str,
) -> dict[str, Any]:
    return import_hevy_payload(
        db,
        workouts=workouts,
        user_email=user_email,
        user_name=user_name,
    )


def _hevy_display_name(user_info: dict[str, Any] | None) -> str | None:
    if not user_info:
        return None
    for key in ("username", "full_name", "name", "email"):
        value = user_info.get(key)
        if value:
            return str(value)
    return None


def sync_hevy(
    db: Session,
    *,
    api_key: str,
    user_email: str,
    user_name: str,
    max_pages: int = 50,
    exercise_history_limit: int = DEFAULT_EXERCISE_HISTORY_LIMIT,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    with HevyClient(api_key, client=client) as hevy:
        user_info = hevy.get_user_info()
        workout_count = hevy.get_workout_count()
        workouts = hevy.get_workouts(max_pages=max_pages)
        body_measurements = hevy.get_body_measurements(max_pages=max_pages)
        exercise_templates = hevy.get_exercise_templates(max_pages=20)
        template_ids = _collect_exercise_template_ids(workouts, exercise_history_limit)
        exercise_history = {
            template_id: hevy.get_exercise_history(template_id)
            for template_id in template_ids
        }

    return import_hevy_payload(
        db,
        workouts=workouts,
        body_measurements=body_measurements,
        user_info=user_info,
        exercise_templates=exercise_templates,
        exercise_history=exercise_history,
        workout_count=workout_count,
        user_email=user_email,
        user_name=user_name,
    )
