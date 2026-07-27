"""End-to-end and unit tests for the v0 vertical slice."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.analytics.hypotheses import evaluate_weight_hypotheses
from src.analytics.weight_trend import attach_weight_trends
from src.coaching.explanation import explain_weight_for_date
from src.db.models import DailySummary


def test_weight_trends_attach():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-07-01", periods=10, freq="D"),
            "morning_weight_kg": [94.2, 94.0, 93.9, 93.8, 93.7, 93.6, 93.5, 93.4, 93.3, 93.2],
        }
    )
    out = attach_weight_trends(df)
    assert out["weight_7d_average"].notna().sum() >= 5
    assert out.loc[9, "weight_change_from_yesterday_kg"] == pytest.approx(-0.1)


def test_import_and_summaries(loaded_db):
    db, user_id = loaded_db
    summaries = db.query(DailySummary).filter(DailySummary.user_id == user_id).all()
    assert len(summaries) == 21
    day = next(s for s in summaries if s.date == date(2026, 7, 8))
    assert day.morning_weight_kg == pytest.approx(94.6)
    assert day.weight_change_from_yesterday_kg == pytest.approx(0.9)


def test_restaurant_day_prefers_water_retention(loaded_db):
    db, user_id = loaded_db
    explanation = explain_weight_for_date(db, date(2026, 7, 8), user_id=user_id)
    assert explanation.primary_hypothesis == "temporary_water_retention"
    assert explanation.confidence >= 0.5
    assert any(
        "restaurant" in e.lower() or "sodium" in e.lower()
        for e in explanation.hypotheses[0].evidence
    )
    assert any(
        "one weigh-in" in r.action.lower() or "weigh-in" in r.action.lower()
        for r in explanation.recommendations
    )


def test_downward_trend_day_not_aggressive_surplus(loaded_db):
    db, user_id = loaded_db
    explanation = explain_weight_for_date(db, date(2026, 7, 16), user_id=user_id)
    names = [h.name for h in explanation.hypotheses]
    assert "possible_calorie_surplus" in names
    surplus = next(h for h in explanation.hypotheses if h.name == "possible_calorie_surplus")
    assert (
        surplus.score < explanation.hypotheses[0].score
        or explanation.primary_hypothesis != "possible_calorie_surplus"
    )


def test_api_weight_explanation(client):
    response = client.get("/weight-explanation/2026-07-08")
    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-07-08"
    assert payload["primary_hypothesis"] == "temporary_water_retention"
    assert len(payload["hypotheses"]) >= 3
    assert len(payload["recommendations"]) >= 1


def test_api_daily_summary(client):
    response = client.get("/daily-summary/2026-07-08")
    assert response.status_code == 200
    assert response.json()["summary"]["weight_kg"] == pytest.approx(94.6)


def test_hypothesis_scoring_unit():
    today = DailySummary(
        user_id=1,
        date=date(2026, 7, 8),
        morning_weight_kg=94.6,
        weight_change_from_yesterday_kg=0.9,
        weight_trend_kg_per_week=-0.4,
        calories=1650,
        protein_g=150,
        sodium_mg=1900,
        restaurant_meal=False,
        alcohol_servings=0,
        data_completeness_score=0.95,
    )
    yesterday = DailySummary(
        user_id=1,
        date=date(2026, 7, 7),
        morning_weight_kg=93.7,
        calories=1780,
        sodium_mg=3200,
        restaurant_meal=True,
        alcohol_servings=1,
        data_completeness_score=0.95,
    )
    results = evaluate_weight_hypotheses(today, [yesterday, today], calorie_target=1700)
    assert results[0].name == "temporary_water_retention"
