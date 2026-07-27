"""Assemble weight explanations — LLM reasoning trace when available."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.coaching.llm_reasoner import llm_build_reasoning_trace
from src.db.models import DailySummary, User
from src.models.schemas import DailySummaryMetrics, HypothesisResult, WeightExplanationResponse


def _to_metrics(summary: DailySummary) -> DailySummaryMetrics:
    return DailySummaryMetrics(
        weight_kg=summary.morning_weight_kg,
        weight_7d_average=summary.weight_7d_average,
        weight_trend_kg_per_week=summary.weight_trend_kg_per_week,
        weight_change_from_yesterday_kg=summary.weight_change_from_yesterday_kg,
        calories=summary.calories,
        protein_g=summary.protein_g,
        fiber_g=summary.fiber_g,
        sodium_mg=summary.sodium_mg,
        steps=summary.steps,
        active_energy_kcal=summary.active_energy_kcal,
        strength_training_minutes=summary.strength_training_minutes,
        cardio_minutes=summary.cardio_minutes,
        sleep_hours=summary.sleep_hours,
        cycle_day=summary.cycle_day,
        period_status=summary.period_status,
        restaurant_meal=summary.restaurant_meal,
        alcohol_servings=summary.alcohol_servings,
        data_completeness_score=summary.data_completeness_score,
    )


def explain_weight_for_date(
    db: Session,
    target: date,
    *,
    user_id: int | None = None,
) -> WeightExplanationResponse:
    if user_id is None:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            raise LookupError("No users found. Import data first.")
        user_id = user.id

    trace = llm_build_reasoning_trace(db, target, user_id=user_id)
    today = db.scalar(
        select(DailySummary).where(DailySummary.user_id == user_id, DailySummary.date == trace.date)
    )
    if today is None:
        raise LookupError(f"No daily summary for {target.isoformat()}")

    hypotheses = [
        HypothesisResult(
            name=h.id,
            score=h.probability,
            confidence=h.confidence,
            evidence=h.evidence_for,
            counterevidence=h.evidence_against,
            missing_information=h.missing_information,
            recommended_next_action=trace.recommended_action
            if h.id == trace.primary_hypothesis_id
            else None,
        )
        for h in trace.hypotheses
    ]
    caveats = [
        "LLM health-scientist debate over grounded evidence — not medical diagnosis",
        "Correlation is not causation; the model tries to disprove hypotheses",
        trace.what_would_change_my_mind,
    ]
    for item in trace.missing_information[:5]:
        caveats.append(f"Missing data: {item}")

    return WeightExplanationResponse(
        date=trace.date,
        summary=_to_metrics(today),
        primary_hypothesis=trace.primary_hypothesis_id,
        confidence=trace.confidence,
        hypotheses=hypotheses,
        recommendations=trace.recommendations,
        observations=list(trace.observation.notes),
        caveats=caveats,
    )
