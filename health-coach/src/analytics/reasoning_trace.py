"""Reasoning-trace engine: observe → debate hypotheses → challenge → recommend → learn conditions."""

from __future__ import annotations

from datetime import date
from math import exp
from statistics import mean
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.patterns import list_patterns_for_user, pattern_to_dict
from src.db.config import settings
from src.db.models import DailySummary, User
from src.models.schemas import (
    EnergyBalanceBelief,
    HypothesisDebate,
    ObservationBlock,
    ReasoningTrace,
    RecommendationItem,
)


def _softmax(scores: list[float], temperature: float = 0.45) -> list[float]:
    if not scores:
        return []
    scaled = [s / max(temperature, 1e-6) for s in scores]
    m = max(scaled)
    exps = [exp(s - m) for s in scaled]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def _yesterday(history: list[DailySummary], today: DailySummary) -> Optional[DailySummary]:
    for row in reversed(history):
        if row.date < today.date:
            return row
    return None


def _recent_avg_calories(history: list[DailySummary], days: int = 7) -> Optional[float]:
    window = [d.calories for d in history[-days:] if d.calories is not None]
    return mean(window) if window else None


def _baseline_sodium(history: list[DailySummary]) -> Optional[float]:
    values = [d.sodium_mg for d in history[:-1] if d.sodium_mg is not None]
    return mean(values) if values else None


def build_observation(
    today: DailySummary,
    history: list[DailySummary],
    *,
    calorie_target: float,
) -> ObservationBlock:
    yesterday = _yesterday(history, today)
    notes: list[str] = []
    if today.morning_weight_kg is not None:
        notes.append(f"Morning weight {today.morning_weight_kg:.2f} kg")
    if yesterday and yesterday.morning_weight_kg is not None:
        notes.append(f"Yesterday {yesterday.morning_weight_kg:.2f} kg")
    if today.weight_change_from_yesterday_kg is not None:
        notes.append(f"Change {today.weight_change_from_yesterday_kg:+.2f} kg")
    if today.weight_trend_kg_per_week is not None:
        notes.append(f"7-day trend {today.weight_trend_kg_per_week:+.2f} kg/week")

    return ObservationBlock(
        date=today.date,
        today_weight_kg=today.morning_weight_kg,
        yesterday_weight_kg=yesterday.morning_weight_kg if yesterday else None,
        change_kg=today.weight_change_from_yesterday_kg,
        weight_7d_average_kg=today.weight_7d_average,
        weight_trend_kg_per_week=today.weight_trend_kg_per_week,
        calories_today=today.calories,
        calories_7d_avg=_recent_avg_calories(history, 7),
        calorie_target=calorie_target,
        sodium_mg=(yesterday.sodium_mg if yesterday and yesterday.sodium_mg is not None else today.sodium_mg),
        restaurant_meal=bool(yesterday.restaurant_meal) if yesterday else today.restaurant_meal,
        alcohol_servings=(
            yesterday.alcohol_servings if yesterday is not None else today.alcohol_servings
        ),
        sleep_hours=(
            yesterday.sleep_hours if yesterday and yesterday.sleep_hours is not None else today.sleep_hours
        ),
        strength_training_minutes=(
            yesterday.strength_training_minutes
            if yesterday and yesterday.strength_training_minutes is not None
            else today.strength_training_minutes
        ),
        data_completeness_score=today.data_completeness_score,
        notes=notes,
    )


