"""Tests for Health Auto Export webhook ingest."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.db.models import DailySummary, Measurement
from src.db.session import Base, get_db


SAMPLE_HAE_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "weight_body_mass",
                "units": "kg",
                "data": [
                    {
                        "qty": 93.6,
                        "date": "2026-07-20 07:00:00 +0000",
                        "source": "VeSync",
                    }
                ],
            },
            {
                "name": "dietary_energy",
                "units": "kcal",
                "data": [
                    {
                        "qty": 1650,
                        "date": "2026-07-20 23:59:00 +0000",
                        "source": "MacroFactor",
                    }
                ],
            },
            {
                "name": "protein",
                "units": "g",
                "data": [
                    {
                        "qty": 150,
                        "date": "2026-07-20 23:59:00 +0000",
                        "source": "MacroFactor",
                    }
                ],
            },
            {
                "name": "step_count",
                "units": "count",
                "data": [
                    {
                        "qty": 10800,
                        "date": "2026-07-20 23:59:00 +0000",
                        "source": "Apple Watch",
                    }
                ],
            },
            {
                "name": "sleep_analysis",
                "units": "hr",
                "data": [
                    {
                        "date": "2026-07-20",
                        "totalSleep": 7.4,
                        "asleep": 7.1,
                        "source": "Apple Watch",
                    }
                ],
            },
        ],
        "workouts": [
            {
                "id": "w1",
                "name": "Traditional Strength Training",
                "start": "2026-07-19 17:00:00 +0000",
                "end": "2026-07-19 18:00:00 +0000",
                "duration": 3600,
                "activeEnergyBurned": {"qty": 220, "units": "kcal"},
            }
        ],
    }
}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSession()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client, session
    app.dependency_overrides.clear()
    session.close()


def test_health_auto_export_sync(client, monkeypatch):
    test_client, session = client
    monkeypatch.setenv("HC_SYNC_API_KEY", "test-secret")
    from src.db.config import settings

    settings.sync_api_key = "test-secret"

    denied = test_client.post("/sync/health-auto-export", json=SAMPLE_HAE_PAYLOAD)
    assert denied.status_code == 401

    response = test_client.post(
        "/sync/health-auto-export",
        json=SAMPLE_HAE_PAYLOAD,
        headers={"X-API-Key": "test-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["measurements_imported"] >= 4
    assert body["workouts_imported"] == 1
    assert body["summaries_built"] >= 1

    weights = session.scalars(select(Measurement).where(Measurement.metric_type == "weight")).all()
    assert any(m.source == "smart_scale" and m.value == pytest.approx(93.6) for m in weights)

    calories = session.scalars(
        select(Measurement).where(Measurement.metric_type == "calories")
    ).all()
    assert any(m.source == "macrofactor" and m.value == pytest.approx(1650) for m in calories)

    summary = session.scalar(
        select(DailySummary).where(DailySummary.date == date(2026, 7, 20))
    )
    assert summary is not None
    assert summary.morning_weight_kg == pytest.approx(93.6)
    assert summary.calories == pytest.approx(1650)
    assert summary.protein_g == pytest.approx(150)
    assert summary.steps == pytest.approx(10800)
