"""Behavioral Nutrition Intelligence — meal timing, satiety, sequences, habits."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DailySummary, FoodStaple, MealEvent, User

MIN_SUPPORT = 3
LOOKBACK_DAYS = 90


def _primary_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise LookupError("No users found. Import data first.")
    return user


def meal_event_to_dict(row: MealEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "staple_id": row.staple_id,
        "eaten_at": row.eaten_at.isoformat() if row.eaten_at else None,
        "meal_slot": row.meal_slot,
        "name": row.name,
        "calories": row.calories,
        "protein_g": row.protein_g,
        "carbohydrate_g": row.carbohydrate_g,
        "fat_g": row.fat_g,
        "fiber_g": row.fiber_g,
        "sodium_mg": row.sodium_mg,
        "whole_food_score": row.whole_food_score,
        "processing_score": row.processing_score,
        "satiety_hours": row.satiety_hours,
        "hunger_returned_at": row.hunger_returned_at.isoformat() if row.hunger_returned_at else None,
        "energy_after": row.energy_after,
        "craving_after": row.craving_after,
        "followed_by_snack": row.followed_by_snack,
        "workout_hours_after": row.workout_hours_after,
        "enjoyment": row.enjoyment,
        "digestive_comfort": row.digestive_comfort,
        "notes": row.notes,
        "source": row.source,
    }


def list_meal_events(db: Session, *, days: int = 30, limit: int = 100) -> list[MealEvent]:
    user = _primary_user(db)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    return list(
        db.scalars(
            select(MealEvent)
            .where(MealEvent.user_id == user.id, MealEvent.eaten_at >= cutoff)
            .order_by(MealEvent.eaten_at.desc())
            .limit(limit)
        ).all()
    )


def create_meal_event(db: Session, payload: dict[str, Any]) -> MealEvent:
    user = _primary_user(db)
    eaten_at = payload.get("eaten_at")
    if isinstance(eaten_at, str):
        eaten_at = datetime.fromisoformat(eaten_at.replace("Z", "+00:00"))
    if eaten_at is None:
        eaten_at = datetime.now(UTC)
    hunger_at = payload.get("hunger_returned_at")
    if isinstance(hunger_at, str):
        hunger_at = datetime.fromisoformat(hunger_at.replace("Z", "+00:00"))

    satiety = payload.get("satiety_hours")
    if satiety is None and hunger_at is not None and eaten_at is not None:
        satiety = round((hunger_at - eaten_at).total_seconds() / 3600.0, 2)

    staple_id = payload.get("staple_id")
    name = str(payload.get("name") or "").strip()
    if staple_id and not name:
        staple = db.get(FoodStaple, staple_id)
        if staple:
            name = staple.name
            if payload.get("calories") is None:
                payload["calories"] = staple.estimated_calories
            if payload.get("protein_g") is None:
                payload["protein_g"] = staple.estimated_protein_g
            if payload.get("fiber_g") is None:
                payload["fiber_g"] = staple.estimated_fiber_g
            if staple.is_packaged:
                payload.setdefault("processing_score", 7.0)
                payload.setdefault("whole_food_score", 3.0)

    row = MealEvent(
        user_id=user.id,
        staple_id=staple_id,
        eaten_at=eaten_at,
        meal_slot=payload.get("meal_slot"),
        name=name or "Meal",
        calories=payload.get("calories"),
        protein_g=payload.get("protein_g"),
        carbohydrate_g=payload.get("carbohydrate_g"),
        fat_g=payload.get("fat_g"),
        fiber_g=payload.get("fiber_g"),
        sodium_mg=payload.get("sodium_mg"),
        whole_food_score=payload.get("whole_food_score"),
        processing_score=payload.get("processing_score"),
        satiety_hours=satiety,
        hunger_returned_at=hunger_at,
        energy_after=payload.get("energy_after"),
        craving_after=payload.get("craving_after"),
        followed_by_snack=payload.get("followed_by_snack"),
        workout_hours_after=payload.get("workout_hours_after"),
        enjoyment=payload.get("enjoyment"),
        digestive_comfort=payload.get("digestive_comfort"),
        notes=payload.get("notes"),
        source=payload.get("source") or "manual",
    )
    db.add(row)
    if staple_id:
        staple = db.get(FoodStaple, staple_id)
        if staple and staple.user_id == user.id:
            staple.times_logged = int(staple.times_logged or 0) + 1
            staple.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    refresh_staple_profiles(db)
    return row


def delete_meal_event(db: Session, event_id: int) -> None:
    user = _primary_user(db)
    row = db.scalar(
        select(MealEvent).where(MealEvent.id == event_id, MealEvent.user_id == user.id)
    )
    if row is None:
        raise LookupError(f"Meal event {event_id} not found")
    db.delete(row)
    db.commit()


def _avg(vals: list[float]) -> Optional[float]:
    return round(mean(vals), 2) if vals else None


def refresh_staple_profiles(db: Session) -> None:
    """Update learned_profile on each staple from linked meal events."""
    user = _primary_user(db)
    staples = list(
        db.scalars(select(FoodStaple).where(FoodStaple.user_id == user.id)).all()
    )
    for staple in staples:
        events = list(
            db.scalars(
                select(MealEvent)
                .where(MealEvent.user_id == user.id, MealEvent.staple_id == staple.id)
                .order_by(MealEvent.eaten_at.desc())
            ).all()
        )
        if not events:
            continue
        satiety = [e.satiety_hours for e in events if e.satiety_hours is not None]
        snacks = [
            1.0 if e.followed_by_snack else 0.0
            for e in events
            if e.followed_by_snack is not None
        ]
        cravings = [
            1.0 if e.craving_after else 0.0 for e in events if e.craving_after is not None
        ]
        energy = [float(e.energy_after) for e in events if e.energy_after is not None]
        enjoyment = [float(e.enjoyment) for e in events if e.enjoyment is not None]
        comfort = [
            float(e.digestive_comfort) for e in events if e.digestive_comfort is not None
        ]
        processing = [e.processing_score for e in events if e.processing_score is not None]
        whole = [e.whole_food_score for e in events if e.whole_food_score is not None]

        days = {e.eaten_at.date() for e in events if e.eaten_at}
        summaries = {
            r.date: r
            for r in db.scalars(
                select(DailySummary).where(
                    DailySummary.user_id == user.id,
                    DailySummary.date.in_(list(days) if days else [date.today()]),
                )
            ).all()
        }
        next_deltas: list[float] = []
        for d in days:
            nxt = summaries.get(d + timedelta(days=1))
            if nxt and nxt.weight_change_from_yesterday_kg is not None:
                next_deltas.append(float(nxt.weight_change_from_yesterday_kg))

        snack_rate = _avg(snacks)
        craving_risk = _avg(cravings)
        avg_satiety = _avg(satiety)
        satiety_score = None
        if avg_satiety is not None:
            base = min(10.0, avg_satiety * 1.4)
            if snack_rate is not None:
                base -= snack_rate * 3.0
            satiety_score = round(max(1.0, min(10.0, base)), 1)

        staple.learned_profile = {
            "times_logged": len(events),
            "avg_satiety_hours": avg_satiety,
            "personal_satiety_score": satiety_score,
            "snack_follow_rate": snack_rate,
            "craving_risk": craving_risk,
            "avg_energy_after": _avg(energy),
            "avg_enjoyment": _avg(enjoyment),
            "avg_digestive_comfort": _avg(comfort),
            "avg_processing_score": _avg(processing),
            "avg_whole_food_score": _avg(whole),
            "avg_next_morning_weight_delta_kg": _avg(next_deltas),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        staple.times_logged = len(events)
        staple.updated_at = datetime.now(UTC)
    db.commit()


def build_meal_review(db: Session, staple_id: int) -> dict[str, Any]:
    user = _primary_user(db)
    staple = db.scalar(
        select(FoodStaple).where(FoodStaple.id == staple_id, FoodStaple.user_id == user.id)
    )
    if staple is None:
        raise LookupError(f"Staple {staple_id} not found")
    refresh_staple_profiles(db)
    db.refresh(staple)
    profile = staple.learned_profile or {}
    n = int(profile.get("times_logged") or staple.times_logged or 0)
    strengths: list[str] = []
    improvements: list[str] = []

    sat = profile.get("personal_satiety_score")
    if sat is not None and sat >= 7:
        strengths.append(f"Keeps you full well (personal satiety ~{sat}/10).")
    elif sat is not None and sat < 5:
        improvements.append(
            f"Personal satiety is low (~{sat}/10) — often followed by hunger or snacking."
        )

    if staple.estimated_protein_g and staple.estimated_protein_g >= 30:
        strengths.append("Consistently helps hit protein goals.")
    elif staple.estimated_protein_g is not None and staple.estimated_protein_g < 20:
        improvements.append(
            "Protein is lower than similar meals — consider adding eggs, yogurt, or chicken."
        )

    fiber = staple.estimated_fiber_g
    if fiber is not None and fiber < 5:
        improvements.append(
            "Fiber is lower than your daily target. Adding berries and chia seeds "
            "would increase fiber with minimal calorie impact."
        )
    elif fiber is not None and fiber >= 8:
        strengths.append("Solid fiber contribution for satiety.")

    if staple.is_packaged:
        improvements.append(
            "Packaged source — swapping one day a week for a whole-food version may improve satiety."
        )
    else:
        strengths.append("Whole-food oriented.")

    snack_rate = profile.get("snack_follow_rate")
    if snack_rate is not None and snack_rate >= 0.5:
        improvements.append(
            f"Followed by a snack ~{int(snack_rate * 100)}% of the time — "
            "consider a higher-fiber or higher-protein variant."
        )
    elif snack_rate is not None and snack_rate < 0.25 and n >= MIN_SUPPORT:
        strengths.append("Rarely followed by snacking.")

    if n < MIN_SUPPORT:
        strengths.append(f"Logged {n} time(s) — keep logging outcomes to sharpen this review.")

    return {
        "staple_id": staple.id,
        "name": staple.name,
        "times_logged": n,
        "profile": profile,
        "strengths": strengths,
        "improvements": improvements,
        "summary": (
            f"{staple.name}: {n} logs. "
            + (" ".join(strengths[:2]) if strengths else "Still learning this meal.")
        ),
    }


def detect_meal_patterns(db: Session) -> list[dict[str, Any]]:
    """Discover timing, interval, habit, and circadian associations."""
    user = _primary_user(db)
    cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    events = list(
        db.scalars(
            select(MealEvent)
            .where(MealEvent.user_id == user.id, MealEvent.eaten_at >= cutoff)
            .order_by(MealEvent.eaten_at.asc())
        ).all()
    )
    patterns: list[dict[str, Any]] = []
    if len(events) < MIN_SUPPORT:
        return patterns

    by_day: dict[date, list[MealEvent]] = defaultdict(list)
    for e in events:
        by_day[e.eaten_at.date()].append(e)

    summaries = {
        r.date: r
        for r in db.scalars(
            select(DailySummary)
            .where(DailySummary.user_id == user.id)
            .order_by(DailySummary.date.desc())
            .limit(LOOKBACK_DAYS)
        ).all()
    }

    early_protein_days: list[float] = []
    low_protein_days: list[float] = []
    early_snack_rates: list[float] = []
    low_snack_rates: list[float] = []
    for _day, meals in by_day.items():
        breakfasts = [
            m
            for m in meals
            if (m.meal_slot or "").lower() == "breakfast" or m.eaten_at.hour < 10
        ]
        if not breakfasts:
            continue
        protein = sum(m.protein_g or 0 for m in breakfasts)
        snacks = [
            m
            for m in meals
            if (m.meal_slot or "").lower() == "snack"
            or (
                m.eaten_at.hour >= 16
                and (m.meal_slot or "").lower() not in ("dinner", "lunch", "breakfast")
            )
        ]
        snack_flag = (
            1.0
            if snacks
            or any(bool(m.followed_by_snack) for m in breakfasts if m.followed_by_snack is not None)
            else 0.0
        )
        evening_kcal = sum(m.calories or 0 for m in meals if m.eaten_at.hour >= 17)
        if protein >= 35 and any(m.eaten_at.hour < 9 for m in breakfasts):
            early_protein_days.append(evening_kcal)
            early_snack_rates.append(snack_flag)
        elif protein < 25:
            low_protein_days.append(evening_kcal)
            low_snack_rates.append(snack_flag)

    if len(early_protein_days) >= MIN_SUPPORT and len(low_protein_days) >= MIN_SUPPORT:
        early_snack = mean(early_snack_rates)
        low_snack = mean(low_snack_rates)
        if low_snack > 0 and early_snack < low_snack:
            reduction = round((1 - early_snack / low_snack) * 100)
            patterns.append(
                {
                    "key": "early_protein_less_snacking",
                    "category": "meal_timing",
                    "title": "Early protein linked to less evening snacking",
                    "insight": (
                        f"When you eat at least 35g protein before 9 AM, evening snack days drop "
                        f"~{reduction}% vs lower-protein mornings "
                        f"(n={len(early_protein_days)} vs {len(low_protein_days)})."
                    ),
                    "confidence": min(0.75, 0.4 + 0.05 * min(len(early_protein_days), 8)),
                    "support": len(early_protein_days) + len(low_protein_days),
                }
            )

    late_lunch_eve: list[float] = []
    early_lunch_eve: list[float] = []
    for _day, meals in by_day.items():
        lunches = [
            m
            for m in meals
            if (m.meal_slot or "").lower() == "lunch" or 11 <= m.eaten_at.hour <= 15
        ]
        if not lunches:
            continue
        lunch_hour = min(m.eaten_at.hour + m.eaten_at.minute / 60 for m in lunches)
        evening = sum(m.calories or 0 for m in meals if m.eaten_at.hour >= 17)
        if lunch_hour >= 14:
            late_lunch_eve.append(evening)
        elif lunch_hour <= 13:
            early_lunch_eve.append(evening)
    if len(late_lunch_eve) >= MIN_SUPPORT and len(early_lunch_eve) >= MIN_SUPPORT:
        delta = mean(late_lunch_eve) - mean(early_lunch_eve)
        if delta >= 150:
            patterns.append(
                {
                    "key": "late_lunch_evening_calories",
                    "category": "meal_interval",
                    "title": "Late lunch associated with higher evening calories",
                    "insight": (
                        f"When lunch is delayed past 2 PM, evening calories average "
                        f"+{int(delta)} kcal vs earlier lunches."
                    ),
                    "confidence": min(0.7, 0.4 + 0.04 * len(late_lunch_eve)),
                    "support": len(late_lunch_eve) + len(early_lunch_eve),
                }
            )

    long_gaps: list[float] = []
    for day, meals in by_day.items():
        ordered = sorted(meals, key=lambda m: m.eaten_at)
        for a, b in zip(ordered, ordered[1:]):
            gap_h = (b.eaten_at - a.eaten_at).total_seconds() / 3600.0
            if gap_h >= 6:
                long_gaps.append(gap_h)
                if b.craving_after or b.followed_by_snack or (b.calories or 0) > 800:
                    patterns.append(
                        {
                            "key": f"long_gap_{day.isoformat()}",
                            "category": "meal_interval",
                            "title": "Long meal gap before a large/hungry meal",
                            "insight": (
                                f"On {day.isoformat()}, {gap_h:.1f}h between "
                                f"{a.name} and {b.name} — watch for rebound hunger."
                            ),
                            "confidence": 0.45,
                            "support": 1,
                        }
                    )
                    break
    gap_patterns = [p for p in patterns if p["key"].startswith("long_gap_")]
    if len(gap_patterns) > 2:
        for p in gap_patterns[2:]:
            patterns.remove(p)
    if len(long_gaps) >= MIN_SUPPORT:
        patterns.append(
            {
                "key": "frequent_long_gaps",
                "category": "meal_interval",
                "title": "Frequent long gaps between meals",
                "insight": (
                    f"You have {len(long_gaps)} meal gaps ≥6h in the lookback. "
                    "Long waits often drive evening overeating more than the calorie target itself."
                ),
                "confidence": 0.55,
                "support": len(long_gaps),
            }
        )

    late_calorie_sleep: list[float] = []
    early_calorie_sleep: list[float] = []
    for day, meals in by_day.items():
        total = sum(m.calories or 0 for m in meals) or 0
        if total <= 0:
            continue
        after_8 = sum(m.calories or 0 for m in meals if m.eaten_at.hour >= 20)
        share = after_8 / total
        s = summaries.get(day)
        if s is None or s.sleep_hours is None:
            continue
        if share >= 0.35:
            late_calorie_sleep.append(float(s.sleep_hours))
        elif share < 0.15:
            early_calorie_sleep.append(float(s.sleep_hours))
    if len(late_calorie_sleep) >= MIN_SUPPORT and len(early_calorie_sleep) >= MIN_SUPPORT:
        delta_sleep = mean(early_calorie_sleep) - mean(late_calorie_sleep)
        if delta_sleep >= 0.3:
            patterns.append(
                {
                    "key": "late_calories_sleep",
                    "category": "circadian",
                    "title": "Late calorie load associated with shorter sleep",
                    "insight": (
                        f"On days with ≥35% of calories after 8 PM, sleep averages "
                        f"{delta_sleep:.1f}h less than earlier-eating days."
                    ),
                    "confidence": min(0.7, 0.4 + 0.04 * len(late_calorie_sleep)),
                    "support": len(late_calorie_sleep) + len(early_calorie_sleep),
                }
            )

    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for wd in range(7):
        days_wd = [d for d in by_day if d.weekday() == wd]
        if len(days_wd) < MIN_SUPPORT:
            continue
        deltas = []
        for d in days_wd:
            s = summaries.get(d + timedelta(days=1))
            if s and s.weight_change_from_yesterday_kg is not None:
                deltas.append(float(s.weight_change_from_yesterday_kg))
        if len(deltas) < MIN_SUPPORT:
            continue
        avg_d = mean(deltas)
        if abs(avg_d) >= 0.2:
            direction = "up" if avg_d > 0 else "down"
            patterns.append(
                {
                    "key": f"weekday_habit_{wd}",
                    "category": "habit",
                    "title": f"{weekday_names[wd]} pattern → next-morning weight {direction}",
                    "insight": (
                        f"After {weekday_names[wd]} meals, next-morning weight change averages "
                        f"{avg_d:+.2f} kg (n={len(deltas)}). Not judgment — a learnable loop."
                    ),
                    "confidence": min(0.7, 0.35 + 0.05 * len(deltas)),
                    "support": len(deltas),
                }
            )

    staples = list(
        db.scalars(select(FoodStaple).where(FoodStaple.user_id == user.id)).all()
    )
    scored = [
        (s, (s.learned_profile or {}).get("personal_satiety_score"))
        for s in staples
        if (s.learned_profile or {}).get("personal_satiety_score") is not None
        and (s.learned_profile or {}).get("times_logged", 0) >= MIN_SUPPORT
    ]
    scored.sort(key=lambda x: x[1] or 0, reverse=True)
    if scored:
        best = scored[0][0]
        bp = best.learned_profile or {}
        patterns.append(
            {
                "key": "best_satiety_meal",
                "category": "satiety",
                "title": f"Highest personal satiety: {best.name}",
                "insight": (
                    f"{best.name} averages {bp.get('avg_satiety_hours')}h fullness "
                    f"(score {bp.get('personal_satiety_score')}/10 across {bp.get('times_logged')} logs)."
                ),
                "confidence": 0.6,
                "support": int(bp.get("times_logged") or 0),
            }
        )
        if len(scored) >= 2 and (scored[-1][1] or 0) < 5:
            worst = scored[-1][0]
            wp = worst.learned_profile or {}
            patterns.append(
                {
                    "key": "low_satiety_meal",
                    "category": "satiety",
                    "title": f"Low satiety meal: {worst.name}",
                    "insight": (
                        f"{worst.name} scores {wp.get('personal_satiety_score')}/10 satiety "
                        f"and is often followed by snacking — a high-ROI swap candidate."
                    ),
                    "confidence": 0.55,
                    "support": int(wp.get("times_logged") or 0),
                }
            )

    patterns.sort(key=lambda p: (-(p.get("confidence") or 0), -(p.get("support") or 0)))
    return patterns[:12]


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def predict_hunger(db: Session) -> Optional[dict[str, Any]]:
    """Heuristic hunger prediction from today's meals so far."""
    user = _primary_user(db)
    now = datetime.now(UTC)
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    today_meals = list(
        db.scalars(
            select(MealEvent)
            .where(MealEvent.user_id == user.id, MealEvent.eaten_at >= today_start.replace(tzinfo=None))
            .order_by(MealEvent.eaten_at.asc())
        ).all()
    )
    # Also include aware timestamps stored with tz
    if not today_meals:
        today_meals = list(
            db.scalars(
                select(MealEvent)
                .where(MealEvent.user_id == user.id, MealEvent.eaten_at >= today_start)
                .order_by(MealEvent.eaten_at.asc())
            ).all()
        )
    # Fallback: filter in Python for mixed tz storage
    if not today_meals:
        all_recent = list(
            db.scalars(
                select(MealEvent)
                .where(MealEvent.user_id == user.id)
                .order_by(MealEvent.eaten_at.desc())
                .limit(20)
            ).all()
        )
        today_meals = [
            m
            for m in reversed(all_recent)
            if _as_aware(m.eaten_at).date() == now.date()
        ]

    if not today_meals:
        return {
            "risk": "unknown",
            "message": (
                "No meals logged today yet. Log breakfast with protein and timing "
                "so Momentum can predict evening hunger."
            ),
            "suggested_action": "Log your next meal with time and satiety outcome.",
            "reasons": [],
        }

    last = today_meals[-1]
    hours_since = (now - _as_aware(last.eaten_at)).total_seconds() / 3600.0
    breakfast_protein = sum(
        m.protein_g or 0
        for m in today_meals
        if (m.meal_slot or "").lower() == "breakfast" or _as_aware(m.eaten_at).hour < 10
    )
    lunch_late = any(
        ((m.meal_slot or "").lower() == "lunch" or 11 <= _as_aware(m.eaten_at).hour <= 15)
        and _as_aware(m.eaten_at).hour >= 14
        for m in today_meals
    )
    avg_satiety = [m.satiety_hours for m in today_meals if m.satiety_hours is not None]
    expected_satiety = mean(avg_satiety) if avg_satiety else 4.0

    risk = "low"
    reasons: list[str] = []
    if hours_since >= expected_satiety * 0.85:
        risk = "high"
        reasons.append(
            f"{hours_since:.1f}h since {last.name} (typical satiety ~{expected_satiety:.1f}h)"
        )
    if breakfast_protein < 25 and now.hour >= 15:
        risk = "high" if risk != "low" else "medium"
        reasons.append(f"Morning protein only ~{int(breakfast_protein)}g")
    if lunch_late:
        risk = "high"
        reasons.append("Lunch was delayed past 2 PM — evenings often run hungry")

    if risk == "low" and now.hour < 16:
        return {
            "risk": "low",
            "message": "Based on today's meals so far, evening hunger risk looks manageable.",
            "suggested_action": None,
            "reasons": reasons,
        }

    action = (
        "Have Greek yogurt, fruit, or a high-protein snack before leaving work "
        "to reduce evening overeating risk."
    )
    return {
        "risk": risk,
        "message": (
            "Based on lunch timing, breakfast composition, and hours since your last meal, "
            "you're likely to be very hungry around 6 PM."
            if risk == "high"
            else "Moderate evening hunger risk based on today's meal pattern."
        ),
        "suggested_action": action if risk in ("high", "medium") else None,
        "reasons": reasons,
    }


def build_bni_pack(db: Session) -> dict[str, Any]:
    """Full Behavioral Nutrition Intelligence pack for coaching / UI."""
    try:
        user = _primary_user(db)
    except LookupError:
        return {
            "patterns": [],
            "hunger_prediction": None,
            "meal_reviews": [],
            "recent_events": [],
            "event_count": 0,
        }

    refresh_staple_profiles(db)
    patterns = detect_meal_patterns(db)
    hunger = predict_hunger(db)
    events = list_meal_events(db, days=14, limit=40)
    staples = list(
        db.scalars(
            select(FoodStaple)
            .where(FoodStaple.user_id == user.id)
            .order_by(FoodStaple.times_logged.desc())
        ).all()
    )
    reviews = []
    for s in staples[:5]:
        if (s.times_logged or 0) >= 1:
            try:
                reviews.append(build_meal_review(db, s.id))
            except LookupError:
                pass

    return {
        "patterns": patterns,
        "hunger_prediction": hunger,
        "meal_reviews": reviews,
        "recent_events": [meal_event_to_dict(e) for e in events],
        "event_count": len(events),
    }
