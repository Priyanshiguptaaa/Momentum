"""Expert panel: nutritionist, fitness coach, weight-loss coach, research advisor."""

from __future__ import annotations

from typing import Any

from src.models.schemas import (
    CandidateExperiment,
    EvidenceLayers,
    ExpertBrainOpinion,
    ExpertPanel,
    ExpertPanelSynthesis,
    RejectedAlternative,
    SynthesizedExperiment,
)

EXPERT_PANEL_INSTRUCTIONS = """
EXPERT PANEL — simulate four experts meeting every morning to review this user.

Each expert proposes 0–2 candidate experiments (not prescriptions). A chair synthesizes ONE.

🧠 NUTRITIONIST — protein, fiber, micronutrients, food quality, meal timing, hunger, satiety,
   processed food, digestion. Examples: increase fiber to 30g, swap packaged protein for whole food,
   add vegetables to dinner, 3-day sodium test.

💪 FITNESS COACH — progression, recovery, cardio, steps, NEAT, training volume, plateau duration.
   Examples: +2000 steps instead of cutting calories, one HIIT session, deload week, train closer to failure.

⚖️ WEIGHT-LOSS COACH — trend, adherence, deficit size, plateau, hunger, sustainability.
   First ask: is this actually a plateau? (7 days? sodium? cycle? adherence drop? activity change?)
   Only then recommend a change. Sometimes the best advice is NO CHANGE.

📚 RESEARCH ADVISOR — grounds recommendations in general evidence + coaching heuristics.
   Wording: "This is the next evidence-based experiment" — never "this is THE answer."

SYNTHESIS RULES:
- Pick ONE experiment from hundreds of possible interventions, or recommend NO CHANGE.
- When intervene_now is false, explain why (e.g. "4 days is normal variation; 7-day avg still down").
- Separate evidence layers clearly:
  • general_evidence — what research/literature suggests
  • coaching_heuristic — what experienced coaches typically try first
  • personal_evidence — what THIS user's history/patterns show
- Reject 2–4 alternatives with why_not_now.
- highest_leverage.action MUST match synthesis.selected_experiment.action (or no-change message).

Include in your JSON response:
"expert_panel": {
  "nutritionist": {
    "expert": "nutritionist", "emoji": "🧠",
    "focus_reviewed": ["protein", "fiber", ...],
    "observations": ["..."],
    "candidate_experiments": [{"action":"...","rationale":"...","priority":0.8,"category":"nutrition"}],
    "intervene_recommended": true
  },
  "fitness_coach": { "expert": "fitness_coach", "emoji": "💪", ... },
  "weight_loss_coach": { "expert": "weight_loss_coach", "emoji": "⚖️", ... },
  "research_advisor": {
    "expert": "research_advisor", "emoji": "📚",
    "focus_reviewed": ["evidence quality", "intervention hierarchy"],
    "observations": ["general evidence notes", "heuristic notes"],
    "candidate_experiments": [],
    "intervene_recommended": true
  },
  "synthesis": {
    "intervene_now": true,
    "no_change_reason": null,
    "chair_summary": "one paragraph — how the panel decided",
    "selected_experiment": {
      "action": "ONE specific experiment",
      "category": "nutrition|training|lifestyle|behavior|no_change",
      "evidence": {
        "general_evidence": "Research suggests...",
        "coaching_heuristic": "Experienced coaches often...",
        "personal_evidence": "Your data shows..."
      },
      "how_to_judge": "what to watch over 7–14 days",
      "duration_days": 14,
      "confidence": 0.65,
      "framing": "This is the next evidence-based experiment, not a prescription."
    },
    "rejected_alternatives": [{"action":"Reduce calories","why_not_now":"7-day trend still decreasing"}]
  }
}
"""


def _parse_candidate(x: dict[str, Any]) -> CandidateExperiment:
    return CandidateExperiment(
        action=str(x.get("action") or ""),
        rationale=str(x.get("rationale") or ""),
        priority=float(x.get("priority") or 0.5),
        category=str(x.get("category") or "other"),
    )


def _parse_brain(raw: dict[str, Any] | None, *, expert: str, emoji: str) -> ExpertBrainOpinion:
    if not isinstance(raw, dict):
        return ExpertBrainOpinion(expert=expert, emoji=emoji)
    return ExpertBrainOpinion(
        expert=str(raw.get("expert") or expert),
        emoji=str(raw.get("emoji") or emoji),
        focus_reviewed=[str(x) for x in (raw.get("focus_reviewed") or [])],
        observations=[str(x) for x in (raw.get("observations") or [])],
        candidate_experiments=[
            _parse_candidate(x)
            for x in (raw.get("candidate_experiments") or [])
            if isinstance(x, dict)
        ],
        intervene_recommended=bool(raw.get("intervene_recommended", True)),
    )


