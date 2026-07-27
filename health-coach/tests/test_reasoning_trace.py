"""Reasoning-trace engine tests."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.reasoning_trace import build_reasoning_trace
from src.db.models import DailySummary, User
from src.db.session import Base


def test_reasoning_trace_debates_and_change_mind():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    user = User(email="r@example.com", display_name="R")
    db.add(user)
    db.flush()

    start = date(2026, 7, 10)
    rows: list[DailySummary] = []
    for i in range(10):
        day = start + timedelta(days=i)
        rows.append(
            DailySummary(
                user_id=user.id,
                date=day,
                morning_weight_kg=93.4 + (0.15 if i == 9 else 0.0),
                weight_change_from_yesterday_kg=0.15 if i == 9 else -0.05,
                weight_7d_average=93.35,
                weight_trend_kg_per_week=-0.25,
                calories=1680 if i < 8 else None,
                sodium_mg=3500 if i == 8 else 2000,
                restaurant_meal=(i == 8),
                alcohol_servings=0.0,
                sleep_hours=7.0,
                strength_training_minutes=0,
                data_completeness_score=0.7,
            )
        )
        db.add(rows[-1])
    db.commit()

    trace = build_reasoning_trace(rows[-1], rows, calorie_target=1700.0, patterns=[])
    ids = [h.id for h in trace.hypotheses]
    assert "actual_fat_gain" in ids
    assert "temporary_water_retention" in ids
    assert abs(sum(h.probability for h in trace.hypotheses) - 1.0) < 1e-3

    fat = next(h for h in trace.hypotheses if h.id == "actual_fat_gain")
    water = next(h for h in trace.hypotheses if h.id == "temporary_water_retention")
    assert fat.probability < water.probability
    assert any("implausible" in e.lower() or "7700" in e for e in fat.evidence_against)
    assert trace.what_would_change_my_mind
    assert "5 consecutive" in trace.what_would_change_my_mind or "surplus" in trace.what_would_change_my_mind.lower()
    assert "hypothesis" in trace.recommendations[0].rationale.lower() or trace.primary_hypothesis_id
    assert trace.energy_balance.stance in {
        "likely_deficit",
        "roughly_maintenance_range",
        "unclear",
        "possible_surplus",
        "unknown",
    }
    db.close()
