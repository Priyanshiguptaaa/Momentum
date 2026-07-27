"""LLM elite-coach layer: leverage, food quality, satiety, adherence, plateau."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from src.coaching.expert_panel import (
    EXPERT_PANEL_INSTRUCTIONS,
    fallback_expert_panel,
    parse_expert_panel,
)
from src.coaching.food_staples import list_food_staples, staple_to_dict, update_staple_quality
from src.coaching.llm_reasoner import build_evidence_pack
from src.coaching.preferences import get_calorie_target
from src.db.config import settings
from src.models.schemas import (
    CoachingPack,
    DietDay,
    DietMeal,
    DietSketch,
    FoodQualityReview,
    HighestLeverageAction,
    LeverItem,
    PlateauInvestigation,
    TomorrowExperiment,
)

COACH_SYSTEM = """You are Momentum — an elite weight-loss coach + health scientist.
You are NOT a calorie tracker. You optimize human physiology, habits, and sustainability.

You receive EVIDENCE_PACK (metrics, trends, patterns, interventions) and FOOD_STAPLES (My Meals library).

MINDSET — mentally ask:
• Energy balance: real deficit? too aggressive? maintenance shifted? weekends undoing weekdays?
  tracking accuracy? hidden oil/sauces/drinks/snacks?
• Nutrition quality: protein enough? fiber enough? satiety? sodium swings? ultra-processed share?
  vegetables? healthy fats? sugar → cravings?
• Meal design: macros can look perfect while protein is all packaged, fiber is low, evenings are hungry.
• Satiety: estimate 1-10 how likely a staple/meal keeps THIS person full (use their patterns if any).
• Adherence loops: e.g. Friday restaurant → Saturday overeating → scale spike → discouraged → Sunday binge.
• Friction: why skipped gym / meal prep? (sleep, work, commute, stress, travel) — recommend friction fixes, not "be disciplined."
• Recovery chains: poor sleep → hunger → lower NEAT → cravings → worse adherence.
• Plateau: investigate calories, trend, water, training, cycle, sodium, fiber, stress, restaurants, sleep, logging.
• Opportunity: ONE highest-leverage change — not 10 tips. Optimize leverage + sustainability.
• Behavioral nutrition: use meal_intelligence (timing, intervals, satiety scores, habits, hunger prediction)
  — optimize when/what/how they eat, not just calories.

RULES:
- Never stop at describing data. End with the single highest-impact change for tomorrow.
- Do not say "calories = 1700." Say what the calories MEAN (quality, processing, hunger, patterns).
- Correlation ≠ causation. No medical diagnosis. No slash calories from one weigh-in.
- Do not invent numbers absent from evidence. Say what's missing.
- Use food_staples by id in food_quality_reviews when possible.

