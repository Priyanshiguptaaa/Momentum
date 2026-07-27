"""Tests for check-ins and decision ranking."""

from datetime import UTC, datetime, timedelta

from src.analytics.check_ins import check_in_summary, create_check_in, detect_decision_patterns
from src.analytics.decision_ranker import rank_decision_opportunities
from src.db.models import DailySummary


def test_check_in_create_and_summary(loaded_db):
    db, _ = loaded_db
    create_check_in(
        db,
        {
            "period": "evening",
            "hunger": 8,
            "energy": 4,
            "stress": 6,
            "cravings": 7,
            "bloating": 2,
            "digestion": "normal",
        },
    )
    summary = check_in_summary(db)
    assert summary["count"] >= 1
    assert summary["averages"].get("hunger") == 8.0


def test_poor_sleep_hunger_pattern(loaded_db):
    db, user_id = loaded_db
    # Attach sleep to recent summaries and evening check-ins
    rows = list(
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .limit(10)
    )
    for i, r in enumerate(rows[:6]):
        r.sleep_hours = 5.5 if i % 2 == 0 else 8.0
        evening = datetime(r.date.year, r.date.month, r.date.day, 20, 0, tzinfo=UTC)
        create_check_in(
            db,
            {
                "logged_at": evening.isoformat(),
                "period": "evening",
                "hunger": 8 if i % 2 == 0 else 4,
                "cravings": 7 if i % 2 == 0 else 3,
            },
        )
    db.commit()
    patterns = detect_decision_patterns(db)
    keys = {p["key"] for p in patterns}
    assert "poor_sleep_evening_hunger" in keys or "poor_sleep_cravings" in keys


def test_decision_ranking_returns_ranked(loaded_db):
    db, _ = loaded_db
    ranking = rank_decision_opportunities(db)
    assert ranking.mindset
    assert isinstance(ranking.opportunities, list)
    # Synthetic data usually has sleep/steps/protein — expect at least one opportunity
    assert len(ranking.opportunities) >= 1
    top = ranking.opportunities[0]
    assert top.expected_impact in ("high", "medium", "low")
    assert 0 <= top.confidence <= 1


def test_api_check_ins_and_decisions(client):
    res = client.post(
        "/check-ins",
        json={"hunger": 6, "energy": 5, "stress": 4, "cravings": 3, "bloating": 1},
        headers={"X-API-Key": "test-key"},
    )
    assert res.status_code == 200
    assert res.json()["hunger"] == 6
    dec = client.get("/decisions", headers={"X-API-Key": "test-key"})
    assert dec.status_code == 200
    body = dec.json()
    assert "opportunities" in body
    assert "mindset" in body
