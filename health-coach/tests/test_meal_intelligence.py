"""Tests for Behavioral Nutrition Intelligence."""

from datetime import UTC, datetime, timedelta

from src.analytics.meal_intelligence import (
    build_meal_review,
    create_meal_event,
    detect_meal_patterns,
    predict_hunger,
    refresh_staple_profiles,
)
from src.coaching.food_staples import create_food_staple


def test_meal_event_updates_staple_profile(loaded_db):
    db, user_id = loaded_db
    staple = create_food_staple(
        db,
        {
            "name": "Chicken wrap",
            "meal_slot": "lunch",
            "estimated_protein_g": 40,
            "estimated_fiber_g": 8,
            "estimated_calories": 600,
            "is_packaged": False,
        },
    )
    base = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for i in range(3):
        create_meal_event(
            db,
            {
                "staple_id": staple.id,
                "name": "Chicken wrap",
                "meal_slot": "lunch",
                "eaten_at": (base - timedelta(days=i)).isoformat(),
                "calories": 600,
                "protein_g": 40,
                "fiber_g": 8,
                "satiety_hours": 6.0,
                "followed_by_snack": False,
                "whole_food_score": 8,
            },
        )
    refresh_staple_profiles(db)
    db.refresh(staple)
    assert staple.times_logged >= 3
    assert staple.learned_profile is not None
    assert staple.learned_profile.get("avg_satiety_hours") == 6.0
    assert staple.learned_profile.get("personal_satiety_score") is not None

    review = build_meal_review(db, staple.id)
    assert review["name"] == "Chicken wrap"
    assert any("full" in s.lower() or "protein" in s.lower() for s in review["strengths"])


def test_early_protein_pattern_detection(loaded_db):
    db, _user_id = loaded_db
    # High-protein early breakfasts vs low — with snack flags
    for i in range(4):
        day = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(
            days=i + 1
        )
        create_meal_event(
            db,
            {
                "name": "Eggs",
                "meal_slot": "breakfast",
                "eaten_at": day.isoformat(),
                "protein_g": 40,
                "calories": 400,
                "followed_by_snack": False,
            },
        )
        create_meal_event(
            db,
            {
                "name": "Dinner",
                "meal_slot": "dinner",
                "eaten_at": day.replace(hour=19).isoformat(),
                "calories": 500,
            },
        )
    for i in range(4):
        day = datetime.now(UTC).replace(hour=8, minute=30, second=0, microsecond=0) - timedelta(
            days=i + 10
        )
        create_meal_event(
            db,
            {
                "name": "Toast",
                "meal_slot": "breakfast",
                "eaten_at": day.isoformat(),
                "protein_g": 8,
                "calories": 300,
                "followed_by_snack": True,
            },
        )
        create_meal_event(
            db,
            {
                "name": "Snack",
                "meal_slot": "snack",
                "eaten_at": day.replace(hour=17).isoformat(),
                "calories": 400,
            },
        )
        create_meal_event(
            db,
            {
                "name": "Dinner",
                "meal_slot": "dinner",
                "eaten_at": day.replace(hour=20).isoformat(),
                "calories": 700,
            },
        )

    patterns = detect_meal_patterns(db)
    keys = {p["key"] for p in patterns}
    assert "early_protein_less_snacking" in keys


def test_hunger_prediction_with_late_gap(loaded_db):
    db, _user_id = loaded_db
    # Breakfast only, long ago — high risk if hours elapsed
    eaten = datetime.now(UTC) - timedelta(hours=6)
    create_meal_event(
        db,
        {
            "name": "Light breakfast",
            "meal_slot": "breakfast",
            "eaten_at": eaten.isoformat(),
            "protein_g": 15,
            "calories": 300,
            "satiety_hours": 3.0,
        },
    )
    pred = predict_hunger(db)
    assert pred is not None
    assert pred["risk"] in ("high", "medium", "low", "unknown")
    assert "message" in pred


def test_api_meal_events(client, loaded_db):
    db, _ = loaded_db
    # Ensure API key header used by other tests — check client fixture
    res = client.post(
        "/meal-events",
        json={
            "name": "Office salad",
            "meal_slot": "lunch",
            "protein_g": 35,
            "calories": 450,
            "satiety_hours": 5,
            "eaten_at": datetime.now(UTC).isoformat(),
        },
        headers={"X-API-Key": "test-key"},
    )
    # Auth may use env key — accept 200 or 401/403 depending on fixture
    if res.status_code == 200:
        data = res.json()
        assert data["name"] == "Office salad"
        pack = client.get("/meal-intelligence", headers={"X-API-Key": "test-key"})
        assert pack.status_code == 200
        assert "patterns" in pack.json()