def _debate_hypotheses(
    today: DailySummary,
    history: list[DailySummary],
    *,
    calorie_target: float,
    patterns: list[dict[str, Any]],
) -> list[HypothesisDebate]:
    yesterday = _yesterday(history, today)
    change = today.weight_change_from_yesterday_kg
    trend = today.weight_trend_kg_per_week
    recent_cal = _recent_avg_calories(history, 7)
    baseline_na = _baseline_sodium(history)
    signal = yesterday or today
    cal_days = sum(1 for d in history[-7:] if d.calories is not None)

    # --- H1 actual fat gain ---
    fat_for: list[str] = []
    fat_against: list[str] = []
    fat_missing: list[str] = []
    fat_score = 0.05
    if change is not None and change > 0:
        fat_for.append(f"Scale is up {change:+.2f} kg vs yesterday")
        fat_score += 0.05
    if recent_cal is not None and recent_cal - calorie_target >= 300:
        fat_for.append(
            f"7-day intake ({recent_cal:.0f} kcal) is above plan target ({calorie_target:.0f} kcal)"
        )
        fat_score += 0.25
    if trend is not None and trend > 0.25:
        fat_for.append(f"7-day trend is rising ({trend:+.2f} kg/week)")
        fat_score += 0.25
    if change is not None and change > 0:
        # ~7700 kcal ≈ 1 kg fat; overnight fat gain of 0.15kg needs ~1150 surplus in one day — usually impossible.
        implied = change * 7700
        fat_against.append(
            f"Gaining {change:.2f} kg as pure fat overnight would require roughly {implied:.0f} kcal surplus "
            "in one day — physiologically implausible at typical intakes"
        )
        fat_score -= 0.35
    if trend is not None and trend < 0:
        fat_against.append(f"Weekly trend is still decreasing ({trend:+.2f} kg/week)")
        fat_score -= 0.2
    if recent_cal is not None and recent_cal <= calorie_target + 100:
        fat_against.append("Recent logged intake is near or below the plan target")
        fat_score -= 0.15
    if recent_cal is None:
        fat_missing.append("Complete multi-day calorie logs")
    fat_score = max(0.01, fat_score)

    # --- H2 water retention ---
    water_for: list[str] = []
    water_against: list[str] = []
    water_missing: list[str] = []
    water_score = 0.12
    if change is not None and change > 0:
        water_for.append(f"Upward scale move of {change:+.2f} kg can be fluid/glycogen")
        water_score += 0.12 if change < 0.5 else 0.18
    if signal.restaurant_meal:
        water_for.append("Restaurant meal in the prior day (often higher sodium/volume)")
        water_score += 0.22
    else:
        water_missing.append("Restaurant meal flag for prior day")
    if signal.alcohol_servings and signal.alcohol_servings > 0:
        water_for.append(f"Alcohol logged previously ({signal.alcohol_servings:g} servings)")
        water_score += 0.12
    if signal.sodium_mg is not None and baseline_na is not None:
        delta = signal.sodium_mg - baseline_na
        if delta > 400:
            water_for.append(f"Sodium ~{delta:.0f} mg above recent baseline")
            water_score += 0.2
        elif delta < -200:
            water_against.append("Sodium was below recent baseline")
            water_score -= 0.08
    else:
        water_missing.append("Prior-day sodium vs personal baseline")
    if trend is not None and trend <= 0.05:
        water_for.append(
            f"Broader trend is flat/down ({trend:+.2f} kg/week), so a one-day bump fits temporary fluid"
        )
        water_score += 0.18
    if recent_cal is not None and recent_cal <= calorie_target + 150 and change is not None and change > 0:
        water_for.append("Intake near target makes a sudden fat jump less likely than fluid")
        water_score += 0.12
    if signal.strength_training_minutes and signal.strength_training_minutes >= 30:
        water_for.append("Recent strength work can add short-term inflammation-related water")
        water_score += 0.08
    for p in patterns:
        if p.get("pattern_key") in {
            "restaurant_next_morning_bump",
            "high_sodium_next_morning_bump",
            "alcohol_next_morning_bump",
            "strength_day_next_morning_bump",
        } and (p.get("typical_delta") or 0) > 0:
            water_for.append(f"Personal pattern: {p.get('title')} (assoc. only)")
            water_score += 0.1 * float(p.get("confidence") or 0.5)
    if change is not None and change <= 0:
        water_against.append("No upward scale move today")
        water_score -= 0.15
    water_missing.extend(
        [
            "Subjective bloating",
            "Bowel movement / constipation status",
            "Menstrual cycle phase (if applicable)",
        ]
    )
    water_score = max(0.01, water_score)

    # --- H3 measurement variation ---
    noise_for: list[str] = []
    noise_against: list[str] = []
    noise_missing: list[str] = []
    noise_score = 0.2
    if change is not None and abs(change) < 0.4:
        noise_for.append(f"Change of {change:+.2f} kg is within common day-to-day scale noise")
        noise_score += 0.35
    elif change is not None and abs(change) < 0.7:
        noise_for.append(f"Change of {change:+.2f} kg can still include measurement variation")
        noise_score += 0.15
    elif change is not None:
        noise_against.append(f"Change of {change:+.2f} kg is larger than typical noise alone")
        noise_score -= 0.1
    if today.data_completeness_score < 0.6:
        noise_for.append("Incomplete recent data increases uncertainty / noise weight")
        noise_score += 0.1
        noise_missing.append("More complete morning weigh-in context")
    if change is None:
        noise_missing.append("Day-over-day weight change")
        noise_score = 0.25
    noise_score = max(0.01, noise_score)

    # --- H4 food volume / glycogen ---
    vol_for: list[str] = []
    vol_against: list[str] = []
    vol_missing: list[str] = []
    vol_score = 0.08
    if signal.restaurant_meal:
        vol_for.append("Restaurant / larger meal day often increases glycogen + food volume")
        vol_score += 0.2
    if signal.sodium_mg is not None and baseline_na is not None and signal.sodium_mg > baseline_na:
        vol_for.append("Higher sodium can increase water bound with glycogen/food")
        vol_score += 0.1
    if change is not None and 0 < change < 0.6:
        vol_for.append("Magnitude is compatible with glycogen/food residue rather than fat")
        vol_score += 0.15
    if change is not None and change <= 0:
        vol_against.append("No increase to explain via food volume")
        vol_score -= 0.1
    vol_missing.append("Meal timing / last meal size before weigh-in")
    vol_missing.append("Carbohydrate intake yesterday")
    vol_score = max(0.01, vol_score)

    # --- H5 sustained calorie surplus (trend belief, not overnight fat) ---
    sur_for: list[str] = []
    sur_against: list[str] = []
    sur_missing: list[str] = []
    sur_score = 0.08
    if recent_cal is not None and recent_cal - calorie_target >= 200:
        sur_for.append(
            f"Average intake ({recent_cal:.0f}) exceeds plan target ({calorie_target:.0f})"
        )
        sur_score += 0.25
    if trend is not None and trend > 0.2:
        sur_for.append(f"Multi-day trend rising ({trend:+.2f} kg/week)")
        sur_score += 0.3
    if trend is not None and trend <= 0:
        sur_against.append(f"Trend not rising ({trend:+.2f} kg/week)")
        sur_score -= 0.2
    if recent_cal is not None and recent_cal <= calorie_target:
        sur_against.append("Logged intake at/below target")
        sur_score -= 0.15
    if cal_days < 4:
        sur_missing.append("More days of complete nutrition logs")
        sur_against.append(f"Only {cal_days} nutrition log(s) in the last week")
        sur_score -= 0.1
    sur_score = max(0.01, sur_score)

    raw = [
        ("actual_fat_gain", "Actual fat gain", fat_score, fat_for, fat_against, fat_missing, 0.55),
        ("temporary_water_retention", "Water retention / fluid shift", water_score, water_for, water_against, water_missing, 0.6),
        ("normal_measurement_noise", "Measurement variation", noise_score, noise_for, noise_against, noise_missing, 0.55),
        ("food_volume_glycogen", "Food volume / glycogen", vol_score, vol_for, vol_against, vol_missing, 0.5),
        ("possible_calorie_surplus", "Sustained calorie surplus (trend)", sur_score, sur_for, sur_against, sur_missing, 0.55),
    ]

    scores = [r[2] for r in raw]
    probs = _softmax(scores)
    debates: list[HypothesisDebate] = []
    for (key, title, score, fr, ag, miss, base_conf), prob in zip(raw, probs):
        # Confidence rises with evidence clarity and falls with missing info / contradiction density.
        conf = base_conf + 0.04 * len(fr) - 0.05 * len(ag) - 0.03 * len(miss)
        conf = max(0.15, min(0.92, conf))
        debates.append(
            HypothesisDebate(
                id=key,
                title=title,
                probability=round(prob, 3),
                confidence=round(conf, 3),
                evidence_for=fr or ["No strong supporting signal"],
                evidence_against=ag or ["No major contradictions logged"],
                missing_information=miss,
                disconfirm_test=(
                    "Would be weakened if the opposing hypothesis accumulates multi-day confirming evidence"
                ),
            )
        )
    debates.sort(key=lambda h: h.probability, reverse=True)
    # Fix float drift so displayed probabilities sum to 1.00
    total = sum(h.probability for h in debates)
    if debates and abs(total - 1.0) > 1e-9:
        debates[0].probability = round(debates[0].probability + (1.0 - total), 3)
    return debates


