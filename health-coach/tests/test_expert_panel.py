"""Tests for expert panel parsing."""

from src.coaching.expert_panel import fallback_expert_panel, parse_expert_panel


def test_parse_expert_panel_full():
    raw = {
        "nutritionist": {
            "expert": "nutritionist",
            "emoji": "🧠",
            "observations": ["Fiber low"],
            "candidate_experiments": [
                {
                    "action": "Increase fiber to 30g",
                    "rationale": "Satiety",
                    "priority": 0.8,
                    "category": "nutrition",
                }
            ],
        },
        "fitness_coach": {"expert": "fitness_coach", "emoji": "💪"},
        "weight_loss_coach": {
            "expert": "weight_loss_coach",
            "emoji": "⚖️",
            "intervene_recommended": False,
        },
        "research_advisor": {"expert": "research_advisor", "emoji": "📚"},
        "synthesis": {
            "intervene_now": True,
            "chair_summary": "Fiber is the highest-leverage nutrition experiment.",
            "selected_experiment": {
                "action": "Increase fiber to 30g/day for 14 days",
                "category": "nutrition",
                "evidence": {
                    "general_evidence": "Fiber improves satiety.",
                    "coaching_heuristic": "Coaches try fiber before cutting calories.",
                    "personal_evidence": "Hunger spikes on low-fiber days.",
                },
                "how_to_judge": "Track evening hunger and 7-day average weight.",
                "duration_days": 14,
                "confidence": 0.7,
            },
            "rejected_alternatives": [
                {"action": "Cut 100 kcal", "why_not_now": "Trend still decreasing."}
            ],
        },
    }
    panel = parse_expert_panel(raw)
    assert panel is not None
    assert panel.nutritionist.observations == ["Fiber low"]
    assert panel.synthesis.selected_experiment is not None
    assert panel.synthesis.selected_experiment.action.startswith("Increase fiber")
    assert panel.synthesis.selected_experiment.evidence.general_evidence.startswith("Fiber")
    assert len(panel.synthesis.rejected_alternatives) == 1


def test_fallback_expert_panel_no_change():
    panel = fallback_expert_panel()
    assert panel.synthesis.intervene_now is False
    assert panel.synthesis.selected_experiment is not None
    assert panel.nutritionist.emoji == "🧠"
