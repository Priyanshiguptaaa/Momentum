"""FastAPI application — v0 endpoints."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.analytics.daily_summary import rebuild_daily_summaries
from src.analytics.check_ins import (
    check_in_summary,
    check_in_to_dict,
    create_check_in,
    delete_check_in,
    list_check_ins,
)
from src.analytics.decision_ranker import rank_decision_opportunities
from src.analytics.meal_intelligence import (
    build_bni_pack,
    build_meal_review,
    create_meal_event,
    delete_meal_event,
    list_meal_events,
    meal_event_to_dict,
)
from src.analytics.patterns import (
    list_patterns_for_user,
    pattern_to_dict,
    refresh_physiology_patterns,
)
from src.coaching.llm_reasoner import llm_build_reasoning_trace
from src.api.auth import require_sync_api_key
from src.coaching.explanation import _to_metrics, explain_weight_for_date
from src.coaching.food_staples import (
    create_food_staple,
    delete_food_staple,
    list_food_staples,
    staple_to_dict,
)
from src.coaching.interventions import (
    create_intervention,
    evaluate_intervention,
    intervention_to_dict,
    list_interventions,
)
from src.coaching.llm_chat import ask_health_question
from src.coaching.expert_panel import fallback_expert_panel
from src.coaching.preferences import get_calorie_target, get_preferences, update_preferences
from src.coaching.llm_coach import build_coaching_pack, build_plateau_investigation
from src.db.config import ROOT_DIR, settings
from src.db.models import DailySummary, User
from src.db.session import SessionLocal, get_db, init_db
from src.ingestion.csv_daily import import_daily_metrics_csv
from src.ingestion.health_auto_export import ingest_health_auto_export
from src.ingestion.hevy import HevyAPIError, fetch_hevy_user_info, sync_hevy
from src.models.schemas import (
    BriefDayPoint,
    BriefResponse,
    ChatAskRequest,
    ChatAskResponse,
    CoachingPack,
    DailySummaryResponse,
    ExpertPanel,
    FoodStapleCreate,
    FoodStapleOut,
    HealthAutoExportSyncResult,
    HevySyncResult,
    ImportResult,
    InterventionCreate,
    InterventionOut,
    CheckInCreate,
    CheckInOut,
    DecisionRanking,
    PreferencesOut,
    PreferencesUpdate,
    MealEventCreate,
    MealEventOut,
    MealIntelligencePack,
    MealReview,
    PhysiologyPatternOut,
    PlateauInvestigation,
    ReasoningTrace,
    WeightExplanationResponse,
)

APP_HTML = Path(__file__).resolve().parent / "static" / "chat.html"


def _run_hevy_sync_once(max_pages: int = 50) -> None:
    if not settings.hevy_api_key:
        return
    db = SessionLocal()
    try:
        result = sync_hevy(
            db,
            api_key=settings.hevy_api_key,
            user_email=settings.default_user_email,
            user_name=settings.default_user_name,
            max_pages=max_pages,
        )
        rebuild_daily_summaries(db, result["user_id"])
        refresh_physiology_patterns(db, result["user_id"])
        print(
            "[hevy-auto-sync] success "
            f"account={result.get('hevy_username') or 'unknown'} "
            f"imported={result['workouts_imported']} "
            f"updated={result['workouts_updated']} "
            f"sets={result['sets_imported']} "
            f"body={result.get('body_measurements_imported', 0)}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[hevy-auto-sync] failed: {exc}")
    finally:
        db.close()


def _seconds_until_next_hevy_sync(now: datetime) -> float:
    target_today = datetime.combine(
        now.date(),
        time(hour=settings.hevy_auto_sync_hour, minute=settings.hevy_auto_sync_minute),
    )
    if now >= target_today:
        target_today += timedelta(days=1)
    return max((target_today - now).total_seconds(), 1.0)


async def _nightly_hevy_sync_loop() -> None:
    while True:
        wait_seconds = _seconds_until_next_hevy_sync(datetime.now())
        await asyncio.sleep(wait_seconds)
        await asyncio.to_thread(_run_hevy_sync_once)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    scheduler_task: asyncio.Task | None = None
    if settings.hevy_auto_sync_enabled:
        valid_time = 0 <= settings.hevy_auto_sync_hour <= 23 and 0 <= settings.hevy_auto_sync_minute <= 59
        if not valid_time:
            print("[hevy-auto-sync] invalid hour/minute config; scheduler not started")
        elif settings.hevy_api_key:
            scheduler_task = asyncio.create_task(_nightly_hevy_sync_loop())
            print(
                "[hevy-auto-sync] enabled "
                f"at {settings.hevy_auto_sync_hour:02d}:{settings.hevy_auto_sync_minute:02d} "
                "(server local time)"
            )
        else:
            print("[hevy-auto-sync] enabled but HC_HEVY_API_KEY is missing; scheduler not started")
    try:
        yield
    finally:
        if scheduler_task:
            scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler_task


app = FastAPI(
    title="Momentum API",
    version="0.4.0",
    description="Momentum — AI health scientist: patterns, experiments, and evidence-backed explanations.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _serve_app() -> FileResponse:
    if not APP_HTML.is_file():
        raise HTTPException(status_code=404, detail="Momentum UI missing")
    return FileResponse(APP_HTML, media_type="text/html")


@app.get("/")
def home_page() -> FileResponse:
    return _serve_app()


@app.get("/chat")
def chat_page() -> FileResponse:
    return _serve_app()


@app.get(
    "/brief",
    response_model=BriefResponse,
    dependencies=[Depends(require_sync_api_key)],
)
def get_brief(
    days: int = Query(default=14, ge=7, le=60),
    include_ai: bool = Query(
        default=False,
        description="If true, run LLM coaching/trace inline (slow). Prefer GET /coaching after lean brief.",
    ),
    db: Session = Depends(get_db),
) -> BriefResponse:
    """Home brief: series + decisions first. AI coaching is deferred unless include_ai=true."""
    user = db.scalar(select(User).order_by(User.id).limit(1))
    prefs = get_preferences(db)
    target = float(prefs["calorie_target"])
    maint = prefs.get("estimated_maintenance")
    rationale = prefs.get("rationale")
    if user is None:
        return BriefResponse(
            calorie_target=target,
            calorie_target_source=str(prefs.get("source") or "seed_default"),
            estimated_maintenance=maint,
            calorie_target_rationale=rationale,
        )

    latest = db.scalar(
        select(DailySummary)
        .where(DailySummary.user_id == user.id)
        .order_by(DailySummary.date.desc())
        .limit(1)
    )
    if latest is None:
        return BriefResponse(
            calorie_target=target,
            calorie_target_source=str(prefs.get("source") or "seed_default"),
            estimated_maintenance=maint,
            calorie_target_rationale=rationale,
            patterns=[
                PhysiologyPatternOut(**pattern_to_dict(p))
                for p in list_patterns_for_user(db, user.id)
            ],
        )

    start = latest.date - timedelta(days=days - 1)
    rows = list(
        db.scalars(
            select(DailySummary)
            .where(
                DailySummary.user_id == user.id,
                DailySummary.date >= start,
                DailySummary.date <= latest.date,
            )
            .order_by(DailySummary.date)
        ).all()
    )
    series = [
        BriefDayPoint(
            date=r.date,
            weight_kg=r.morning_weight_kg,
            weight_7d_average=r.weight_7d_average,
            weight_trend_kg_per_week=r.weight_trend_kg_per_week,
            weight_change_from_yesterday_kg=r.weight_change_from_yesterday_kg,
            calories=r.calories,
            protein_g=r.protein_g,
            sleep_hours=r.sleep_hours,
            steps=r.steps,
            restaurant_meal=bool(r.restaurant_meal),
            alcohol_servings=float(r.alcohol_servings or 0),
            strength_training_minutes=r.strength_training_minutes,
            data_completeness_score=float(r.data_completeness_score or 0),
        )
        for r in rows
    ]

    # Lean metrics for the hero (no LLM) — always available from the daily row.
    explanation: WeightExplanationResponse | None = WeightExplanationResponse(
        date=latest.date,
        summary=_to_metrics(latest),
        primary_hypothesis="pending_ai",
        confidence=0.0,
        hypotheses=[],
        recommendations=[],
        observations=[],
        caveats=["AI coaching loads separately for a faster brief."],
    )
    reasoning_trace: ReasoningTrace | None = None
    coaching: CoachingPack | None = None
    ai_pending = not include_ai

    if include_ai:
        try:
            explanation = explain_weight_for_date(db, latest.date, user_id=user.id)
        except LookupError:
            pass
        try:
            reasoning_trace = llm_build_reasoning_trace(db, latest.date, user_id=user.id)
        except Exception:  # noqa: BLE001
            reasoning_trace = None
        try:
            coaching = build_coaching_pack(db, include_diet=False)
        except Exception:  # noqa: BLE001
            coaching = None
        ai_pending = False

    try:
        staples = [FoodStapleOut(**staple_to_dict(s)) for s in list_food_staples(db)]
    except LookupError:
        staples = []

    meal_intelligence: MealIntelligencePack | None = None
    try:
        meal_intelligence = MealIntelligencePack(**build_bni_pack(db))
    except Exception:  # noqa: BLE001
        meal_intelligence = None

    decision_ranking: DecisionRanking | None = None
    try:
        decision_ranking = rank_decision_opportunities(db)
    except Exception:  # noqa: BLE001
        decision_ranking = None

    check_summary: dict | None = None
    try:
        check_summary = check_in_summary(db)
    except Exception:  # noqa: BLE001
        check_summary = None

    return BriefResponse(
        as_of=latest.date,
        calorie_target=target,
        calorie_target_source=str(prefs.get("source") or "body_data"),
        estimated_maintenance=maint,
        calorie_target_rationale=rationale,
        series=series,
        explanation=explanation,
        reasoning_trace=reasoning_trace,
        coaching=coaching,
        patterns=[
            PhysiologyPatternOut(**pattern_to_dict(p))
            for p in list_patterns_for_user(db, user.id)
        ],
        food_staples=staples,
        meal_intelligence=meal_intelligence,
        decision_ranking=decision_ranking,
        check_in_summary=check_summary,
        ai_pending=ai_pending,
    )


@app.get(
    "/expert-panel",
    response_model=ExpertPanel,
    dependencies=[Depends(require_sync_api_key)],
)
def get_expert_panel(db: Session = Depends(get_db)) -> ExpertPanel:
    pack = build_coaching_pack(db, include_diet=False)
    return pack.expert_panel or fallback_expert_panel()


@app.get(
    "/coaching",
    response_model=CoachingPack,
    dependencies=[Depends(require_sync_api_key)],
)
def get_coaching(db: Session = Depends(get_db)) -> CoachingPack:
    return build_coaching_pack(db, include_diet=False)


@app.get(
    "/plateau",
    response_model=PlateauInvestigation,
    dependencies=[Depends(require_sync_api_key)],
)
def get_plateau(db: Session = Depends(get_db)) -> PlateauInvestigation:
    return build_plateau_investigation(db)


@app.get(
    "/preferences",
    response_model=PreferencesOut,
    dependencies=[Depends(require_sync_api_key)],
)
def read_preferences(db: Session = Depends(get_db)) -> PreferencesOut:
    return PreferencesOut(**get_preferences(db))


@app.put(
    "/preferences",
    response_model=PreferencesOut,
    dependencies=[Depends(require_sync_api_key)],
)
def put_preferences(body: PreferencesUpdate, db: Session = Depends(get_db)) -> PreferencesOut:
    try:
        return PreferencesOut(
            **update_preferences(
                db,
                calorie_target=body.calorie_target,
                mode=body.mode,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/decisions",
    response_model=DecisionRanking,
    dependencies=[Depends(require_sync_api_key)],
)
def get_decisions(db: Session = Depends(get_db)) -> DecisionRanking:
    return rank_decision_opportunities(db)


@app.get(
    "/check-ins",
    response_model=list[CheckInOut],
    dependencies=[Depends(require_sync_api_key)],
)
def get_check_ins(
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
) -> list[CheckInOut]:
    try:
        return [CheckInOut(**check_in_to_dict(r)) for r in list_check_ins(db, days=days)]
    except LookupError:
        return []


@app.post(
    "/check-ins",
    response_model=CheckInOut,
    dependencies=[Depends(require_sync_api_key)],
)
def post_check_in(body: CheckInCreate, db: Session = Depends(get_db)) -> CheckInOut:
    try:
        row = create_check_in(db, body.model_dump(exclude_none=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CheckInOut(**check_in_to_dict(row))


@app.delete(
    "/check-ins/{check_in_id}",
    dependencies=[Depends(require_sync_api_key)],
)
def remove_check_in(check_in_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        delete_check_in(db, check_in_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}


@app.get(
    "/meal-intelligence",
    response_model=MealIntelligencePack,
    dependencies=[Depends(require_sync_api_key)],
)
def get_meal_intelligence(db: Session = Depends(get_db)) -> MealIntelligencePack:
    return MealIntelligencePack(**build_bni_pack(db))


@app.get(
    "/meal-events",
    response_model=list[MealEventOut],
    dependencies=[Depends(require_sync_api_key)],
)
def get_meal_events(
    days: int = Query(default=30, ge=1, le=180),
    db: Session = Depends(get_db),
) -> list[MealEventOut]:
    try:
        return [MealEventOut(**meal_event_to_dict(e)) for e in list_meal_events(db, days=days)]
    except LookupError:
        return []


@app.post(
    "/meal-events",
    response_model=MealEventOut,
    dependencies=[Depends(require_sync_api_key)],
)
def post_meal_event(body: MealEventCreate, db: Session = Depends(get_db)) -> MealEventOut:
    try:
        row = create_meal_event(db, body.model_dump(exclude_none=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MealEventOut(**meal_event_to_dict(row))


@app.delete(
    "/meal-events/{event_id}",
    dependencies=[Depends(require_sync_api_key)],
)
def remove_meal_event(event_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        delete_meal_event(db, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}


@app.get(
    "/meal-reviews/{staple_id}",
    response_model=MealReview,
    dependencies=[Depends(require_sync_api_key)],
)
def get_meal_review(staple_id: int, db: Session = Depends(get_db)) -> MealReview:
    try:
        return MealReview(**build_meal_review(db, staple_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/food-staples",
    response_model=list[FoodStapleOut],
    dependencies=[Depends(require_sync_api_key)],
)
def get_food_staples(db: Session = Depends(get_db)) -> list[FoodStapleOut]:
    try:
        return [FoodStapleOut(**staple_to_dict(s)) for s in list_food_staples(db)]
    except LookupError:
        return []


@app.post(
    "/food-staples",
    response_model=FoodStapleOut,
    dependencies=[Depends(require_sync_api_key)],
)
def post_food_staple(body: FoodStapleCreate, db: Session = Depends(get_db)) -> FoodStapleOut:
    try:
        row = create_food_staple(db, body.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FoodStapleOut(**staple_to_dict(row))


@app.delete(
    "/food-staples/{staple_id}",
    dependencies=[Depends(require_sync_api_key)],
)
def remove_food_staple(staple_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        delete_food_staple(db, staple_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}


@app.post(
    "/chat/ask",
    response_model=ChatAskResponse,
    dependencies=[Depends(require_sync_api_key)],
)
def chat_ask(body: ChatAskRequest, db: Session = Depends(get_db)) -> ChatAskResponse:
    try:
        result = ask_health_question(db, body.message, thread_id=body.thread_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}") from exc
    return ChatAskResponse(**result)


@app.get(
    "/patterns",
    response_model=list[PhysiologyPatternOut],
    dependencies=[Depends(require_sync_api_key)],
)
def get_patterns(db: Session = Depends(get_db)) -> list[PhysiologyPatternOut]:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        return []
    return [PhysiologyPatternOut(**pattern_to_dict(p)) for p in list_patterns_for_user(db, user.id)]


@app.post(
    "/patterns/refresh",
    response_model=list[PhysiologyPatternOut],
    dependencies=[Depends(require_sync_api_key)],
)
def refresh_patterns(db: Session = Depends(get_db)) -> list[PhysiologyPatternOut]:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise HTTPException(status_code=404, detail="No users found. Import data first.")
    rows = refresh_physiology_patterns(db, user.id)
    return [PhysiologyPatternOut(**pattern_to_dict(p)) for p in rows]


@app.get(
    "/interventions",
    response_model=list[InterventionOut],
    dependencies=[Depends(require_sync_api_key)],
)
def get_interventions(db: Session = Depends(get_db)) -> list[InterventionOut]:
    try:
        return [InterventionOut(**intervention_to_dict(i)) for i in list_interventions(db)]
    except LookupError:
        return []


@app.post(
    "/interventions",
    response_model=InterventionOut,
    dependencies=[Depends(require_sync_api_key)],
)
def post_intervention(body: InterventionCreate, db: Session = Depends(get_db)) -> InterventionOut:
    try:
        row = create_intervention(
            db,
            name=body.name,
            hypothesis=body.hypothesis,
            start_date=body.start_date,
            end_date=body.end_date,
            category=body.category,
            instructions=body.instructions,
            target_metrics=body.target_metrics,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InterventionOut(**intervention_to_dict(row))


@app.post(
    "/interventions/{intervention_id}/evaluate",
    response_model=InterventionOut,
    dependencies=[Depends(require_sync_api_key)],
)
def post_evaluate_intervention(
    intervention_id: int, db: Session = Depends(get_db)
) -> InterventionOut:
    try:
        row = evaluate_intervention(db, intervention_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InterventionOut(**intervention_to_dict(row))


@app.post("/imports/synthetic-csv", response_model=ImportResult)
def import_synthetic_csv(
    path: str | None = Query(
        default=None,
        description="Optional path to CSV; defaults to data/raw/synthetic/daily_metrics.csv",
    ),
    db: Session = Depends(get_db),
) -> ImportResult:
    csv_path = Path(path) if path else ROOT_DIR / "data" / "raw" / "synthetic" / "daily_metrics.csv"
    try:
        result = import_daily_metrics_csv(
            db,
            csv_path,
            user_email=settings.default_user_email,
            user_name=settings.default_user_name,
            source="synthetic",
        )
        summaries = rebuild_daily_summaries(db, result["user_id"])
        refresh_physiology_patterns(db, result["user_id"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ImportResult(
        source=result["source"],
        filename=result["filename"],
        measurements_imported=result["measurements_imported"],
        contexts_imported=result["contexts_imported"],
        summaries_built=summaries,
        user_id=result["user_id"],
    )


@app.post(
    "/sync/health-auto-export",
    response_model=HealthAutoExportSyncResult,
    dependencies=[Depends(require_sync_api_key)],
)
@app.post(
    "/api/data",
    response_model=HealthAutoExportSyncResult,
    dependencies=[Depends(require_sync_api_key)],
    include_in_schema=False,
)
async def sync_health_auto_export(
    request: Request,
    db: Session = Depends(get_db),
) -> HealthAutoExportSyncResult:
    """Receive JSON from the Health Auto Export iOS app REST automation."""
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Body must be JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    result = ingest_health_auto_export(
        db,
        payload,
        user_email=settings.default_user_email,
        user_name=settings.default_user_name,
    )
    summaries = rebuild_daily_summaries(db, result["user_id"])
    refresh_physiology_patterns(db, result["user_id"])
    return HealthAutoExportSyncResult(
        measurements_imported=result["measurements_imported"],
        workouts_imported=result["workouts_imported"],
        contexts_imported=result["contexts_imported"],
        skipped_groups_or_rows=result["skipped_groups_or_rows"],
        summaries_built=summaries,
        user_id=result["user_id"],
        import_batch_id=result["import_batch_id"],
    )


@app.get(
    "/sync/hevy/account",
    dependencies=[Depends(require_sync_api_key)],
)
def get_hevy_account() -> dict[str, Any]:
    """Verify which Hevy account the configured API key belongs to."""
    if not settings.hevy_api_key:
        raise HTTPException(
            status_code=503,
            detail="HC_HEVY_API_KEY is not set. Create one at https://hevy.com/settings?developer (Hevy Pro).",
        )
    try:
        info = fetch_hevy_user_info(settings.hevy_api_key)
    except HevyAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"connected": True, "hevy_account": info}


@app.post(
    "/sync/hevy",
    response_model=HevySyncResult,
    dependencies=[Depends(require_sync_api_key)],
)
def sync_hevy_workouts(
    max_pages: int = Query(default=50, ge=1, le=200),
    exercise_history_limit: int = Query(default=12, ge=0, le=50),
    db: Session = Depends(get_db),
) -> HevySyncResult:
    """Pull strength workouts from the Hevy Pro API into workouts + exercise_sets."""
    if not settings.hevy_api_key:
        raise HTTPException(
            status_code=503,
            detail="HC_HEVY_API_KEY is not set. Create one at https://hevy.com/settings?developer (Hevy Pro).",
        )
    try:
        result = sync_hevy(
            db,
            api_key=settings.hevy_api_key,
            user_email=settings.default_user_email,
            user_name=settings.default_user_name,
            max_pages=max_pages,
            exercise_history_limit=exercise_history_limit,
        )
    except HevyAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Hevy sync failed: {exc}") from exc

    summaries = rebuild_daily_summaries(db, result["user_id"])
    refresh_physiology_patterns(db, result["user_id"])
    return HevySyncResult(
        hevy_username=result.get("hevy_username"),
        hevy_workout_count=result.get("hevy_workout_count"),
        workouts_imported=result["workouts_imported"],
        workouts_updated=result["workouts_updated"],
        sets_imported=result["sets_imported"],
        strength_measurements_imported=result["strength_measurements_imported"],
        body_measurements_imported=result.get("body_measurements_imported", 0),
        exercise_templates_cached=result.get("exercise_templates_cached", 0),
        exercise_history_fetched=result.get("exercise_history_fetched", 0),
        personal_records=result.get("personal_records", []),
        skipped=result["skipped"],
        summaries_built=summaries,
        user_id=result["user_id"],
        import_batch_id=result["import_batch_id"],
    )


@app.get(
    "/reasoning-trace/{target_date}",
    response_model=ReasoningTrace,
    dependencies=[Depends(require_sync_api_key)],
)
def get_reasoning_trace(target_date: date, db: Session = Depends(get_db)) -> ReasoningTrace:
    try:
        return llm_build_reasoning_trace(db, target_date)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Reasoning failed: {exc}") from exc


@app.get("/daily-summary/{target_date}", response_model=DailySummaryResponse)
def get_daily_summary(target_date: date, db: Session = Depends(get_db)) -> DailySummaryResponse:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise HTTPException(status_code=404, detail="No users found. Import data first.")
    summary = db.scalar(
        select(DailySummary).where(
            DailySummary.user_id == user.id, DailySummary.date == target_date
        )
    )
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No summary for {target_date}")
    return DailySummaryResponse(date=target_date, summary=_to_metrics(summary))


@app.get("/weight-explanation/{target_date}", response_model=WeightExplanationResponse)
def get_weight_explanation(
    target_date: date, db: Session = Depends(get_db)
) -> WeightExplanationResponse:
    try:
        return explain_weight_for_date(db, target_date)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