def _energy_balance(
    history: list[DailySummary],
    *,
    calorie_target: float,
) -> EnergyBalanceBelief:
    recent_cal = _recent_avg_calories(history, 7)
    cal_days = sum(1 for d in history[-7:] if d.calories is not None)
    latest = history[-1] if history else None
    trend = latest.weight_trend_kg_per_week if latest else None

    supporting: list[str] = []
    contradictory: list[str] = []
    missing: list[str] = []
    stance = "unknown"
    conf = 0.35

    if trend is not None and trend < -0.1:
        supporting.append(f"Weight trend decreasing ({trend:+.2f} kg/week)")
    if recent_cal is not None and recent_cal <= calorie_target + 50:
        supporting.append(
            f"Intake near/below plan target ({recent_cal:.0f} vs {calorie_target:.0f} kcal)"
        )
    if trend is not None and trend > 0.2:
        contradictory.append(f"Weight trend rising ({trend:+.2f} kg/week)")
    if recent_cal is not None and recent_cal > calorie_target + 200:
        contradictory.append("Average intake above plan target")
    if cal_days < 4:
        contradictory.append(f"Only {cal_days} nutrition logs in the last 7 days")
        missing.append("More complete calorie logging")
    missing.append("Measured TDEE / true maintenance (not available yet)")

    if trend is not None and trend < -0.1 and (recent_cal is None or recent_cal <= calorie_target + 100):
        stance = "likely_deficit"
        conf = 0.55 if cal_days >= 4 else 0.4
    elif trend is not None and trend > 0.2 and recent_cal is not None and recent_cal > calorie_target + 150:
        stance = "possible_surplus"
        conf = 0.55 if cal_days >= 5 else 0.4
    elif trend is not None and abs(trend) <= 0.1:
        stance = "roughly_maintenance_range"
        conf = 0.45
    else:
        stance = "unclear"
        conf = 0.35

    return EnergyBalanceBelief(
        stance=stance,
        confidence=conf,
        supporting_evidence=supporting or ["Insufficient signals"],
        contradictory_evidence=contradictory or ["No strong contradictions"],
        missing_information=missing,
        note="Plan calorie_target is not measured maintenance/TDEE.",
    )


