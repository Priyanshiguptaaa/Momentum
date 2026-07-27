"""LLM-driven ReasoningTrace: the model debates; stats only supply grounded facts."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.patterns import list_patterns_for_user, pattern_to_dict
from src.analytics.reasoning_trace import build_observation
from src.coaching.interventions import intervention_to_dict, list_interventions
from src.coaching.food_staples import list_food_staples, staple_to_dict
from src.coaching.preferences import get_calorie_target
from src.db.config import settings
from src.db.models import DailySummary, User
from src.models.schemas import (
    DailySummaryMetrics,
    EnergyBalanceBelief,
    HypothesisDebate,
    ObservationBlock,
    ReasoningTrace,
    RecommendationItem,
)

REASONER_SYSTEM = """You are Momentum's health-scientist reasoning engine.
You receive a grounded EVIDENCE_PACK (facts from this person's logged data). You do NOT invent numbers.

Your job is to THINK like a scientist — not a linear stats script:
1. State observations from the pack.
2. Generate multiple competing hypotheses (at least: actual fat gain, water retention, measurement noise, food volume/glycogen, sustained surplus trend — plus others if warranted).
3. For EACH hypothesis, list evidence FOR and evidence AGAINST. Actively try to disprove yourself.
4. Assign probabilities that roughly sum to 1.0 (your judgment, not a formula).
5. Assign confidence per hypothesis.
6. Derive recommended_action FROM the leading hypothesis — never "weight up → cut calories."
7. Write expected_outcome and what_would_change_my_mind (specific, falsifiable).
8. Energy balance: stance + supporting vs contradictory evidence + missing info. calorie_target is a PLAN target, not measured TDEE.
9. Prefer personalized_patterns when present (associations ≠ causation).
10. No medical diagnosis. Preserve uncertainty. Missing data is valid.

Return ONLY valid JSON matching this schema (no markdown):
{
  "date": "YYYY-MM-DD",
  "observation": {
    "date": "YYYY-MM-DD",
    "today_weight_kg": number|null,
    "yesterday_weight_kg": number|null,
    "change_kg": number|null,
    "weight_7d_average_kg": number|null,
    "weight_trend_kg_per_week": number|null,
    "calories_today": number|null,
    "calories_7d_avg": number|null,
    "calorie_target": number,
    "sodium_mg": number|null,
    "restaurant_meal": boolean,
    "alcohol_servings": number,
    "sleep_hours": number|null,
    "strength_training_minutes": number|null,
    "data_completeness_score": number,
    "notes": ["..."]
  },
  "hypotheses": [
    {
      "id": "snake_case_id",
      "title": "Human title",
      "probability": 0.0-1.0,
      "confidence": 0.0-1.0,
      "evidence_for": ["..."],
      "evidence_against": ["..."],
      "missing_information": ["..."],
      "disconfirm_test": "..."
    }
  ],
  "primary_hypothesis_id": "...",
  "energy_balance": {
    "stance": "likely_deficit|possible_surplus|roughly_maintenance_range|unclear|unknown",
    "confidence": 0.0-1.0,
    "supporting_evidence": ["..."],
    "contradictory_evidence": ["..."],
    "missing_information": ["..."],
    "note": "..."
  },
  "missing_information": ["..."],
  "confidence": 0.0-1.0,
  "recommended_action": "...",
  "expected_outcome": "...",
  "follow_up_condition": "...",
  "what_would_change_my_mind": "...",
  "method": "Short description of how you reasoned"
}
"""


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


def build_evidence_pack(
    db: Session,
    target: date | None = None,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Facts only — no scored debate. The LLM does the science."""
    if user_id is None:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        if user is None:
            raise LookupError("No users found. Import data first.")
        user_id = user.id
        user_obj = user
    else:
        user_obj = db.get(User, user_id)
        if user_obj is None:
            raise LookupError("User not found")

    rows = list(
        db.scalars(
            select(DailySummary)
            .where(DailySummary.user_id == user_id)
            .order_by(DailySummary.date.asc())
        ).all()
    )
    if not rows:
        raise LookupError("No daily summaries available")

    day = target or date.today()
    today = next((r for r in rows if r.date == day), None)
    if today is None:
        prior = [r for r in rows if r.date <= day]
        today = prior[-1] if prior else rows[-1]

    history = [r for r in rows if r.date <= today.date][-30:]
    observation = build_observation(today, history, calorie_target=get_calorie_target(db))
    patterns = [pattern_to_dict(p) for p in list_patterns_for_user(db, user_id)]
    try:
        interventions = [intervention_to_dict(i) for i in list_interventions(db)[:8]]
    except LookupError:
        interventions = []

    try:
        from src.analytics.meal_intelligence import build_bni_pack

        meal_intelligence = build_bni_pack(db)
    except Exception:  # noqa: BLE001
        meal_intelligence = {"patterns": [], "event_count": 0}

    try:
        from src.analytics.check_ins import check_in_summary
        from src.analytics.decision_ranker import rank_decision_opportunities
        from src.coaching.preferences import get_preferences as _get_prefs

        check_ins = check_in_summary(db)
        decisions = rank_decision_opportunities(db).model_dump()
        prefs_pack = _get_prefs(db)
    except Exception:  # noqa: BLE001
        check_ins = {"count": 0}
        decisions = {"opportunities": []}
        prefs_pack = {"calorie_target": get_calorie_target(db), "source": "seed_default"}

    days = [
        {"date": r.date.isoformat(), **_to_metrics(r).model_dump()}
        for r in history
    ]

    return {
        "user": {"email": user_obj.email, "display_name": user_obj.display_name},
        "anchor_date": today.date.isoformat(),
        "calorie_target_note": (
            "calorie_target is inferred from body data (intake + weight trend ± wearables) "
            "unless manually overridden — not a hardcoded constant."
        ),
        "observation": observation.model_dump(mode="json"),
        "calorie_target": prefs_pack.get("calorie_target") or get_calorie_target(db),
        "energy_plan": prefs_pack,
        "recent_days": days,
        "personalized_patterns": patterns,
        "interventions": interventions,
        "meal_intelligence": meal_intelligence,
        "check_ins": check_ins,
        "decision_ranking": decisions,
        "scientist_instructions": (
            "Debate competing hypotheses. Try to disprove yourself. "
            "Recommendations come from hypotheses. State what would change your mind. "
            "Use meal_intelligence and check_ins for timing/satiety/feel-state. "
            "Prefer decision_ranking for highest-impact × confidence experiments. "
            "Mindset: estimate well enough to beat the user's unaided decision — not perfect data."
        ),
    }


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def _normalize_probs(hyps: list[HypothesisDebate]) -> list[HypothesisDebate]:
    total = sum(max(0.0, h.probability) for h in hyps) or 1.0
    for h in hyps:
        h.probability = round(max(0.0, h.probability) / total, 3)
    drift = 1.0 - sum(h.probability for h in hyps)
    if hyps:
        hyps[0].probability = round(hyps[0].probability + drift, 3)
    hyps.sort(key=lambda h: h.probability, reverse=True)
    return hyps


def _parse_trace(raw: dict[str, Any], evidence: dict[str, Any]) -> ReasoningTrace:
    obs = evidence.get("observation") or raw.get("observation") or {}
    if isinstance(obs, dict) and "calorie_target" not in obs:
        obs["calorie_target"] = evidence.get("calorie_target") or settings.calorie_target

    hyps_raw = raw.get("hypotheses") or []
    debates: list[HypothesisDebate] = []
    for h in hyps_raw:
        if not isinstance(h, dict):
            continue
        debates.append(
            HypothesisDebate(
                id=str(h.get("id") or "unknown"),
                title=str(h.get("title") or h.get("id") or "Hypothesis"),
                probability=float(h.get("probability") or 0),
                confidence=float(h.get("confidence") or 0.5),
                evidence_for=list(h.get("evidence_for") or []),
                evidence_against=list(h.get("evidence_against") or []),
                missing_information=list(h.get("missing_information") or []),
                disconfirm_test=h.get("disconfirm_test"),
            )
        )
    if not debates:
        raise ValueError("LLM returned no hypotheses")
    debates = _normalize_probs(debates)

    primary = str(raw.get("primary_hypothesis_id") or debates[0].id)
    if primary not in {h.id for h in debates}:
        primary = debates[0].id

    eb_raw = raw.get("energy_balance") or {}
    energy = EnergyBalanceBelief(
        stance=str(eb_raw.get("stance") or "unclear"),
        confidence=float(eb_raw.get("confidence") or 0.4),
        supporting_evidence=list(eb_raw.get("supporting_evidence") or []),
        contradictory_evidence=list(eb_raw.get("contradictory_evidence") or []),
        missing_information=list(eb_raw.get("missing_information") or []),
        note=str(eb_raw.get("note") or "Plan calorie_target is not measured TDEE."),
    )

    action = str(raw.get("recommended_action") or "Maintain current plan; gather more evidence.")
    expected = str(raw.get("expected_outcome") or "Reassess with additional mornings of data.")
    change = str(
        raw.get("what_would_change_my_mind")
        or raw.get("follow_up_condition")
        or "New multi-day evidence that contradicts the leading hypothesis."
    )
    anchor = evidence.get("anchor_date") or raw.get("date") or date.today().isoformat()

    observation = ObservationBlock.model_validate(
        {**obs, "date": obs.get("date") or anchor}
    )

    return ReasoningTrace(
        date=date.fromisoformat(str(anchor)[:10]),
        observation=observation,
        hypotheses=debates,
        primary_hypothesis_id=primary,
        energy_balance=energy,
        missing_information=list(raw.get("missing_information") or []),
        confidence=float(raw.get("confidence") or debates[0].confidence),
        recommended_action=action,
        expected_outcome=expected,
        follow_up_condition=change,
        what_would_change_my_mind=change,
        personalized_patterns=list(evidence.get("personalized_patterns") or []),
        method=str(
            raw.get("method")
            or "LLM health-scientist debate over grounded evidence pack (not a fixed statistical tree)."
        ),
        recommendations=[
            RecommendationItem(
                action=action,
                rationale=f"Derived from leading hypothesis `{primary}`",
                linked_hypothesis=primary,
            )
        ],
    )


def llm_build_reasoning_trace(
    db: Session,
    target: date | None = None,
    *,
    user_id: int | None = None,
    question: str | None = None,
) -> ReasoningTrace:
    """Primary path: LLM debates from evidence. Falls back to statistical trace if needed."""
    evidence = build_evidence_pack(db, target, user_id=user_id)

    if not settings.openai_api_key or settings.reasoning_mode == "statistical":
        return _statistical_fallback(db, target, user_id=user_id)

    payload = {
        "question": question or "Explain today's weight change and whether the plan should change.",
        "evidence_pack": evidence,
    }
    client = OpenAI(api_key=settings.openai_api_key)
    completion = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.5,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": REASONER_SYSTEM},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
    )
    text = _strip_json(completion.choices[0].message.content or "")
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        return _parse_trace(raw, evidence)
    except Exception:
        # Grounded fallback so the product never hard-fails.
        return _statistical_fallback(db, target, user_id=user_id)


