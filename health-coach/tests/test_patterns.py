"""Physiology pattern detection tests."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.analytics.patterns import refresh_physiology_patterns
from src.db.models import DailySummary, PhysiologyPattern, User
from src.db.session import Base


def _session():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def test_restaurant_pattern_detection():
    db = _session()
    user = User(email="p@example.com", display_name="P")
    db.add(user)
    db.flush()

    start = date(2026, 7, 1)
    # Build 20 days; restaurant on days 0,3,6,9,12 with +0.8 next morning.
    for i in range(20):
        day = start + timedelta(days=i)
        prev_restaurant = i > 0 and ((i - 1) % 3 == 0)
        restaurant = i % 3 == 0 and i < 15
        db.add(
            DailySummary(
                user_id=user.id,
                date=day,
                morning_weight_kg=93.0 + i * 0.01,
                weight_change_from_yesterday_kg=0.8 if prev_restaurant else 0.05,
                restaurant_meal=restaurant,
                alcohol_servings=0.0,
                sodium_mg=2200,
                strength_training_minutes=0,
                sleep_hours=7.2,
                data_completeness_score=0.8,
            )
        )
    db.commit()

    patterns = refresh_physiology_patterns(db, user.id)
    keys = {p.pattern_key for p in patterns}
    assert "restaurant_next_morning_bump" in keys
    row = db.scalar(
        select(PhysiologyPattern).where(
            PhysiologyPattern.user_id == user.id,
            PhysiologyPattern.pattern_key == "restaurant_next_morning_bump",
        )
    )
    assert row is not None
    assert row.support_count >= 3
    assert row.typical_delta is not None and row.typical_delta > 0.3
    db.close()