def _recommendation_from_hypotheses(
    primary: HypothesisDebate,
    energy: EnergyBalanceBelief,
) -> tuple[str, str, str]:
    """Return action, expected_outcome, linked reasoning — from hypotheses, not raw weight."""
    if primary.id in {"temporary_water_retention", "food_volume_glycogen", "normal_measurement_noise"}:
        action = "No calorie intervention. Keep the current plan and reassess after 2 more morning weigh-ins."
        expected = "If this is fluid/noise/volume, weight should drift back toward the 7-day average within a few days."
    elif primary.id == "possible_calorie_surplus":
        action = (
            "Do not slash calories today. Review the next 7 days of adherence and weekly trend before any change."
        )
        expected = "If surplus is real, the multi-week trend—not one weigh-in—should keep rising."
    elif primary.id == "actual_fat_gain":
        action = (
            "Treat overnight fat gain as unlikely. Continue plan; only reconsider after a sustained multi-day trend."
        )
        expected = "True fat change shows up in weekly averages, not a single morning."
    else:
        action = "Maintain current plan; gather missing context before intervening."
        expected = "Better data should raise confidence without changing behavior prematurely."

    if energy.stance == "likely_deficit" and primary.id != "possible_calorie_surplus":
        action = action  # keep non-reactive
    return action, expected, primary.id


