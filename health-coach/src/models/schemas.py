"""Pydantic request and response models for the v0 API."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class DailySummaryMetrics(BaseModel):
    weight_kg: Optional[float] = None
    weight_7d_average: Optional[float] = None
    weight_trend_kg_per_week: Optional[float] = None
    weight_change_from_yesterday_kg: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    steps: Optional[float] = None
    active_energy_kcal: Optional[float] = None
    strength_training_minutes: Optional[float] = None
    cardio_minutes: Optional[float] = None
    sleep_hours: Optional[float] = None
    cycle_day: Optional[int] = None
    period_status: Optional[str] = None
    restaurant_meal: bool = False
    alcohol_servings: float = 0.0
    data_completeness_score: float = 0.0


class DailySummaryResponse(BaseModel):
    date: date
    summary: DailySummaryMetrics


class HypothesisResult(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    counterevidence: list[str]
    missing_information: list[str] = Field(default_factory=list)
    recommended_next_action: Optional[str] = None


class ObservationBlock(BaseModel):
    date: date
    today_weight_kg: Optional[float] = None
    yesterday_weight_kg: Optional[float] = None
    change_kg: Optional[float] = None
    weight_7d_average_kg: Optional[float] = None
    weight_trend_kg_per_week: Optional[float] = None
    calories_today: Optional[float] = None
    calories_7d_avg: Optional[float] = None
    calorie_target: float
    sodium_mg: Optional[float] = None
    restaurant_meal: bool = False
    alcohol_servings: float = 0.0
    sleep_hours: Optional[float] = None
    strength_training_minutes: Optional[float] = None
    data_completeness_score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class HypothesisDebate(BaseModel):
    id: str
    title: str
    probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    disconfirm_test: Optional[str] = None


class EnergyBalanceBelief(BaseModel):
    stance: str
    confidence: float
    supporting_evidence: list[str] = Field(default_factory=list)
    contradictory_evidence: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    note: str = ""


class RecommendationItem(BaseModel):
    action: str
    rationale: str
    linked_hypothesis: Optional[str] = None


class ReasoningTrace(BaseModel):
    """Auditable scientist reasoning object — LLM narrates this; it does not invent it."""

    date: date
    observation: ObservationBlock
    hypotheses: list[HypothesisDebate]
    primary_hypothesis_id: str
    energy_balance: EnergyBalanceBelief
    missing_information: list[str] = Field(default_factory=list)
    confidence: float
    recommended_action: str
    expected_outcome: str
    follow_up_condition: str
    what_would_change_my_mind: str
    personalized_patterns: list[dict] = Field(default_factory=list)
    method: str
    recommendations: list[RecommendationItem] = Field(default_factory=list)


class WeightExplanationResponse(BaseModel):
    date: date
    question: str = "Why did my weight change today, and should I adjust my plan?"
    summary: DailySummaryMetrics
    primary_hypothesis: str
    confidence: float
    hypotheses: list[HypothesisResult]
    recommendations: list[RecommendationItem]
    observations: list[str]
    caveats: list[str]


class ImportResult(BaseModel):
    source: str
    filename: str
    measurements_imported: int
    contexts_imported: int
    summaries_built: int
    user_id: int


class HealthAutoExportSyncResult(BaseModel):
    source: str = "health_auto_export"
    measurements_imported: int
    workouts_imported: int
    contexts_imported: int
    skipped_groups_or_rows: int
    summaries_built: int
    user_id: int
    import_batch_id: int


class ChatAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: Optional[int] = None


class ChatAskResponse(BaseModel):
    reply: str
    model: str
    context_days: int = 0
    thread_id: int
    patterns_used: int = 0
    interventions_in_context: int = 0
    reasoning_trace: Optional[ReasoningTrace] = None


class PhysiologyPatternOut(BaseModel):
    pattern_key: str
    title: str
    description: str
    trigger: str
    effect: str
    typical_delta: Optional[float] = None
    unit: str = "kg"
    support_count: int
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    counterevidence: list[str] = Field(default_factory=list)
    last_seen_date: Optional[str] = None
    caveat: str = "Association from your history — not proven causation."


class InterventionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hypothesis: str = Field(min_length=1, max_length=2000)
    start_date: date
    end_date: Optional[date] = None
    category: Optional[str] = None
    instructions: Optional[str] = None
    target_metrics: list[str] = Field(default_factory=lambda: ["weight_trend"])


class InterventionOut(BaseModel):
    id: int
    name: str
    hypothesis: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    instructions: Optional[str] = None
    target_metrics: Optional[list[str]] = None
    adherence: Optional[float] = None
    results: Optional[dict] = None
    confounding_factors: Optional[list[str]] = None
    result_confidence: Optional[float] = None
    status: str


class BriefDayPoint(BaseModel):
    date: date
    weight_kg: Optional[float] = None
    weight_7d_average: Optional[float] = None
    weight_trend_kg_per_week: Optional[float] = None
    weight_change_from_yesterday_kg: Optional[float] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    sleep_hours: Optional[float] = None
    steps: Optional[float] = None
    restaurant_meal: bool = False
    alcohol_servings: float = 0.0
    strength_training_minutes: Optional[float] = None
    data_completeness_score: float = 0.0


class BriefResponse(BaseModel):
    as_of: Optional[date] = None
    calorie_target: float
    calorie_target_source: str = "default"  # user | default
    series: list[BriefDayPoint] = Field(default_factory=list)
    explanation: Optional[WeightExplanationResponse] = None
    reasoning_trace: Optional[ReasoningTrace] = None
    coaching: Optional["CoachingPack"] = None
    patterns: list[PhysiologyPatternOut] = Field(default_factory=list)
    food_staples: list["FoodStapleOut"] = Field(default_factory=list)
    meal_intelligence: Optional["MealIntelligencePack"] = None
    decision_ranking: Optional["DecisionRanking"] = None
    check_in_summary: Optional[dict[str, Any]] = None


class PreferencesOut(BaseModel):
    calorie_target: float
    source: str = "default"  # user | default
    display_name: Optional[str] = None


class PreferencesUpdate(BaseModel):
    calorie_target: float = Field(ge=800, le=6000)


class CheckInCreate(BaseModel):
    logged_at: Optional[str] = None
    period: Optional[str] = None  # morning|afternoon|evening|post_meal
    hunger: Optional[int] = Field(default=None, ge=0, le=10)
    energy: Optional[int] = Field(default=None, ge=0, le=10)
    stress: Optional[int] = Field(default=None, ge=0, le=10)
    cravings: Optional[int] = Field(default=None, ge=0, le=10)
    bloating: Optional[int] = Field(default=None, ge=0, le=10)
    digestion: Optional[str] = None  # normal|constipated|diarrhea
    notes: Optional[str] = None
    meal_event_id: Optional[int] = None


class CheckInOut(BaseModel):
    id: int
    logged_at: Optional[str] = None
    period: Optional[str] = None
    hunger: Optional[int] = None
    energy: Optional[int] = None
    stress: Optional[int] = None
    cravings: Optional[int] = None
    bloating: Optional[int] = None
    digestion: Optional[str] = None
    notes: Optional[str] = None
    meal_event_id: Optional[int] = None
    source: str = "manual"


class DecisionOpportunity(BaseModel):
    key: str
    label: str
    action: str
    expected_impact: str  # high|medium|low
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    data_basis: str = ""
    tier: int = 1


class DecisionRanking(BaseModel):
    opportunities: list[DecisionOpportunity] = Field(default_factory=list)
    mindset: str = (
        "Can we estimate well enough to make a better decision than the user alone?"
    )
    missing_for_better: list[str] = Field(default_factory=list)


class MealEventCreate(BaseModel):
    name: Optional[str] = None
    staple_id: Optional[int] = None
    eaten_at: Optional[str] = None  # ISO datetime
    meal_slot: Optional[str] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbohydrate_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    whole_food_score: Optional[float] = Field(default=None, ge=0, le=10)
    processing_score: Optional[float] = Field(default=None, ge=0, le=10)
    satiety_hours: Optional[float] = None
    hunger_returned_at: Optional[str] = None
    energy_after: Optional[int] = Field(default=None, ge=1, le=10)
    craving_after: Optional[bool] = None
    followed_by_snack: Optional[bool] = None
    workout_hours_after: Optional[float] = None
    enjoyment: Optional[int] = Field(default=None, ge=1, le=10)
    digestive_comfort: Optional[int] = Field(default=None, ge=1, le=10)
    notes: Optional[str] = None


class MealEventOut(BaseModel):
    id: int
    staple_id: Optional[int] = None
    eaten_at: Optional[str] = None
    meal_slot: Optional[str] = None
    name: str
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbohydrate_g: Optional[float] = None
    fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    whole_food_score: Optional[float] = None
    processing_score: Optional[float] = None
    satiety_hours: Optional[float] = None
    hunger_returned_at: Optional[str] = None
    energy_after: Optional[int] = None
    craving_after: Optional[bool] = None
    followed_by_snack: Optional[bool] = None
    workout_hours_after: Optional[float] = None
    enjoyment: Optional[int] = None
    digestive_comfort: Optional[int] = None
    notes: Optional[str] = None
    source: str = "manual"


class MealPatternInsight(BaseModel):
    key: str
    category: str
    title: str
    insight: str
    confidence: float = 0.5
    support: int = 0


class HungerPrediction(BaseModel):
    risk: str = "unknown"
    message: str
    suggested_action: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)


class MealReview(BaseModel):
    staple_id: int
    name: str
    times_logged: int = 0
    profile: dict[str, Any] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    summary: str = ""


class MealIntelligencePack(BaseModel):
    patterns: list[MealPatternInsight] = Field(default_factory=list)
    hunger_prediction: Optional[HungerPrediction] = None
    meal_reviews: list[MealReview] = Field(default_factory=list)
    recent_events: list[MealEventOut] = Field(default_factory=list)
    event_count: int = 0


class FoodStapleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    meal_slot: Optional[str] = None
    description: Optional[str] = None
    ingredients: Optional[str] = None
    is_packaged: bool = False
    brand: Optional[str] = None
    frequency: Optional[str] = "often"
    estimated_calories: Optional[float] = None
    estimated_protein_g: Optional[float] = None
    estimated_carbs_g: Optional[float] = None
    estimated_fat_g: Optional[float] = None
    estimated_fiber_g: Optional[float] = None
    estimated_sugar_g: Optional[float] = None
    notes: Optional[str] = None


class FoodStapleOut(BaseModel):
    id: int
    name: str
    meal_slot: Optional[str] = None
    description: Optional[str] = None
    ingredients: Optional[str] = None
    is_packaged: bool = False
    brand: Optional[str] = None
    frequency: Optional[str] = None
    estimated_calories: Optional[float] = None
    estimated_protein_g: Optional[float] = None
    estimated_carbs_g: Optional[float] = None
    estimated_fat_g: Optional[float] = None
    estimated_fiber_g: Optional[float] = None
    estimated_sugar_g: Optional[float] = None
    notes: Optional[str] = None
    quality_flags: list[str] = Field(default_factory=list)
    quality_notes: Optional[str] = None
    learned_profile: Optional[dict[str, Any]] = None
    times_logged: int = 0
    source: str = "manual"


class LeverItem(BaseModel):
    key: str
    label: str
    status: str  # ok | watch | risk | unknown
    why: str
    tune: str


class TomorrowExperiment(BaseModel):
    title: str
    action: str
    why: str
    how_to_judge: str
    effort: str = "low"


class FoodQualityReview(BaseModel):
    staple_id: Optional[int] = None
    name: str
    flags: list[str] = Field(default_factory=list)
    verdict: str
    swap_suggestion: Optional[str] = None
    satiety_score: Optional[int] = Field(default=None, ge=1, le=10)


class DietMeal(BaseModel):
    slot: str
    name: str
    notes: Optional[str] = None
    uses_staple: bool = False
    estimated_satiety: Optional[int] = Field(default=None, ge=1, le=10)


class DietDay(BaseModel):
    label: str
    meals: list[DietMeal] = Field(default_factory=list)


class DietSketch(BaseModel):
    title: str
    calorie_guidance: str
    principles: list[str] = Field(default_factory=list)
    days: list[DietDay] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class HighestLeverageAction(BaseModel):
    action: str
    reason: str
    expected_impact: str
    effort: str = "low"
    category: str  # sleep | food_quality | protein | fiber | sodium | adherence | movement | other


class CandidateExperiment(BaseModel):
    action: str
    rationale: str
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    category: str = "other"


class ExpertBrainOpinion(BaseModel):
    expert: str
    emoji: str = ""
    focus_reviewed: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    candidate_experiments: list[CandidateExperiment] = Field(default_factory=list)
    intervene_recommended: bool = True


class EvidenceLayers(BaseModel):
    general_evidence: str = ""
    coaching_heuristic: str = ""
    personal_evidence: str = ""


class SynthesizedExperiment(BaseModel):
    action: str
    category: str = "other"
    evidence: EvidenceLayers = Field(default_factory=EvidenceLayers)
    how_to_judge: str = ""
    duration_days: int = 14
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    framing: str = "This is the next evidence-based experiment, not a prescription."


class RejectedAlternative(BaseModel):
    action: str
    why_not_now: str


class ExpertPanelSynthesis(BaseModel):
    intervene_now: bool = True
    no_change_reason: Optional[str] = None
    selected_experiment: Optional[SynthesizedExperiment] = None
    rejected_alternatives: list[RejectedAlternative] = Field(default_factory=list)
    chair_summary: str = ""


class ExpertPanel(BaseModel):
    nutritionist: ExpertBrainOpinion
    fitness_coach: ExpertBrainOpinion
    weight_loss_coach: ExpertBrainOpinion
    research_advisor: ExpertBrainOpinion
    synthesis: ExpertPanelSynthesis


class PlateauInvestigation(BaseModel):
    summary: str
    ranked_causes: list[str] = Field(default_factory=list)
    ruled_out: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CoachingPack(BaseModel):
    headline: str
    stuck_story: str
    what_matters_now: list[str] = Field(default_factory=list)
    levers: list[LeverItem] = Field(default_factory=list)
    tomorrow_experiments: list[TomorrowExperiment] = Field(default_factory=list)
    food_quality_reviews: list[FoodQualityReview] = Field(default_factory=list)
    diet_sketch: Optional[DietSketch] = None
    watch_outs: list[str] = Field(default_factory=list)
    highest_leverage: Optional[HighestLeverageAction] = None
    plateau: Optional[PlateauInvestigation] = None
    adherence_loops: list[str] = Field(default_factory=list)
    friction_notes: list[str] = Field(default_factory=list)
    recovery_chain: Optional[str] = None
    nutrition_quality_story: Optional[str] = None
    expert_panel: Optional[ExpertPanel] = None