Return ONLY valid JSON:
{
  "headline": "...",
  "stuck_story": "for someone doing everything right but confused",
  "nutrition_quality_story": "coach-level paragraph on quality not just macros",
  "what_matters_now": ["..."],
  "levers": [{"key":"...","label":"...","status":"ok|watch|risk|unknown","why":"...","tune":"..."}],
  "highest_leverage": {
    "action": "ONE specific change tomorrow",
    "reason": "why this beats other options",
    "expected_impact": "what should improve (adherence, hunger, trend signal, etc.)",
    "effort": "low|medium",
    "category": "sleep|food_quality|protein|fiber|sodium|adherence|movement|other"
  },
  "tomorrow_experiments": [{"title":"...","action":"...","why":"...","how_to_judge":"...","effort":"low|medium"}],
  "food_quality_reviews": [{
    "staple_id": 1, "name":"...", "flags":["ultra_processed","added_sugar","hidden_refined_carbs","low_protein","poor_fiber_quality","high_sodium","sugar_alcohols","artificial_sweeteners"],
    "verdict":"...", "swap_suggestion":"...", "satiety_score": 4
  }],
  "adherence_loops": ["behavioral loop descriptions from data if any"],
  "friction_notes": ["friction-aware observations"],
  "recovery_chain": "sleep → hunger → ... if relevant",
  "plateau": {
    "summary": "if trend flat/rising despite effort",
    "ranked_causes": ["most likely first"],
    "ruled_out": ["..."],
    "missing_data": ["..."],
    "confidence": 0.0-1.0
  },
  "diet_sketch": {
    "title":"...", "calorie_guidance":"...", "principles":["..."],
    "days":[{"label":"Day 1","meals":[{"slot":"breakfast","name":"...","notes":"...","uses_staple":true,"estimated_satiety":8}]}],
    "caveats":["..."]
  },
  "watch_outs": ["..."]
}
"""

COACH_SYSTEM = COACH_SYSTEM + "\n" + EXPERT_PANEL_INSTRUCTIONS


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def _fallback_pack() -> CoachingPack:
    return CoachingPack(
        headline="Watch the weekly trend — today's scale is only one data point.",
        stuck_story=(
            "When calories look fine but progress feels stuck, the story is often water, glycogen, "
            "logging gaps, or food quality (hunger → evening snacking) — not necessarily that you need "
            "a harsher deficit."
        ),
        nutrition_quality_story=(
            "Macros on paper can look fine while fiber is low, protein is mostly packaged, and evenings "
            "stay hungry. Quality and satiety matter as much as the calorie number."
        ),
        what_matters_now=[
            "14-day weight trend vs daily noise",
            "Protein + fiber from whole foods",
            "Sleep and sodium (scale swings)",
            "Ultra-processed share of staples",
            "Weekend vs weekday adherence",
        ],
        levers=[
            LeverItem(
                key="trend",
                label="Weekly trend",
                status="watch",
                why="Fat loss shows in averages, not one morning.",
                tune="Compare 7-day averages week-over-week before changing targets.",
            )
        ],
        highest_leverage=HighestLeverageAction(
            action="Log 2–3 staples you eat most days under My Meals so Momentum can review quality and satiety.",
            reason="Without your recurring meals, coaching defaults to generic advice.",
            expected_impact="Personalized swaps and hunger predictions.",
            effort="low",
            category="food_quality",
        ),
        tomorrow_experiments=[
            TomorrowExperiment(
                title="Protect the morning signal",
                action="Weigh after bathroom, before food/drink; keep calories at plan.",
                why="Better signal before changing the plan.",
                how_to_judge="If 7-day average drifts down over 10–14 days, stay course.",
                effort="low",
            )
        ],
        watch_outs=["Add My Meals for coach-level food quality analysis."],
        expert_panel=fallback_expert_panel(),
    )


def _parse_pack(raw: dict[str, Any], db: Session) -> CoachingPack:
    levers = [
        LeverItem(
            key=str(x.get("key") or "lever"),
            label=str(x.get("label") or "Lever"),
            status=str(x.get("status") or "unknown"),
            why=str(x.get("why") or ""),
            tune=str(x.get("tune") or ""),
        )
        for x in (raw.get("levers") or [])
        if isinstance(x, dict)
    ]
    experiments = [
        TomorrowExperiment(
            title=str(x.get("title") or "Experiment"),
            action=str(x.get("action") or ""),
            why=str(x.get("why") or ""),
            how_to_judge=str(x.get("how_to_judge") or ""),
            effort=str(x.get("effort") or "low"),
        )
        for x in (raw.get("tomorrow_experiments") or [])
        if isinstance(x, dict)
    ]
    reviews: list[FoodQualityReview] = []
    for x in raw.get("food_quality_reviews") or []:
        if not isinstance(x, dict):
            continue
        review = FoodQualityReview(
            staple_id=x.get("staple_id"),
            name=str(x.get("name") or "Food"),
            flags=[str(f) for f in (x.get("flags") or [])],
            verdict=str(x.get("verdict") or ""),
            swap_suggestion=x.get("swap_suggestion"),
            satiety_score=x.get("satiety_score"),
        )
        reviews.append(review)
        sid = x.get("staple_id")
        if isinstance(sid, int):
            try:
                update_staple_quality(
                    db,
                    sid,
                    quality_flags=review.flags,
                    quality_notes=review.verdict
                    + (f" Satiety ~{review.satiety_score}/10." if review.satiety_score else "")
                    + (f" Swap: {review.swap_suggestion}" if review.swap_suggestion else ""),
                )
            except LookupError:
                pass

    hl = raw.get("highest_leverage")
    highest = None
    if isinstance(hl, dict):
        highest = HighestLeverageAction(
            action=str(hl.get("action") or ""),
            reason=str(hl.get("reason") or ""),
            expected_impact=str(hl.get("expected_impact") or ""),
            effort=str(hl.get("effort") or "low"),
            category=str(hl.get("category") or "other"),
        )

    plateau = None
    pl = raw.get("plateau")
    if isinstance(pl, dict):
        plateau = PlateauInvestigation(
            summary=str(pl.get("summary") or ""),
            ranked_causes=[str(x) for x in (pl.get("ranked_causes") or [])],
            ruled_out=[str(x) for x in (pl.get("ruled_out") or [])],
            missing_data=[str(x) for x in (pl.get("missing_data") or [])],
            confidence=float(pl.get("confidence") or 0.4),
        )

    diet = None
    d = raw.get("diet_sketch")
    if isinstance(d, dict):
        days = []
        for day in d.get("days") or []:
            if not isinstance(day, dict):
                continue
            meals = [
                DietMeal(
                    slot=str(m.get("slot") or "meal"),
                    name=str(m.get("name") or ""),
                    notes=m.get("notes"),
                    uses_staple=bool(m.get("uses_staple")),
                    estimated_satiety=m.get("estimated_satiety"),
                )
                for m in (day.get("meals") or [])
                if isinstance(m, dict)
            ]
            days.append(DietDay(label=str(day.get("label") or "Day"), meals=meals))
        diet = DietSketch(
            title=str(d.get("title") or "Plan sketch"),
            calorie_guidance=str(d.get("calorie_guidance") or ""),
            principles=[str(p) for p in (d.get("principles") or [])],
            days=days,
            caveats=[str(c) for c in (d.get("caveats") or [])],
        )

    base = _fallback_pack()
    panel = parse_expert_panel(raw.get("expert_panel")) or base.expert_panel

    if panel and panel.synthesis.selected_experiment and not highest:
        sel = panel.synthesis.selected_experiment
        ev = sel.evidence
        reason_parts = [
            p
            for p in [
                ev.personal_evidence,
                ev.coaching_heuristic,
                panel.synthesis.chair_summary,
            ]
            if p
        ]
        highest = HighestLeverageAction(
            action=sel.action,
            reason=" ".join(reason_parts[:2]) or panel.synthesis.chair_summary,
            expected_impact=sel.how_to_judge,
            effort="low" if sel.duration_days <= 7 else "medium",
            category=sel.category if sel.category != "no_change" else "other",
        )
    elif panel and panel.synthesis.selected_experiment and highest:
        sel = panel.synthesis.selected_experiment
        if sel.action and not panel.synthesis.intervene_now:
            highest = HighestLeverageAction(
                action=sel.action,
                reason=panel.synthesis.no_change_reason or highest.reason,
                expected_impact=sel.how_to_judge or highest.expected_impact,
                effort=highest.effort,
                category="other",
            )

    return CoachingPack(
        headline=str(raw.get("headline") or base.headline),
        stuck_story=str(raw.get("stuck_story") or base.stuck_story),
        nutrition_quality_story=raw.get("nutrition_quality_story"),
        what_matters_now=[str(x) for x in (raw.get("what_matters_now") or [])] or base.what_matters_now,
        levers=levers or base.levers,
        highest_leverage=highest or base.highest_leverage,
        tomorrow_experiments=experiments or base.tomorrow_experiments,
        food_quality_reviews=reviews,
        diet_sketch=diet,
        adherence_loops=[str(x) for x in (raw.get("adherence_loops") or [])],
        friction_notes=[str(x) for x in (raw.get("friction_notes") or [])],
        recovery_chain=raw.get("recovery_chain"),
        plateau=plateau,
        watch_outs=[str(x) for x in (raw.get("watch_outs") or [])],
        expert_panel=panel,
    )


def build_coaching_pack(db: Session, *, include_diet: bool = True) -> CoachingPack:
    if not settings.openai_api_key:
        return _fallback_pack()
    try:
        evidence = build_evidence_pack(db)
    except LookupError:
        return _fallback_pack()

    try:
        from src.analytics.check_ins import check_in_summary
        from src.analytics.decision_ranker import rank_decision_opportunities
        from src.analytics.meal_intelligence import build_bni_pack

        meal_intelligence = build_bni_pack(db)
        check_ins_pack = check_in_summary(db)
        decisions = rank_decision_opportunities(db).model_dump()
    except Exception:  # noqa: BLE001
        meal_intelligence = {}
        check_ins_pack = {}
        decisions = {}
    payload = {
        "evidence_pack": evidence,
        "food_staples": staples,
        "meal_intelligence": meal_intelligence,
        "check_ins": check_ins_pack,
        "decision_ranking": decisions,
        "include_diet_sketch": include_diet,
        "calorie_target": get_calorie_target(db),
        "coaching_mode": "decision_quality_optimizer",
    }
    client = OpenAI(api_key=settings.openai_api_key)
    completion = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.55,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": COACH_SYSTEM},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
    )
    raw = json.loads(_strip_json(completion.choices[0].message.content or "{}"))
    if not isinstance(raw, dict):
        return _fallback_pack()
    return _parse_pack(raw, db)


def build_plateau_investigation(db: Session) -> PlateauInvestigation:
    pack = build_coaching_pack(db, include_diet=False)
    if pack.plateau:
        return pack.plateau
    return PlateauInvestigation(
        summary=pack.stuck_story or "Insufficient data for a full plateau workup.",
        ranked_causes=pack.what_matters_now[:5],
        ruled_out=[],
        missing_data=pack.watch_outs,
        confidence=0.35,
    )