def _statistical_fallback(
    db: Session,
    target: date | None,
    *,
    user_id: int | None,
) -> ReasoningTrace:
    trace = build_reasoning_trace_for_user_statistical(db, target, user_id=user_id)
    trace.method = (
        (trace.method or "")
        + " [statistical fallback — LLM reasoner unavailable or failed validation]"
    )
    return trace


def build_reasoning_trace_for_user_statistical(
    db: Session,
    target: date | None = None,
    *,
    user_id: int | None = None,
) -> ReasoningTrace:
    from src.analytics.reasoning_trace import build_reasoning_trace_for_user as _stat

    return _stat(db, target, user_id=user_id)


def llm_answer_with_trace(
    db: Session,
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """One LLM-led turn: debate + human reply. Returns reply + ReasoningTrace dict."""
    evidence = build_evidence_pack(db, user_id=user_id)
    if not settings.openai_api_key:
        raise RuntimeError("HC_OPENAI_API_KEY is not set")

    if settings.reasoning_mode == "statistical":
        trace = _statistical_fallback(db, None, user_id=user_id)
        # Narration-only path handled by caller if needed.
        return {
            "reply": None,
            "reasoning_trace": trace,
            "mode": "statistical",
        }

    system = (
        REASONER_SYSTEM
        + """

COACH MODE: You are an elite coaching panel (nutritionist, fitness coach, weight-loss coach, research advisor).
Never stop at describing data — recommend ONE highest-leverage experiment OR explicitly say "stay the course."
Separate general evidence, coaching heuristics, and personal evidence. Frame as experiments, not prescriptions.
Use food_staples (My Meals) when present for food-quality and swap suggestions.

Also include a top-level "reply" string: warm human prose answering the user's question,
narrating your debate (hypotheses, for/against, missing info, recommendation from hypotheses,
what would change your mind). NEVER put JSON inside reply. Do not invent numbers.
"""
    )
    try:
        staples = [staple_to_dict(s) for s in list_food_staples(db)]
    except LookupError:
        staples = []
    user_payload = {
        "question": message,
        "evidence_pack": evidence,
        "food_staples": staples,
        "conversation_history": history or [],
    }
    client = OpenAI(api_key=settings.openai_api_key)
    completion = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.55,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ],
    )
    text = _strip_json(completion.choices[0].message.content or "")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("LLM returned non-object JSON")

    reply = str(raw.get("reply") or "").strip()
    trace = _parse_trace(raw, evidence)
    if not reply:
        # Minimal narration if model omitted reply.
        top = ", ".join(
            f"{h.title} (~{h.probability:.0%})" for h in trace.hypotheses[:3]
        )
        reply = (
            f"Leading explanations: {top}. "
            f"{trace.recommended_action} "
            f"What would change my mind: {trace.what_would_change_my_mind}"
        )
    return {
        "reply": reply,
        "reasoning_trace": trace,
        "mode": "llm",
        "evidence_days": len(evidence.get("recent_days") or []),
        "patterns_used": len(evidence.get("personalized_patterns") or []),
        "interventions_in_context": len(evidence.get("interventions") or []),
    }