def _parse_synthesis(raw: dict[str, Any] | None) -> ExpertPanelSynthesis:
    if not isinstance(raw, dict):
        return ExpertPanelSynthesis(
            intervene_now=False,
            chair_summary="Insufficient panel data — stay consistent and gather more signal.",
        )
    selected = None
    sel = raw.get("selected_experiment")
    if isinstance(sel, dict):
        ev = sel.get("evidence") if isinstance(sel.get("evidence"), dict) else {}
        selected = SynthesizedExperiment(
            action=str(sel.get("action") or ""),
            category=str(sel.get("category") or "other"),
            evidence=EvidenceLayers(
                general_evidence=str(ev.get("general_evidence") or ""),
                coaching_heuristic=str(ev.get("coaching_heuristic") or ""),
                personal_evidence=str(ev.get("personal_evidence") or ""),
            ),
            how_to_judge=str(sel.get("how_to_judge") or ""),
            duration_days=int(sel.get("duration_days") or 14),
            confidence=float(sel.get("confidence") or 0.5),
            framing=str(
                sel.get("framing")
                or "This is the next evidence-based experiment, not a prescription."
            ),
        )
    return ExpertPanelSynthesis(
        intervene_now=bool(raw.get("intervene_now", True)),
        no_change_reason=raw.get("no_change_reason"),
        selected_experiment=selected,
        rejected_alternatives=[
            RejectedAlternative(
                action=str(x.get("action") or ""),
                why_not_now=str(x.get("why_not_now") or ""),
            )
            for x in (raw.get("rejected_alternatives") or [])
            if isinstance(x, dict)
        ],
        chair_summary=str(raw.get("chair_summary") or ""),
    )


def parse_expert_panel(raw: dict[str, Any] | None) -> ExpertPanel | None:
    if not isinstance(raw, dict):
        return None
    return ExpertPanel(
        nutritionist=_parse_brain(raw.get("nutritionist"), expert="nutritionist", emoji="🧠"),
        fitness_coach=_parse_brain(raw.get("fitness_coach"), expert="fitness_coach", emoji="💪"),
        weight_loss_coach=_parse_brain(
            raw.get("weight_loss_coach"), expert="weight_loss_coach", emoji="⚖️"
        ),
        research_advisor=_parse_brain(
            raw.get("research_advisor"), expert="research_advisor", emoji="📚"
        ),
        synthesis=_parse_synthesis(raw.get("synthesis")),
    )


def fallback_expert_panel() -> ExpertPanel:
    experiment = SynthesizedExperiment(
        action="Stay the course — compare 7-day averages for another week before changing anything.",
        category="no_change",
        evidence=EvidenceLayers(
            general_evidence=(
                "Short-term scale stalls are common during fat loss; water, glycogen, and sodium "
                "can mask trend changes for several days."
            ),
            coaching_heuristic=(
                "Experienced coaches rarely change the plan based on fewer than 7–10 days of data "
                "when weekly averages are still moving in the right direction."
            ),
            personal_evidence="Add more daily summaries and My Meals so the panel can personalize.",
        ),
        how_to_judge=(
            "If your 7-day average weight is flat or rising for 14+ days with consistent adherence, "
            "revisit the panel."
        ),
        duration_days=7,
        confidence=0.55,
    )
    return ExpertPanel(
        nutritionist=ExpertBrainOpinion(
            expert="nutritionist",
            emoji="🧠",
            focus_reviewed=["fiber", "protein quality", "satiety"],
            observations=["Log My Meals to unlock food-quality coaching."],
            candidate_experiments=[
                CandidateExperiment(
                    action="Add 2–3 recurring meals to My Meals",
                    rationale="Enables fiber/processing/satiety analysis.",
                    priority=0.7,
                    category="nutrition",
                )
            ],
        ),
        fitness_coach=ExpertBrainOpinion(
            expert="fitness_coach",
            emoji="💪",
            focus_reviewed=["steps", "recovery", "NEAT"],
            observations=["Sync activity data for movement-based experiments."],
        ),
        weight_loss_coach=ExpertBrainOpinion(
            expert="weight_loss_coach",
            emoji="⚖️",
            focus_reviewed=["trend", "adherence"],
            observations=["One morning tells you little — watch the weekly average."],
            intervene_recommended=False,
        ),
        research_advisor=ExpertBrainOpinion(
            expert="research_advisor",
            emoji="📚",
            focus_reviewed=["intervention timing", "evidence hierarchy"],
            observations=[
                "Activity increases are often tried before further calorie cuts to preserve diet quality."
            ],
        ),
        synthesis=ExpertPanelSynthesis(
            intervene_now=False,
            no_change_reason="Not enough personalized signal yet to justify a change.",
            selected_experiment=experiment,
            chair_summary=(
                "The panel recommends patience: gather meal staples and a longer trend window "
                "before running a targeted experiment."
            ),
            rejected_alternatives=[
                RejectedAlternative(
                    action="Cut calories further",
                    why_not_now="Premature without confirmed plateau and adherence data.",
                )
            ],
        ),
    )
