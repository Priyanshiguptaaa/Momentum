"""Recommendation stage: observation → hypothesis → action."""

from __future__ import annotations

from src.db.models import DailySummary
from src.models.schemas import HypothesisResult, RecommendationItem


def build_observations(today: DailySummary) -> list[str]:
    observations: list[str] = []
    if today.morning_weight_kg is not None:
        observations.append(f"Morning weight is {today.morning_weight_kg:.2f} kg")
    if today.weight_change_from_yesterday_kg is not None:
        observations.append(
            f"Change from yesterday is {today.weight_change_from_yesterday_kg:+.2f} kg"
        )
    if today.weight_trend_kg_per_week is not None:
        observations.append(
            f"Seven-day trend is {today.weight_trend_kg_per_week:+.2f} kg/week"
        )
    if today.calories is not None:
        observations.append(f"Logged calories today: {today.calories:.0f} kcal")
    if today.restaurant_meal:
        observations.append("Restaurant meal flag is true for this day")
    if today.data_completeness_score < 0.7:
        observations.append(
            f"Data completeness is {today.data_completeness_score:.0%} for this day"
        )
    return observations


def build_recommendations(
    today: DailySummary,
    hypotheses: list[HypothesisResult],
) -> list[RecommendationItem]:
    primary = hypotheses[0] if hypotheses else None
    recs: list[RecommendationItem] = []

    # Safety rule: never recommend calorie cuts from a single weigh-in.
    recs.append(
        RecommendationItem(
            action="Avoid changing calories based on one weigh-in",
            rationale="Daily scale changes are noisy; prefer the 7-day trend before adjusting the plan",
            linked_hypothesis=primary.name if primary else None,
        )
    )

    if primary and primary.name == "temporary_water_retention":
        recs.append(
            RecommendationItem(
                action="Return to normal eating and hydration; reassess after two more morning weigh-ins",
                rationale="; ".join(primary.evidence[:2]) or primary.recommended_next_action or "",
                linked_hypothesis=primary.name,
            )
        )
    elif primary and primary.name == "possible_calorie_surplus":
        # Soft nudge only if trend supports it.
        if today.weight_trend_kg_per_week and today.weight_trend_kg_per_week > 0.2:
            recs.append(
                RecommendationItem(
                    action="Keep today's target unchanged, but review adherence over the next 7 days",
                    rationale="A rising multi-day trend deserves attention, not an immediate aggressive cut",
                    linked_hypothesis=primary.name,
                )
            )
        else:
            recs.append(
                RecommendationItem(
                    action="Maintain current calorie target and continue logging",
                    rationale="Surplus signals are weak relative to the broader trend",
                    linked_hypothesis=primary.name,
                )
            )
    else:
        recs.append(
            RecommendationItem(
                action="Maintain the current plan and use the seven-day average",
                rationale="Today's change is consistent with normal variation",
                linked_hypothesis=primary.name if primary else None,
            )
        )

    return recs[:2]


def build_caveats(hypotheses: list[HypothesisResult]) -> list[str]:
    caveats = [
        "These are probabilistic explanations from personal recent data, not medical diagnoses",
        "Correlation in short windows does not prove causation",
    ]
    missing = []
    for h in hypotheses:
        missing.extend(h.missing_information)
    for item in dict.fromkeys(missing):
        caveats.append(f"Missing data: {item}")
    return caveats
