"""Hevy API importer tests (mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.daily_summary import rebuild_daily_summaries
from src.db.models import DailySummary, ExerciseSet, Measurement, Workout
from src.db.session import Base
from src.ingestion.hevy import import_hevy_payload, import_hevy_workouts, sync_hevy


SAMPLE_WORKOUT = {
    "id": "aa6b6d62-3857-45f2-97be-15db42638a59",
    "title": "Push Day",
    "description": "felt strong",
    "start_time": "2026-07-20T09:00:00Z",
    "end_time": "2026-07-20T10:05:00Z",
    "updated_at": "2026-07-20T10:05:00Z",
    "created_at": "2026-07-20T09:00:00Z",
    "exercises": [
        {
            "index": 0,
            "title": "Bench Press (Barbell)",
            "notes": "pause",
            "exercise_template_id": "79D0BB3A",
            "sets": [
                {"index": 0, "type": "warmup", "weight_kg": 40, "reps": 10, "rpe": None},
                {"index": 1, "type": "normal", "weight_kg": 80, "reps": 5, "rpe": 8.5},
            ],
        }
    ],
}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_import_hevy_workouts_stores_sets_and_strength_minutes(db):
    result = import_hevy_workouts(
        db,
        [SAMPLE_WORKOUT],
        user_email="demo@healthcoach.local",
        user_name="Demo User",
    )
    assert result["workouts_imported"] == 1
    assert result["sets_imported"] == 2
    assert result["strength_measurements_imported"] == 1

    workout = db.scalar(select(Workout).where(Workout.source == "hevy"))
    assert workout is not None
    assert workout.workout_type == "Push Day"
    assert workout.duration_minutes == pytest.approx(65.0)

    sets = list(db.scalars(select(ExerciseSet).where(ExerciseSet.workout_id == workout.id)))
    assert len(sets) == 2
    assert any(s.is_warmup for s in sets)
    working = next(s for s in sets if not s.is_warmup)
    assert working.weight == pytest.approx(80.0)
    assert working.repetitions == 5

    strength = db.scalar(
        select(Measurement).where(
            Measurement.metric_type == "strength_minutes", Measurement.source == "hevy"
        )
    )
    assert strength is not None
    assert strength.value == pytest.approx(65.0)

    rebuild_daily_summaries(db, result["user_id"])
    summary = db.scalar(select(DailySummary))
    assert summary is not None
    assert summary.strength_training_minutes == pytest.approx(65.0)


def test_import_hevy_payload_imports_body_measurements_and_account(db):
    result = import_hevy_payload(
        db,
        workouts=[SAMPLE_WORKOUT],
        body_measurements=[{"date": "2026-07-20", "weight_kg": 72.4, "fat_percent": 18.2}],
        user_info={"username": "pri_test"},
        exercise_templates=[{"id": "79D0BB3A", "title": "Bench Press (Barbell)"}],
        exercise_history={
            "79D0BB3A": [
                {
                    "set_type": "normal",
                    "weight_kg": 85,
                    "reps": 5,
                    "workout_start_time": "2026-07-18T09:00:00Z",
                    "workout_title": "Push Day",
                }
            ]
        },
        workout_count=42,
        user_email="demo@healthcoach.local",
        user_name="Demo User",
    )
    assert result["hevy_username"] == "pri_test"
    assert result["hevy_workout_count"] == 42
    assert result["body_measurements_imported"] == 2
    assert result["exercise_templates_cached"] == 1
    assert result["exercise_history_fetched"] == 1
    assert result["personal_records"][0]["weight_kg"] == pytest.approx(85.0)

    weight = db.scalar(
        select(Measurement).where(
            Measurement.metric_type == "weight",
            Measurement.source == "hevy",
            Measurement.source_record_id == "hevy-weight-2026-07-20",
        )
    )
    assert weight is not None
    assert weight.value == pytest.approx(72.4)


def test_import_hevy_is_idempotent_by_workout_id(db):
    import_hevy_workouts(
        db,
        [SAMPLE_WORKOUT],
        user_email="demo@healthcoach.local",
        user_name="Demo User",
    )
    updated = dict(SAMPLE_WORKOUT)
    updated["title"] = "Push Day v2"
    updated["exercises"] = [
        {
            "index": 0,
            "title": "Overhead Press (Barbell)",
            "exercise_template_id": "7B8D84E8",
            "sets": [{"index": 0, "type": "normal", "weight_kg": 50, "reps": 8, "rpe": 7}],
        }
    ]
    result = import_hevy_workouts(
        db,
        [updated],
        user_email="demo@healthcoach.local",
        user_name="Demo User",
    )
    assert result["workouts_imported"] == 0
    assert result["workouts_updated"] == 1
    assert result["sets_imported"] == 1

    workouts = list(db.scalars(select(Workout).where(Workout.source == "hevy")))
    assert len(workouts) == 1
    assert workouts[0].workout_type == "Push Day v2"
    sets = list(db.scalars(select(ExerciseSet)))
    assert len(sets) == 1
    assert sets[0].exercise_name.startswith("Overhead")


def test_sync_hevy_uses_api_key_header(db):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("api-key") == "test-hevy-key"
        if request.url.path == "/v1/user/info":
            return httpx.Response(200, json={"data": {"username": "tester"}})
        if request.url.path == "/v1/workouts/count":
            return httpx.Response(200, json={"workout_count": 1})
        if request.url.path == "/v1/workouts":
            return httpx.Response(
                200,
                json={"page": 1, "page_count": 1, "workouts": [SAMPLE_WORKOUT]},
            )
        if request.url.path == "/v1/body_measurements":
            return httpx.Response(200, json={"page": 1, "page_count": 1, "body_measurements": []})
        if request.url.path == "/v1/exercise_templates":
            return httpx.Response(200, json={"page": 1, "page_count": 1, "exercise_templates": []})
        if request.url.path.startswith("/v1/exercise_history/"):
            return httpx.Response(200, json={"exercise_history": []})
        return httpx.Response(404, json={"error": "unexpected path"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://api.hevyapp.com") as client:
        result = sync_hevy(
            db,
            api_key="test-hevy-key",
            user_email="demo@healthcoach.local",
            user_name="Demo User",
            client=client,
            exercise_history_limit=1,
        )
    assert result["workouts_imported"] == 1
    assert result["hevy_username"] == "tester"