def _change_my_mind(primary: HypothesisDebate, energy: EnergyBalanceBelief) -> str:
    if primary.id in {"temporary_water_retention", "food_volume_glycogen", "normal_measurement_noise"}:
        return (
            "I would raise the probability of a true sustained surplus if morning weight stays elevated "
            "above the prior 7-day average for 5 consecutive days AND logged intake exceeds the plan target "
            "across that same window."
        )
    if primary.id == "possible_calorie_surplus":
        return (
            "I would downgrade surplus if the 14-day trend turns flat/down while intake remains at target "
            "and completeness is high."
        )
    if primary.id == "actual_fat_gain":
        return (
            "I would further reduce fat-gain probability if weight reverts within 48–72 hours while intake "
            "stays near target."
        )
    return (
        "I would revise this ranking if missing context (sodium, restaurant, cycle, alcohol, training) "
        "arrives and conflicts with the leading hypothesis for several days."
    )


def build_reasoning_trace(
    today: DailySummary,
    history: list[DailySummary],
    *,
    calorie_target: float | None = None,
    patterns: list[dict[str, Any]] | None = None,
) -> ReasoningTrace:
    target = calorie_target if calorie_target is not None else settings.calorie_target
    hist = history or [today]
    observation = build_observation(today, hist, calorie_target=target)
    debates = _debate_hypotheses(today, hist, calorie_target=target, patterns=patterns or [])
    energy = _energy_balance(hist, calorie_target=target)
    primary = debates[0]
    action, expected, linked = _recommendation_from_hypotheses(primary, energy)
    change_mind = _change_my_mind(primary, energy)

    missing: list[str] = []
    for h in debates:
        missing.extend(h.missing_information)
    missing = list(dict.fromkeys(missing))

    method = (
        "Generated competing hypotheses, scored evidence for and against each (attempting to disprove), "
        "normalized to probabilities, derived the recommendation from the leading hypothesis—not from the "
        "raw scale reading alone—and stated what evidence would force a belief update."
    )

    return ReasoningTrace(
        date=today.date,
        observation=observation,
        hypotheses=debates,
        primary_hypothesis_id=primary.id,
        energy_balance=energy,
        missing_information=missing,
        confidence=primary.confidence,
        recommended_action=action,
        expected_outcome=expected,
        follow_up_condition=change_mind,
        what_would_change_my_mind=change_mind,
        personalized_patterns=patterns or [],
        method=method,
        recommendations=[
            RecommendationItem(
                action=action,
                rationale=f"Derived from leading hypothesis `{linked}` (p={primary.probability:.0%})",
                linked_hypothesis=linked,
            )
        ],
    )


def build_reasoning_trace_for_user(
    db: Session,
    target: date | None = None,
    *,
    user_id: int | None = None,
) -> ReasoningTrace:
    if user_id is None:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            raise LookupError("No users found. Import data first.")
        user_id = user.id

    day = target or date.today()
    # Prefer most recent summary with weight if today missing.
    rows = list(
        db.scalars(
            select(DailySummary)
            .where(DailySummary.user_id == user_id)
            .order_by(DailySummary.date.asc())
        ).all()
    )
    if not rows:
        raise LookupError("No daily summaries available")

    today = next((r for r in rows if r.date == day), None)
    if today is None:
        # nearest prior day
        prior = [r for r in rows if r.date <= day]
        today = prior[-1] if prior else rows[-1]
        day = today.date

    history = [r for r in rows if r.date <= day][-30:]
    patterns = [pattern_to_dict(p) for p in list_patterns_for_user(db, user_id)]
    return build_reasoning_trace(
        today,
        history,
        calorie_target=settings.calorie_target,
        patterns=patterns,
    )
