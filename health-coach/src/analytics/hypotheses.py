"""Deterministic hypothesis scoring for daily weight changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from src.db.models import DailySummary
from src.models.schemas import HypothesisResult


@dataclass
class AnalysisContext:
    today: DailySummary
    history: list[DailySummary]
    calorie_target: float = 1700.0

    @property
    def weight_change(self) -> Optional[float]:
        return self.today.weight_change_from_yesterday_kg

    @property
    def trend(self) -> Optional[float]:
        return self.today.weight_trend_kg_per_week

    def baseline_sodium(self) -> Optional[float]:
        values = [d.sodium_mg for d in self.history[:-1] if d.sodium_mg is not None]
        return mean(values) if values else None

    def recent_avg_calories(self, days: int = 7) -> Optional[float]:
        window = [d.calories for d in self.history[-days:] if d.calories is not None]
        return mean(window) if window else None

    def yesterday(self) -> Optional[DailySummary]:
        if len(self.history) < 2:
            return None
        return self.history[-2]


@dataclass
class ScoredHypothesis:
    name: str
    score: float
    confidence: float
    evidence: list[str] = field(default_factory=list)
    counterevidence: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    recommended_next_action: Optional[str] = None

    def to_result(self) -> HypothesisResult:
        return HypothesisResult(
            name=self.name,
            score=round(min(max(self.score, 0.0), 1.0), 3),
            confidence=round(min(max(self.confidence, 0.0), 1.0), 3),
            evidence=self.evidence,
            counterevidence=self.counterevidence,
            missing_information=self.missing_information,
            recommended_next_action=self.recommended_next_action,
        )


def score_measurement_noise(ctx: AnalysisContext) -> ScoredHypothesis:
    change = abs(ctx.weight_change) if ctx.weight_change is not None else None
    evidence: list[str] = []
    counter: list[str] = []
    missing: list[str] = []
    score = 0.15
    confidence = 0.5

    if change is None:
        missing.append("Day-over-day weight change is unavailable")
        return ScoredHypothesis(
            name="normal_measurement_noise",
            score=0.2,
            confidence=0.3,
            evidence=evidence,
            counterevidence=counter,
            missing_information=missing,
            recommended_next_action="Collect consistent morning weigh-ins before interpreting changes",
        )

    if change < 0.4:
        score += 0.45
        evidence.append(f"Weight change of {ctx.weight_change:+.2f} kg is within typical day-to-day scale noise")
        confidence += 0.2
    elif change < 0.7:
        score += 0.2
        evidence.append(f"Weight change of {ctx.weight_change:+.2f} kg is moderate and could still include measurement noise")
    else:
        counter.append(f"Weight change of {ctx.weight_change:+.2f} kg is larger than typical measurement noise alone")
        score -= 0.05

    if ctx.today.data_completeness_score < 0.6:
        score += 0.15
        evidence.append("Data completeness is limited, so noise/uncertainty is higher")
        missing.append("Some core metrics are missing for recent days")

    if ctx.trend is not None and abs(ctx.trend) < 0.2 and change >= 0.5:
        evidence.append("Seven-day trend is nearly flat despite today's swing, consistent with noise or temporary water")
        score += 0.1

    return ScoredHypothesis(
        name="normal_measurement_noise",
        score=score,
        confidence=confidence,
        evidence=evidence or ["No strong noise signal beyond baseline uncertainty"],
        counterevidence=counter,
        missing_information=missing,
        recommended_next_action="Prefer the 7-day average over a single weigh-in",
    )


def score_temporary_water_retention(ctx: AnalysisContext) -> ScoredHypothesis:
    evidence: list[str] = []
    counter: list[str] = []
    missing: list[str] = []
    score = 0.1
    confidence = 0.45

    change = ctx.weight_change
    yesterday = ctx.yesterday()
    baseline_na = ctx.baseline_sodium()

    if change is None or change <= 0.2:
        if change is not None and change <= 0.2:
            counter.append("Weight did not rise enough to strongly suggest water retention")
        return ScoredHypothesis(
            name="temporary_water_retention",
            score=max(score, 0.1),
            confidence=confidence,
            evidence=evidence or ["No clear water-retention signal from today's change"],
            counterevidence=counter,
            missing_information=missing,
            recommended_next_action="Continue normal hydration and reassess after two morning weigh-ins",
        )

    if change >= 0.5:
        score += 0.2
        evidence.append(f"Scale increased {change:+.2f} kg from yesterday")

    # Sodium / restaurant / alcohol signals from yesterday (affects morning weight).
    signal_day = yesterday or ctx.today
    if signal_day.restaurant_meal:
        score += 0.2
        evidence.append("A restaurant meal was recorded the day before the weigh-in")
    if signal_day.alcohol_servings and signal_day.alcohol_servings > 0:
        score += 0.1
        evidence.append(f"Alcohol servings recorded previously: {signal_day.alcohol_servings:g}")

    if signal_day.sodium_mg is not None and baseline_na is not None:
        delta = signal_day.sodium_mg - baseline_na
        if delta > 600:
            score += 0.25
            evidence.append(
                f"Estimated sodium was {delta:.0f} mg above the recent baseline ({baseline_na:.0f} mg)"
            )
        elif delta < 0:
            counter.append("Sodium was not above the recent baseline")
    else:
        missing.append("Sodium baseline or prior-day sodium is incomplete")
        confidence -= 0.1

    if ctx.trend is not None and ctx.trend < 0:
        score += 0.15
        evidence.append(
            f"Seven-day weight trend remains decreasing ({ctx.trend:+.2f} kg/week)"
        )

    # Calorie balance argument: large gain unlikely to be pure fat in one day.
    recent_cal = ctx.recent_avg_calories()
    if recent_cal is not None:
        surplus = recent_cal - ctx.calorie_target
        if surplus < 400 and change >= 0.5:
            score += 0.15
            evidence.append(
                "Estimated calorie intake is close to target; the gain is too large for one day of fat alone"
            )
        elif surplus >= 500:
            counter.append("Recent calories were meaningfully above target, so surplus remains possible")
    else:
        missing.append("Recent calorie data is incomplete")

    if signal_day.period_status in {"period", "late_luteal"} or (
        signal_day.cycle_day is not None and signal_day.cycle_day <= 3
    ):
        score += 0.1
        evidence.append("Menstrual-cycle context is consistent with higher water retention risk")

    if signal_day.strength_training_minutes and signal_day.strength_training_minutes >= 45:
        score += 0.05
        evidence.append("A longer strength session occurred recently (possible inflammation-related water)")

    confidence = min(0.9, confidence + 0.05 * len(evidence))
    return ScoredHypothesis(
        name="temporary_water_retention",
        score=score,
        confidence=confidence,
        evidence=evidence,
        counterevidence=counter,
        missing_information=missing,
        recommended_next_action="Do not cut calories from one weigh-in; reassess after two more mornings",
    )


def score_possible_calorie_surplus(ctx: AnalysisContext) -> ScoredHypothesis:
    evidence: list[str] = []
    counter: list[str] = []
    missing: list[str] = []
    score = 0.1
    confidence = 0.4

    recent_cal = ctx.recent_avg_calories(days=7)
    change = ctx.weight_change
    trend = ctx.trend

    if recent_cal is None:
        missing.append("Calorie history is incomplete")
        return ScoredHypothesis(
            name="possible_calorie_surplus",
            score=0.15,
            confidence=0.25,
            evidence=["Unable to estimate surplus without calorie history"],
            counterevidence=counter,
            missing_information=missing,
            recommended_next_action="Improve calorie logging completeness before adjusting targets",
        )

    surplus = recent_cal - ctx.calorie_target
    if surplus >= 250:
        score += 0.35
        evidence.append(
            f"7-day average intake ({recent_cal:.0f} kcal) is above target ({ctx.calorie_target:.0f} kcal)"
        )
        confidence += 0.15
    elif surplus >= 100:
        score += 0.15
        evidence.append("Recent average intake is slightly above target")
    else:
        counter.append(
            f"7-day average intake ({recent_cal:.0f} kcal) is at or below target ({ctx.calorie_target:.0f} kcal)"
        )
        score -= 0.05

    if trend is not None and trend > 0.2:
        score += 0.3
        evidence.append(f"Seven-day weight trend is rising ({trend:+.2f} kg/week)")
        confidence += 0.15
    elif trend is not None and trend < 0:
        counter.append(f"Seven-day weight trend is still decreasing ({trend:+.2f} kg/week)")
        score -= 0.1

    if change is not None and change >= 0.8 and surplus < 300:
        counter.append("Single-day gain magnitude exceeds what short-term surplus alone typically explains")
        score -= 0.05

    if ctx.today.protein_g is not None and ctx.today.protein_g < 120:
        evidence.append("Protein is relatively low today, which can make adherence harder over time")
        score += 0.05

    return ScoredHypothesis(
        name="possible_calorie_surplus",
        score=max(score, 0.05),
        confidence=min(confidence, 0.85),
        evidence=evidence or ["No strong surplus signal from available intake and trend"],
        counterevidence=counter,
        missing_information=missing,
        recommended_next_action="Use multi-week trend before changing calorie targets",
    )


def evaluate_weight_hypotheses(
    today: DailySummary,
    history: list[DailySummary],
    *,
    calorie_target: float = 1700.0,
) -> list[HypothesisResult]:
    ctx = AnalysisContext(today=today, history=history, calorie_target=calorie_target)
    scored = [
        score_measurement_noise(ctx),
        score_temporary_water_retention(ctx),
        score_possible_calorie_surplus(ctx),
    ]
    scored.sort(key=lambda h: h.score, reverse=True)
    return [h.to_result() for h in scored]
