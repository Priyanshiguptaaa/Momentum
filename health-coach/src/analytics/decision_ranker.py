"""Rank decision opportunities by expected impact × confidence.

Mindset: Can we estimate well enough to make a better decision than the user alone?
Not: Do we have perfect data?
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.check_ins import check_in_summary
from src.analytics.meal_intelligence import build_bni_pack
from src.db.config import settings
from src.db.models import DailySummary, User
from src.models.schemas import DecisionOpportunity, DecisionRanking


IMPACT_ORDER = {"high": 3, "medium": 2, "low": 1}


def _primary_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise LookupError("No users found.")
    return user


def _recent_summaries(db: Session, user_id: int, n: int = 14) -> list[DailySummary]:
    return list(
        db.scalars(
            select(DailySummary)
            .where(DailySummary.user_id == user_id)
            .order_by(DailySummary.date.desc())
            .limit(n)
        ).all()
    )


def rank_decision_opportunities(db: Session) -> DecisionRanking:
    """Produce a ranked list of tuneable decisions with impact + confidence."""
    opportunities: list[DecisionOpportunity] = []
    missing: list[str] = []

    try:
        user = _primary_user(db)
    except LookupError:
        return DecisionRanking(
            opportunities=[],
            mindset=(
                "Can we estimate well enough to make a better decision than the user alone? "
                "Import data to start."
            ),
            missing_for_better=[],
        )

    rows = _recent_summaries(db, user.id)
    if not rows:
        return DecisionRanking(
            opportunities=[],
            mindset="Import weight/nutrition/activity to rank decisions.",
            missing_for_better=["daily summaries"],
        )

    sleep_vals = [float(r.sleep_hours) for r in rows if r.sleep_hours is not None]
    fiber_vals = [float(r.fiber_g) for r in rows if r.fiber_g is not None]
    protein_vals = [float(r.protein_g) for r in rows if r.protein_g is not None]
    sodium_vals = [float(r.sodium_mg) for r in rows if r.sodium_mg is not None]
    step_vals = [float(r.steps) for r in rows if r.steps is not None]
    calorie_vals = [float(r.calories) for r in rows if r.calories is not None]
    trends = [float(r.weight_trend_kg_per_week) for r in rows if r.weight_trend_kg_per_week is not None]
    restaurant_days = sum(1 for r in rows if r.restaurant_meal)
    alcohol_days = sum(1 for r in rows if (r.alcohol_servings or 0) > 0)

    check = check_in_summary(db)
    bni = build_bni_pack(db)
    decision_patterns = check.get("patterns") or []
    meal_patterns = bni.get("patterns") or []

    # --- Sleep ---
    if sleep_vals:
        avg_sleep = mean(sleep_vals)
        if avg_sleep < 7.0:
            conf = 0.75 if len(sleep_vals) >= 7 else 0.55
            # Boost if decision patterns link sleep → hunger
            if any(p.get("key") == "poor_sleep_evening_hunger" for p in decision_patterns):
                conf = min(0.95, conf + 0.15)
            opportunities.append(
                DecisionOpportunity(
                    key="sleep",
                    label="Protect sleep (+30–60 min)",
                    action="Aim for 7.5+ hours tonight — wind down 30 minutes earlier.",
                    expected_impact="high",
                    confidence=round(conf, 2),
                    rationale=(
                        f"Recent sleep averages {avg_sleep:.1f}h. Sleep often beats calorie cuts "
                        "for adherence and hunger control."
                    ),
                    data_basis="apple_health_sleep",
                    tier=1,
                )
            )
    else:
        missing.append("Sleep (Apple Health / Garmin)")

    # --- Fiber ---
    if fiber_vals:
        avg_fiber = mean(fiber_vals)
        if avg_fiber < 25:
            conf = 0.7 if len(fiber_vals) >= 5 else 0.5
            if any("fiber" in (p.get("title") or "").lower() for p in meal_patterns):
                conf = min(0.9, conf + 0.1)
            if check.get("averages", {}).get("hunger") and check["averages"]["hunger"] >= 6:
                conf = min(0.92, conf + 0.1)
            opportunities.append(
                DecisionOpportunity(
                    key="fiber",
                    label=f"Increase fiber toward 30g (now ~{avg_fiber:.0f}g)",
                    action="Add berries + chia or vegetables to one meal today.",
                    expected_impact="medium",
                    confidence=round(conf, 2),
                    rationale="Higher fiber is linked to satiety; your intake is below common coaching targets.",
                    data_basis="food_logs",
                    tier=1,
                )
            )
    else:
        missing.append("Fiber (MacroFactor / food logs)")

    # --- Protein ---
    if protein_vals:
        avg_p = mean(protein_vals)
        if avg_p < 120:
            opportunities.append(
                DecisionOpportunity(
                    key="protein",
                    label=f"Raise protein (~{avg_p:.0f}g → 140g+)",
                    action="Add 20–30g protein at breakfast (eggs, Greek yogurt, cottage cheese).",
                    expected_impact="medium",
                    confidence=0.72 if len(protein_vals) >= 5 else 0.5,
                    rationale="Early protein often reduces evening snacking when timing data supports it.",
                    data_basis="food_logs",
                    tier=1,
                )
            )
    else:
        missing.append("Protein (MacroFactor)")

    # --- Steps / NEAT ---
    if step_vals:
        avg_steps = mean(step_vals)
        if avg_steps < 9000:
            opportunities.append(
                DecisionOpportunity(
                    key="steps",
                    label=f"+2,000 steps/day (now ~{avg_steps:.0f})",
                    action="Add a 15–20 minute walk after lunch or dinner.",
                    expected_impact="medium",
                    confidence=0.68 if len(step_vals) >= 5 else 0.48,
                    rationale=(
                        "Increasing daily activity often raises expenditure without cutting food intake — "
                        "easier to sustain than another calorie reduction."
                    ),
                    data_basis="apple_health_steps",
                    tier=1,
                )
            )
    else:
        missing.append("Steps (Apple Health)")

    # --- Sodium ---
    if sodium_vals:
        avg_na = mean(sodium_vals)
        if avg_na > 2500 or restaurant_days >= 2:
            opportunities.append(
                DecisionOpportunity(
                    key="sodium",
                    label="3-day lower-sodium experiment",
                    action="Keep restaurant/packaged sodium down for 3 days; watch morning weight.",
                    expected_impact="medium",
                    confidence=0.7,
                    rationale=(
                        f"Sodium ~{avg_na:.0f}mg/day"
                        + (f" and {restaurant_days} restaurant days" if restaurant_days else "")
                        + " — scale noise often masks fat-loss signal."
                    ),
                    data_basis="food_logs_restaurant_tags",
                    tier=1,
                )
            )

    # --- Meal timing from BNI ---
    for p in meal_patterns:
        if p.get("key") == "late_lunch_evening_calories":
            opportunities.append(
                DecisionOpportunity(
                    key="meal_timing",
                    label="Eat lunch before 2 PM",
                    action="Protect a lunch window before 2 PM today.",
                    expected_impact="medium",
                    confidence=float(p.get("confidence") or 0.55),
                    rationale=str(p.get("insight") or ""),
                    data_basis="meal_timestamps",
                    tier=1,
                )
            )
        if p.get("key") == "early_protein_less_snacking":
            opportunities.append(
                DecisionOpportunity(
                    key="early_protein",
                    label="35g+ protein before 9 AM",
                    action="Front-load breakfast protein tomorrow morning.",
                    expected_impact="high",
                    confidence=float(p.get("confidence") or 0.6),
                    rationale=str(p.get("insight") or ""),
                    data_basis="meal_timestamps",
                    tier=1,
                )
            )
        if p.get("key") == "low_satiety_meal":
            opportunities.append(
                DecisionOpportunity(
                    key="satiety_swap",
                    label="Swap low-satiety staple",
                    action=str(p.get("title") or "Replace a low-satiety meal once this week."),
                    expected_impact="medium",
                    confidence=float(p.get("confidence") or 0.5),
                    rationale=str(p.get("insight") or ""),
                    data_basis="satiety_feedback",
                    tier=2,
                )
            )

    # --- Check-in driven ---
    for p in decision_patterns:
        if p.get("key") in ("poor_sleep_evening_hunger", "poor_sleep_cravings"):
            # Already covered by sleep — boost existing or add evening buffer
            opportunities.append(
                DecisionOpportunity(
                    key="evening_buffer",
                    label="Planned snack before 6 PM on short-sleep days",
                    action="After a poor night, have Greek yogurt/fruit before leaving work.",
                    expected_impact="high",
                    confidence=float(p.get("confidence") or 0.7),
                    rationale=str(p.get("insight") or ""),
                    data_basis="check_ins_plus_sleep",
                    tier=2,
                )
            )
        if p.get("key") == "chronic_hunger":
            opportunities.append(
                DecisionOpportunity(
                    key="hunger_management",
                    label="Address hunger without cutting calories",
                    action="Increase volume foods (veg, protein, fiber) at lunch and dinner.",
                    expected_impact="high",
                    confidence=float(p.get("confidence") or 0.6),
                    rationale=str(p.get("insight") or ""),
                    data_basis="check_ins",
                    tier=2,
                )
            )

    # --- Alcohol ---
    if alcohol_days >= 2:
        opportunities.append(
            DecisionOpportunity(
                key="alcohol",
                label="Reduce alcohol frequency this week",
                action="Cap alcohol to 0–1 serving on planned social nights only.",
                expected_impact="medium",
                confidence=0.6,
                rationale=f"{alcohol_days} alcohol days in recent window — often linked to sleep + next-day hunger.",
                data_basis="manual_alcohol",
                tier=1,
            )
        )

    # --- Don't slash calories if trend ok ---
    if trends and mean(trends) < -0.15:
        opportunities.append(
            DecisionOpportunity(
                key="stay_course",
                label="Stay the course (no calorie cut)",
                action="Keep current calorie target; judge by 7-day average for another week.",
                expected_impact="high",
                confidence=0.8,
                rationale=(
                    f"Weekly trend ~{mean(trends):+.2f} kg/week — cutting further is often the wrong decision."
                ),
                data_basis="weight_trend",
                tier=1,
            )
        )
    elif calorie_vals and trends and abs(mean(trends)) < 0.1:
        # Flat — steps/fiber before cut
        opportunities.append(
            DecisionOpportunity(
                key="activity_before_cut",
                label="Try activity or fiber before cutting calories",
                action="Add steps or fiber for 10–14 days before reducing intake.",
                expected_impact="medium",
                confidence=0.65,
                rationale="Flat trend with logged intake — preserve diet quality; test NEAT/fiber first.",
                data_basis="weight_trend_calories",
                tier=1,
            )
        )

    if check.get("count", 0) < 5:
        missing.append("Subjective check-ins (hunger/energy/stress/cravings/bloating)")
    if (bni.get("event_count") or 0) < 5:
        missing.append("Timestamped meals (Apple Health food entries or meal events)")

    # Deduplicate by key, keep highest confidence
    by_key: dict[str, DecisionOpportunity] = {}
    for opp in opportunities:
        prev = by_key.get(opp.key)
        if prev is None or opp.confidence > prev.confidence:
            by_key[opp.key] = opp
    ranked = sorted(
        by_key.values(),
        key=lambda o: (IMPACT_ORDER.get(o.expected_impact, 0), o.confidence),
        reverse=True,
    )

    return DecisionRanking(
        opportunities=ranked[:8],
        mindset=(
            "Can we estimate well enough to make a better decision than the user would make alone? "
            "Rank by expected impact × confidence — not by data perfection."
        ),
        missing_for_better=missing,
    )
