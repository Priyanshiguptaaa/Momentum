"""SQLAlchemy ORM models for the health-coach prototype."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    measurements: Mapped[list[Measurement]] = relationship(back_populates="user")
    daily_contexts: Mapped[list[DailyContext]] = relationship(back_populates="user")
    daily_summaries: Mapped[list[DailySummary]] = relationship(back_populates="user")
    source_files: Mapped[list[SourceFile]] = relationship(back_populates="user")
    hypotheses: Mapped[list[Hypothesis]] = relationship(back_populates="user")
    recommendations: Mapped[list[Recommendation]] = relationship(back_populates="user")
    meals: Mapped[list[Meal]] = relationship(back_populates="user")
    workouts: Mapped[list[Workout]] = relationship(back_populates="user")
    interventions: Mapped[list[Intervention]] = relationship(back_populates="user")
    physiology_patterns: Mapped[list[PhysiologyPattern]] = relationship(back_populates="user")
    chat_threads: Mapped[list[ChatThread]] = relationship(back_populates="user")
    food_staples: Mapped[list[FoodStaple]] = relationship(back_populates="user")
    meal_events: Mapped[list[MealEvent]] = relationship(back_populates="user")
    check_ins: Mapped[list[SubjectiveCheckIn]] = relationship(back_populates="user")


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[Optional[str]] = mapped_column(String(128))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="source_files")


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "metric_type",
            "timestamp",
            "source",
            "source_record_id",
            name="uq_measurement_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[Optional[str]] = mapped_column(String(128))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_files.id"))

    user: Mapped[User] = relationship(back_populates="measurements")


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    meal_type: Mapped[Optional[str]] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(Text)
    calories: Mapped[Optional[float]] = mapped_column(Float)
    protein_g: Mapped[Optional[float]] = mapped_column(Float)
    carbohydrate_g: Mapped[Optional[float]] = mapped_column(Float)
    fat_g: Mapped[Optional[float]] = mapped_column(Float)
    fiber_g: Mapped[Optional[float]] = mapped_column(Float)
    sodium_mg: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_files.id"))

    user: Mapped[User] = relationship(back_populates="meals")


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    workout_type: Mapped[Optional[str]] = mapped_column(String(64))
    duration_minutes: Mapped[Optional[float]] = mapped_column(Float)
    active_calories: Mapped[Optional[float]] = mapped_column(Float)
    average_heart_rate: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_files.id"))

    user: Mapped[User] = relationship(back_populates="workouts")
    exercise_sets: Mapped[list[ExerciseSet]] = relationship(back_populates="workout")


class ExerciseSet(Base):
    __tablename__ = "exercise_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id"), nullable=False)
    exercise_name: Mapped[str] = mapped_column(String(128), nullable=False)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    repetitions: Mapped[Optional[int]] = mapped_column(Integer)
    rpe: Mapped[Optional[float]] = mapped_column(Float)
    is_warmup: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    workout: Mapped[Workout] = relationship(back_populates="exercise_sets")


class DailyContext(Base):
    __tablename__ = "daily_contexts"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_context_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    menstrual_cycle_day: Mapped[Optional[int]] = mapped_column(Integer)
    period_status: Mapped[Optional[str]] = mapped_column(String(32))
    travel: Mapped[bool] = mapped_column(Boolean, default=False)
    restaurant_meal: Mapped[bool] = mapped_column(Boolean, default=False)
    alcohol_servings: Mapped[float] = mapped_column(Float, default=0.0)
    illness: Mapped[bool] = mapped_column(Boolean, default=False)
    stress_rating: Mapped[Optional[float]] = mapped_column(Float)
    hunger_rating: Mapped[Optional[float]] = mapped_column(Float)
    energy_rating: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    import_batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("source_files.id"))

    user: Mapped[User] = relationship(back_populates="daily_contexts")


class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    hypothesis: Mapped[Optional[str]] = mapped_column(Text)
    target_metrics: Mapped[Optional[list[str]]] = mapped_column(JSON)
    adherence: Mapped[Optional[float]] = mapped_column(Float)
    results: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    confounding_factors: Mapped[Optional[list[str]]] = mapped_column(JSON)
    result_confidence: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="interventions")


class PhysiologyPattern(Base):
    """Learned personal associations (not proven causation)."""

    __tablename__ = "physiology_patterns"
    __table_args__ = (
        UniqueConstraint("user_id", "pattern_key", name="uq_physiology_pattern_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(String(128), nullable=False)
    effect: Mapped[str] = mapped_column(String(128), nullable=False)
    typical_delta: Mapped[Optional[float]] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32), default="kg")
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    counterevidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_seen_date: Mapped[Optional[date]] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(64), default="auto")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="physiology_patterns")


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    title: Mapped[Optional[str]] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="chat_threads")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="thread", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("chat_threads.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    thread: Mapped[ChatThread] = relationship(back_populates="messages")


class FoodStaple(Base):
    """Foods/recipes the person eats consistently — for food-quality coaching."""

    __tablename__ = "food_staples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    meal_slot: Mapped[Optional[str]] = mapped_column(String(64))  # breakfast/lunch/dinner/snack
    description: Mapped[Optional[str]] = mapped_column(Text)
    ingredients: Mapped[Optional[str]] = mapped_column(Text)
    is_packaged: Mapped[bool] = mapped_column(Boolean, default=False)
    brand: Mapped[Optional[str]] = mapped_column(String(128))
    frequency: Mapped[Optional[str]] = mapped_column(String(64))  # daily/weekly/often
    estimated_calories: Mapped[Optional[float]] = mapped_column(Float)
    estimated_protein_g: Mapped[Optional[float]] = mapped_column(Float)
    estimated_carbs_g: Mapped[Optional[float]] = mapped_column(Float)
    estimated_fat_g: Mapped[Optional[float]] = mapped_column(Float)
    estimated_fiber_g: Mapped[Optional[float]] = mapped_column(Float)
    estimated_sugar_g: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    quality_flags: Mapped[Optional[list[str]]] = mapped_column(JSON)
    quality_notes: Mapped[Optional[str]] = mapped_column(Text)
    # Learned Behavioral Nutrition profile (satiety, craving risk, success rate, etc.)
    learned_profile: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    times_logged: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="food_staples")
    meal_events: Mapped[list["MealEvent"]] = relationship(back_populates="staple")


class MealEvent(Base):
    """Timed meal instance with outcomes — Behavioral Nutrition Intelligence."""

    __tablename__ = "meal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    staple_id: Mapped[Optional[int]] = mapped_column(ForeignKey("food_staples.id"))
    eaten_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    meal_slot: Mapped[Optional[str]] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    calories: Mapped[Optional[float]] = mapped_column(Float)
    protein_g: Mapped[Optional[float]] = mapped_column(Float)
    carbohydrate_g: Mapped[Optional[float]] = mapped_column(Float)
    fat_g: Mapped[Optional[float]] = mapped_column(Float)
    fiber_g: Mapped[Optional[float]] = mapped_column(Float)
    sodium_mg: Mapped[Optional[float]] = mapped_column(Float)
    whole_food_score: Mapped[Optional[float]] = mapped_column(Float)  # 0–10
    processing_score: Mapped[Optional[float]] = mapped_column(Float)  # 0–10 (higher = more processed)
    satiety_hours: Mapped[Optional[float]] = mapped_column(Float)
    hunger_returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    energy_after: Mapped[Optional[int]] = mapped_column(Integer)  # 1–10
    craving_after: Mapped[Optional[bool]] = mapped_column(Boolean)
    followed_by_snack: Mapped[Optional[bool]] = mapped_column(Boolean)
    workout_hours_after: Mapped[Optional[float]] = mapped_column(Float)
    enjoyment: Mapped[Optional[int]] = mapped_column(Integer)  # 1–10
    digestive_comfort: Mapped[Optional[int]] = mapped_column(Integer)  # 1–10
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="meal_events")
    staple: Mapped[Optional[FoodStaple]] = relationship(back_populates="meal_events")


class SubjectiveCheckIn(Base):
    """Quick feel-state check-in — unlocks objective↔subjective coaching."""

    __tablename__ = "subjective_check_ins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period: Mapped[Optional[str]] = mapped_column(String(32))  # morning|afternoon|evening|post_meal
    hunger: Mapped[Optional[int]] = mapped_column(Integer)  # 0–10
    energy: Mapped[Optional[int]] = mapped_column(Integer)  # 0–10
    stress: Mapped[Optional[int]] = mapped_column(Integer)  # 0–10
    cravings: Mapped[Optional[int]] = mapped_column(Integer)  # 0–10
    bloating: Mapped[Optional[int]] = mapped_column(Integer)  # 0–10
    digestion: Mapped[Optional[str]] = mapped_column(String(32))  # normal|constipated|diarrhea
    notes: Mapped[Optional[str]] = mapped_column(Text)
    meal_event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("meal_events.id"))
    source: Mapped[str] = mapped_column(String(64), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="check_ins")


class DailySummary(Base):
    __tablename__ = "daily_summaries"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_summary_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    morning_weight_kg: Mapped[Optional[float]] = mapped_column(Float)
    weight_7d_average: Mapped[Optional[float]] = mapped_column(Float)
    weight_14d_average: Mapped[Optional[float]] = mapped_column(Float)
    weight_trend_kg_per_week: Mapped[Optional[float]] = mapped_column(Float)
    weight_change_from_yesterday_kg: Mapped[Optional[float]] = mapped_column(Float)
    calories: Mapped[Optional[float]] = mapped_column(Float)
    protein_g: Mapped[Optional[float]] = mapped_column(Float)
    fiber_g: Mapped[Optional[float]] = mapped_column(Float)
    sodium_mg: Mapped[Optional[float]] = mapped_column(Float)
    steps: Mapped[Optional[float]] = mapped_column(Float)
    active_energy_kcal: Mapped[Optional[float]] = mapped_column(Float)
    resting_energy_kcal: Mapped[Optional[float]] = mapped_column(Float)
    strength_training_minutes: Mapped[Optional[float]] = mapped_column(Float)
    cardio_minutes: Mapped[Optional[float]] = mapped_column(Float)
    sleep_hours: Mapped[Optional[float]] = mapped_column(Float)
    resting_heart_rate: Mapped[Optional[float]] = mapped_column(Float)
    cycle_day: Mapped[Optional[int]] = mapped_column(Integer)
    period_status: Mapped[Optional[str]] = mapped_column(String(32))
    restaurant_meal: Mapped[bool] = mapped_column(Boolean, default=False)
    alcohol_servings: Mapped[float] = mapped_column(Float, default=0.0)
    active_interventions: Mapped[Optional[list[str]]] = mapped_column(JSON)
    data_completeness_score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="daily_summaries")


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    counterevidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_next_action: Mapped[Optional[str]] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship(back_populates="hypotheses")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    linked_hypothesis: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship(back_populates="recommendations")
