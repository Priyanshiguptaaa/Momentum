"""Tests for body-derived energy plan / calorie target."""

from src.analytics.energy_plan import estimate_energy_plan
from src.coaching.preferences import get_calorie_target, get_preferences, update_preferences
from src.db.models import DailySummary


def test_energy_plan_from_intake_and_trend(loaded_db):
    db, user_id = loaded_db
    rows = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .limit(14)
        .all()
    )
    for r in rows:
        r.calories = 1800
        r.weight_trend_kg_per_week = -0.4  # losing → maintenance above intake
    db.commit()

    # Clear any manual override
    update_preferences(db, mode="auto")
    plan = estimate_energy_plan(db)
    assert plan["suggested_target"] is not None
    assert plan["source"] in ("body_data", "recent_intake", "seed_default")
    # Losing at 1800 → maintenance should be higher than 1800
    if plan["estimated_maintenance"]:
        assert plan["estimated_maintenance"] > 1800

    prefs = get_preferences(db)
    assert prefs["mode"] == "auto"
    assert get_calorie_target(db) == prefs["calorie_target"]


def test_manual_override_then_auto(loaded_db):
    db, _ = loaded_db
    update_preferences(db, calorie_target=2000)
    prefs = get_preferences(db)
    assert prefs["mode"] == "manual"
    assert prefs["calorie_target"] == 2000

    update_preferences(db, mode="auto")
    prefs2 = get_preferences(db)
    assert prefs2["mode"] == "auto"
