"""Strength training — equipment, exercise catalog, workouts, sets.

This module is the data layer (Phase 1). Workout generation, recovery
integration, and the /workout/strength/today endpoint live in
analytics/strength.py + Phase 3 of the rollout.

The exercise catalog is a static JSON asset shipped with the backend
(data/exercises.json, derived from yuhonas/free-exercise-db, public
domain). It's loaded into memory at module import — single-process
backend, ~200 entries, no need to involve the DB.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, and_, delete, func, select
from sqlalchemy import column as sa_column
from sqlalchemy import update as sa_update
from sqlalchemy import values as sa_values
from sqlalchemy.ext.asyncio import AsyncSession

from ...analytics import consistency, energy
from ...analytics import strength as strength_algo
from ...auth import require_any
from ...config import settings
from ...db import models
from ...db.session import get_session


def _local_today() -> date:
    """Today's date in the user's configured timezone — not UTC. The
    server runs in UTC; using utcnow().date() flips the day at 7 PM
    local in CDT and would hide a planned/completed workout for hours."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()

# Both phone and dashboard hit /workout/strength/* — phone for logging sets,
# dashboard for plan management and history.
router = APIRouter(prefix="/workout/strength", dependencies=[Depends(require_any)])


# ------------------------------------------------------------------
# Catalog (in-memory, loaded once at import)
# ------------------------------------------------------------------

_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "exercises.json"
)
_CATALOG_SUPPLEMENT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "exercises_supplement.json"
)
with open(_CATALOG_PATH, encoding="utf-8") as _f:
    _CATALOG: list[dict[str, Any]] = json.load(_f)
# Supplement file fills gaps in yuhonas/free-exercise-db (e.g. dumbbell-only
# home-gym exercises Fitbod uses but the source dataset is missing).
if _CATALOG_SUPPLEMENT_PATH.exists():
    with open(_CATALOG_SUPPLEMENT_PATH, encoding="utf-8") as _f:
        _CATALOG.extend(json.load(_f))
_CATALOG_BY_ID: dict[str, dict[str, Any]] = {e["id"]: e for e in _CATALOG}


# ------------------------------------------------------------------
# Equipment
# ------------------------------------------------------------------

class DumbbellSpec(BaseModel):
    """Either a list of fixed pairs (most home setups) or an adjustable
    range (PowerBlocks etc). Set type='none' if no dumbbells."""
    type: Literal["fixed_pairs", "adjustable", "none"] = "none"
    pairs_lb: list[float] = []
    min_lb: float | None = None
    max_lb: float | None = None
    increment_lb: float | None = None


class BenchSpec(BaseModel):
    flat: bool = False
    incline: bool = False
    decline: bool = False


class ProgramLiftState(BaseModel):
    """One lift under PROG-1 program mode. Stores the live progression
    state (current working weight + fail streak) so each session
    advances deterministically. Pure JSON in user_equipment.payload —
    no migration."""

    exercise_id: str
    scheme: Literal["greyskull", "linear", "double"] = "linear"
    # Live working weight in lb (None = bodyweight lift; progresses by
    # reps only, no weight jumps). round_weight snaps it to a loadable
    # combo at prescribe time.
    current_weight_lb: float | None = None
    # Weight added on a successful session. Greyskull doubles it when
    # the AMRAP set clears 2× the rep floor.
    increment_lb: float = 5.0
    sets: int = 3
    reps_low: int = 5
    reps_high: int = 5
    # Greyskull: last set is AMRAP (as-many-reps-as-possible ≥ reps_low).
    amrap_last_set: bool = False
    rest_s: int = 180
    # Progression bookkeeping — mutated by advance_program_lift on
    # workout completion.
    consecutive_fails: int = 0
    fails_before_deload: int = 3
    deload_pct: float = 0.10
    # ISO date (YYYY-MM-DD) of the last completion that advanced this
    # lift — guards double-advance on offline replay / re-PATCH.
    last_advanced_on: str | None = None


class ProgramConfig(BaseModel):
    """Program-mode container hung off TrainingPreferences. Default
    disabled with no lifts → generate_plan sees an empty program and
    the default generator runs unchanged."""

    enabled: bool = False
    lifts: list[ProgramLiftState] = Field(default_factory=list)


class TrainingPreferences(BaseModel):
    """Settings the workout generator reads when picking today's plan.

    Stored as a sub-object inside user_equipment.payload to keep all
    strength configuration in one place. Pure JSON, no migration when
    adding fields here."""
    level: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    # 2-6 sessions per week — drives "auto" split selection
    days_per_week: int = 3
    split_preference: Literal["auto", "adaptive", "full_body", "upper_lower", "ppl"] = "auto"
    # Deprecated (WP-17): the minutes knob was never wired into daily
    # generation. Kept so old stored payloads still validate; ignored.
    workout_minutes: int = 50
    # WP-17 — target number of working exercises per strength workout.
    # None = auto (the split template's natural size + adaptive finishers).
    # When set, generate_plan trims to it, or appends accessory slots for
    # under-MEV muscles (core favored) to reach it. Clamped 3-9.
    exercises_per_workout: int | None = None
    # Append a 2-pose mobility cool-down at the end of each strength
    # workout. Defaults on — the post-exercise window is when stretching
    # yields the most flexibility benefit (Behm 2011 SR), and 2 poses
    # at the end of an existing session is a no-friction add.
    include_mobility: bool = True
    # On recommended-rest days, generate a 5-pose yoga flow with longer
    # 45 s holds instead of leaving the day empty. This is the actual
    # flexibility-development engine (Cramer 2013 SR shows 1-2x/week of
    # yoga measurably improves passive ROM); the cool-down above is the
    # consistency floor. Defaults on to make active recovery the default.
    yoga_on_rest_days: bool = True
    # 0-3 dedicated Z2 cardio days per week — auto-allocated to the
    # gaps between strength days. With strength=3 + cardio=2, you get
    # M/W/F strength, T/Th cardio, Sat yoga, Sun rest. Set to 0 to
    # keep cardio purely manual via the swap-day menu.
    cardio_days_per_week: int = 2
    # Training goal — drives rep ranges + rest periods + progression
    # behavior. Defaults to hypertrophy (research consensus for
    # dumbbell-only home gyms hitting general population goals).
    #   strength      — 3-6 reps,  3-5 min rest, bigger weight jumps
    #   hypertrophy   — 6-12 reps, 60-90 s rest, balanced jumps
    #   general       — 8-15 reps, 30-60 s rest, smaller jumps
    goal: Literal["strength", "hypertrophy", "general"] = "hypertrophy"
    # PROG-1 — opt-in linear-progression "program mode". When enabled,
    # the chosen core lifts bypass the Fitbod-style recovery/rating
    # generator and follow a fixed session-to-session scheme instead.
    # Default off → the existing generator is byte-for-byte untouched.
    program: ProgramConfig = Field(default_factory=lambda: ProgramConfig())


class EquipmentPayload(BaseModel):
    """The shape of user_equipment.payload. Adding new fields here
    is enough — no migration required (column is JSON)."""
    dumbbells: DumbbellSpec = Field(default_factory=DumbbellSpec)
    wrist_weights_lb: list[float] = []
    bench: BenchSpec = Field(default_factory=BenchSpec)
    barbell: bool = False
    barbell_plates_lb: list[float] = []
    squat_rack: bool = False
    pull_up_bar: bool = False
    cable_stack: bool = False
    cable_increment_lb: float | None = None
    kettlebells_lb: list[float] = []
    resistance_bands: bool = False
    bodyweight: bool = True
    # Whether a training partner / spotter is available. Default false —
    # a solo home-gym user can't do partner-resistance moves (e.g. towel
    # triceps extension, manual hamstring), so those are filtered out of
    # generated plans unless this is on. See _PARTNER_REQUIRED_EXERCISES.
    training_partner: bool = False
    # Cardio equipment hints. Used by build_cardio_plan() to suggest a
    # specific modality on cardio days (rower indoors, MTB outdoors).
    # The actual data syncs separately — Concept2 ERG → /activities for
    # rowing, Strava → /activities for biking — so these are just
    # *suggestions*, not session-logging hooks.
    cardio_rower: bool = False        # Concept2 / similar erg
    cardio_bike_indoor: bool = False  # spin / Peloton / Zwift
    cardio_mtb_outdoor: bool = False  # mountain bike (Strava)
    cardio_road_bike: bool = False
    cardio_treadmill: bool = False
    # Per-exercise overrides — exercise_id → one of:
    #   "disabled"  — never include in generated plans
    #   "favorite"  — prefer when filling a slot the exercise can fill
    #   "avoid"     — picked only when no other option exists
    # Absence from the dict = neutral (default behaviour).
    exercise_prefs: dict[str, str] = Field(default_factory=dict)
    # Read by analytics.strength.generate_plan to pick split / starting
    # weights / pacing. Defaults to the same constants the algorithm
    # used to hard-code.
    training: TrainingPreferences = Field(default_factory=TrainingPreferences)


class EquipmentIn(BaseModel):
    payload: EquipmentPayload
    unit: Literal["lb", "kg"] = "lb"


class EquipmentOut(BaseModel):
    id: int
    payload: EquipmentPayload
    unit: str
    updated_at: datetime | None


# Default equipment used the first time the user hits GET /workout/strength/equipment
# without a row in the table — bodyweight only, prompts them to fill it in.
_DEFAULT_EQUIPMENT = EquipmentPayload(bodyweight=True)


@router.get("/equipment", response_model=EquipmentOut)
async def get_equipment(db: AsyncSession = Depends(get_session)) -> EquipmentOut:
    row = await db.get(models.UserEquipment, 1)
    if row is None:
        return EquipmentOut(
            id=1,
            payload=_DEFAULT_EQUIPMENT,
            unit="lb",
            updated_at=None,
        )
    return EquipmentOut(
        id=row.id,
        payload=EquipmentPayload(**row.payload),
        unit=row.unit,
        updated_at=row.updated_at,
    )


@router.put("/equipment", response_model=EquipmentOut)
async def put_equipment(
    body: EquipmentIn,
    db: AsyncSession = Depends(get_session),
) -> EquipmentOut:
    now = datetime.now(timezone.utc)
    row = await db.get(models.UserEquipment, 1)
    # Capture the prior training prefs so we can detect a meaningful
    # change after the write and auto-regenerate today's plan. Only
    # fields that actually change the workout shape trigger this:
    # level, days_per_week, split_preference, workout_minutes,
    # cardio_days_per_week, include_mobility, yoga_on_rest_days.
    # Equipment-only changes (e.g. flipping a cardio_rower flag) do
    # NOT trigger a strength regen since the strength plan is
    # unaffected.
    prior_training: dict[str, Any] = {}
    if row is not None:
        prior_training = (row.payload or {}).get("training") or {}

    if row is None:
        row = models.UserEquipment(
            id=1,
            payload=body.payload.model_dump(),
            unit=body.unit,
            updated_at=now,
        )
        db.add(row)
    else:
        row.payload = body.payload.model_dump()
        row.unit = body.unit
        row.updated_at = now
    await db.commit()
    await db.refresh(row)

    # Detect a real training-prefs change and auto-regenerate today
    # IF today's plan exists, is still planned, and has no logged sets
    # (don't clobber in-progress work).
    new_training = (row.payload or {}).get("training") or {}
    watched_fields = (
        "level", "days_per_week", "split_preference", "workout_minutes",
        "cardio_days_per_week", "include_mobility", "yoga_on_rest_days",
        "goal", "exercises_per_workout", "program",
    )
    training_changed = any(
        prior_training.get(f) != new_training.get(f) for f in watched_fields
    )
    if training_changed:
        today_d = _local_today()
        existing = await _existing_workout_for(db, today_d)
        if existing is not None and existing.status == "planned":
            # Has any set been logged on today's workout yet?
            logged_q = await db.execute(
                select(func.count(models.StrengthSet.id))
                .join(
                    models.StrengthWorkoutExercise,
                    models.StrengthSet.workout_exercise_id
                    == models.StrengthWorkoutExercise.id,
                )
                .where(models.StrengthWorkoutExercise.workout_id == existing.id)
                .where(models.StrengthSet.actual_reps.is_not(None))
            )
            logged_count = logged_q.scalar() or 0
            if logged_count == 0:
                # Safe to regenerate. Mark the prior plan as
                # regenerated (history-preserving) and persist a fresh
                # one with the new prefs.
                regen = (await db.execute(
                    select(models.StrengthWorkout)
                    .where(models.StrengthWorkout.date == today_d)
                )).scalars().all()
                regen_count = len(regen)
                profile = await db.get(models.UserProfile, 1)
                equipment_payload = await _equipment_payload(db)
                plan = await strength_algo.generate_plan(
                    db, today_d, equipment_payload, profile,
                    regen_count=regen_count, force_no_rest=True,
                )
                await strength_algo.persist_plan(db, plan, today_d)

    return EquipmentOut(
        id=row.id,
        payload=EquipmentPayload(**row.payload),
        unit=row.unit,
        updated_at=row.updated_at,
    )


# ------------------------------------------------------------------
# Catalog
# ------------------------------------------------------------------

@router.get("/exercises")
async def list_exercises(
    muscle: str | None = None,
    movement: str | None = None,
    equipment: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    """Full catalog (filtered to the user's available equipment is the
    job of the workout generator, not this endpoint — this is the raw
    list, ~200 entries, ~250 KB)."""
    rows = _CATALOG
    if muscle:
        rows = [
            e for e in rows
            if e["primary_muscle"] == muscle or muscle in e["secondary_muscles"]
        ]
    if movement:
        rows = [e for e in rows if e["movement_pattern"] == movement]
    if equipment:
        rows = [e for e in rows if equipment in e["equipment"]]
    if level:
        rows = [e for e in rows if e["level"] == level]
    return {"count": len(rows), "exercises": rows}


@router.get("/exercises/{exercise_id}")
async def get_exercise(exercise_id: str) -> dict[str, Any]:
    row = _CATALOG_BY_ID.get(exercise_id)
    if row is None:
        raise HTTPException(status_code=404, detail="exercise not found")
    return row


@router.get("/exercises-stats-summary")
async def exercises_stats_summary(
    db: AsyncSession = Depends(get_session),
) -> dict[str, dict[str, Any]]:
    """Bulk version of /exercises/{id}/stats — one SQL query, returns
    a dict keyed by exercise_id. Used by the catalog page to enable
    sort-by-stats without N round-trips.
    Exercises the user has never performed are simply absent."""
    rows = (await db.execute(
        select(
            models.StrengthWorkoutExercise.exercise_id.label("ex"),
            func.count(func.distinct(models.StrengthWorkout.id)).label("sessions"),
            func.count(models.StrengthSet.id).label("sets"),
            func.coalesce(func.sum(models.StrengthSet.actual_reps), 0).label("reps"),
            func.coalesce(
                func.sum(
                    models.StrengthSet.actual_weight_lb *
                    models.StrengthSet.actual_reps,
                ), 0,
            ).label("volume"),
            func.max(models.StrengthSet.actual_weight_lb).label("max_w"),
            func.max(models.StrengthWorkout.date).label("last_d"),
        )
        .join(
            models.StrengthSet,
            models.StrengthSet.workout_exercise_id ==
            models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkout.id ==
            models.StrengthWorkoutExercise.workout_id,
        )
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .group_by(models.StrengthWorkoutExercise.exercise_id)
    )).all()

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r.ex] = {
            "times_performed": int(r.sessions or 0),
            "total_sets": int(r.sets or 0),
            "total_reps": int(r.reps or 0),
            "total_volume_lb": round(float(r.volume or 0), 1),
            "max_weight_lb": float(r.max_w) if r.max_w is not None else None,
            "last_performed_date": r.last_d.isoformat() if r.last_d else None,
        }
    return out


@router.get("/exercises/{exercise_id}/stats")
async def get_exercise_stats(
    exercise_id: str, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Aggregate the user's history for one exercise — times performed,
    total volume, max + last weight, avg RPE. Used by the catalog detail
    panel so the user sees their own progression on each entry."""
    if exercise_id not in _CATALOG_BY_ID:
        raise HTTPException(status_code=404, detail="exercise not found")

    sets_q = await db.execute(
        select(
            models.StrengthWorkout.id,
            models.StrengthWorkout.date,
            models.StrengthSet.actual_weight_lb,
            models.StrengthSet.actual_reps,
            models.StrengthSet.rating,
            models.StrengthSet.skipped,
        )
        .join(
            models.StrengthWorkoutExercise,
            models.StrengthSet.workout_exercise_id ==
            models.StrengthWorkoutExercise.id,
        )
        .join(
            models.StrengthWorkout,
            models.StrengthWorkout.id ==
            models.StrengthWorkoutExercise.workout_id,
        )
        .where(models.StrengthWorkoutExercise.exercise_id == exercise_id)
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .where(models.StrengthSet.set_type != "warmup")  # SETTYPE-1
    )
    rows = sets_q.all()
    if not rows:
        return {
            "exercise_id": exercise_id,
            "times_performed": 0,
            "total_sets": 0, "total_reps": 0, "total_volume_lb": 0.0,
            "last_weight_lb": None, "max_weight_lb": None,
            "best_e1rm": None, "last_e1rm": None,
            "last_performed_date": None,
            "avg_rating": None,
        }

    workout_ids = {r.id for r in rows}
    last_date = max(r.date for r in rows)
    last_workout_id = next(
        (r.id for r in rows if r.date == last_date), None,
    )
    last_weight = max(
        (r.actual_weight_lb for r in rows
         if r.id == last_workout_id and r.actual_weight_lb is not None),
        default=None,
    )
    max_weight = max(
        (r.actual_weight_lb for r in rows if r.actual_weight_lb is not None),
        default=None,
    )
    total_reps = sum(r.actual_reps or 0 for r in rows)
    total_volume = sum(
        (r.actual_weight_lb or 0) * (r.actual_reps or 0) for r in rows
    )
    ratings = [r.rating for r in rows if r.rating is not None]
    avg_rating = (sum(ratings) / len(ratings)) if ratings else None

    # e1RM-1: best + most-recent estimated 1-rep-max (warmups already excluded).
    all_e1 = [e for e in (strength_algo.estimate_1rm(r.actual_weight_lb, r.actual_reps)
                          for r in rows) if e is not None]
    best_e1rm = max(all_e1) if all_e1 else None
    last_e1 = [e for e in (strength_algo.estimate_1rm(r.actual_weight_lb, r.actual_reps)
                           for r in rows if r.id == last_workout_id) if e is not None]
    last_e1rm = max(last_e1) if last_e1 else None

    return {
        "exercise_id": exercise_id,
        "times_performed": len(workout_ids),
        "total_sets": len(rows),
        "total_reps": total_reps,
        "total_volume_lb": round(total_volume, 1),
        "last_weight_lb": last_weight,
        "max_weight_lb": max_weight,
        "best_e1rm": best_e1rm,
        "last_e1rm": last_e1rm,
        "last_performed_date": last_date.isoformat() if last_date else None,
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
    }


class ExercisePrefBody(BaseModel):
    pref: Literal["neutral", "disabled", "favorite", "avoid"]


@router.put("/exercises/{exercise_id}/pref")
async def put_exercise_pref(
    exercise_id: str, body: ExercisePrefBody,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Set a per-exercise preference. 'neutral' clears any existing pref."""
    if exercise_id not in _CATALOG_BY_ID:
        raise HTTPException(status_code=404, detail="exercise not found")
    now = datetime.now(timezone.utc)
    row = await db.get(models.UserEquipment, 1)
    if row is None:
        row = models.UserEquipment(
            id=1,
            payload=EquipmentPayload().model_dump(),
            unit="lb",
            updated_at=now,
        )
        db.add(row)
        await db.flush()
    payload = dict(row.payload or {})
    prefs = dict(payload.get("exercise_prefs") or {})
    if body.pref == "neutral":
        prefs.pop(exercise_id, None)
    else:
        prefs[exercise_id] = body.pref
    payload["exercise_prefs"] = prefs
    row.payload = payload
    row.updated_at = now
    await db.commit()
    return {"exercise_id": exercise_id, "pref": body.pref}


# ------------------------------------------------------------------
# Workouts (history + manual creation; generation is Phase 3)
# ------------------------------------------------------------------

class SetIn(BaseModel):
    """When the phone POSTs a logged set."""
    workout_exercise_id: int
    set_number: int
    target_weight_lb: float | None = None
    target_reps: int
    actual_weight_lb: float | None = None
    actual_reps: int | None = None
    rating: int | None = None  # 1..5
    rest_seconds_taken: int | None = None
    skipped: bool = False
    logged_at: datetime | None = None
    set_type: str = "working"  # working | warmup | drop | failure (SETTYPE-1)


class SetOut(BaseModel):
    id: int
    workout_exercise_id: int
    set_number: int
    target_weight_lb: float | None
    target_reps: int
    actual_weight_lb: float | None
    actual_reps: int | None
    rating: int | None
    rest_seconds_taken: int | None
    logged_at: datetime | None
    skipped: bool
    set_type: str = "working"
    # PR-1: set on the log_set response when this set just beat the
    # exercise's prior best. Drives the transient "PR" badge on the client.
    is_weight_pr: bool = False
    is_e1rm_pr: bool = False


class WorkoutExerciseIn(BaseModel):
    exercise_id: str
    order_index: int
    superset_id: str | None = None
    target_sets: int
    target_reps_low: int
    target_reps_high: int
    target_weight_lb: float | None = None
    target_rest_s: int = 90
    notes: str | None = None


class LastSetOut(BaseModel):
    """LOG-1: one working set from the last time this exercise was done."""
    set_number: int
    weight_lb: float | None = None  # None for bodyweight lifts
    reps: int | None = None


class PlannedSetOut(BaseModel):
    """One prescribed set, with the prefill the clients should use.

    Before TD-6 the prescription was a single flat target on the slot, and
    each client turned it into per-set input values with its own rule.
    They disagreed. `StrengthToday.vue` seeded every set from the slot target
    with no rating; `StrengthTodayScreen.kt` inherited weight and reps from
    the most recently logged set of the same exercise and pre-selected a
    rating of 4. Same workout, same screen, two different starting values --
    the exact class of divergence the architecture rule exists to prevent,
    and invisible to `scripts/parity_check.py` because both files exist and
    both keep changing.

    The prefill is resolved here, through a three-tier cascade borrowed from
    SparkyFitness's `resolveAssumedSetValues` (the single most transferable
    idea in that codebase):

    1. The most recently logged set of this exercise **in this session**, so
       correcting the weight on set 1 carries forward to sets 2..N.
    2. The same-index set from the previous session, which is what
       `last_sets` already carries.
    3. The slot prescription.

    Warm-up and working sets are tiered separately, so a light warm-up can
    never seed a working target.

    `prefill_rating` is deliberately null. The rating is the input to next
    session's weight selection, so defaulting it means a user who taps
    through without thinking records an assessment they never made. The
    phone used to pre-select "Good" to save a tap; that convenience was
    quietly manufacturing progression data.
    """
    set_number: int
    set_type: Literal["warmup", "working"] = "working"
    target_weight_lb: float | None = None
    target_reps: int
    rest_s: int
    # PROG-1 Greyskull: the last set is "as many reps as possible". Carried
    # as a flag on the row rather than only inside the program badge string,
    # so the client can label the input instead of the user having to read
    # a badge and remember which set it referred to.
    is_amrap: bool = False
    prefill_weight_lb: float | None = None
    prefill_reps: int
    prefill_rating: int | None = None


class WorkoutExerciseOut(BaseModel):
    id: int
    workout_id: int
    exercise_id: str
    order_index: int
    superset_id: str | None
    target_sets: int
    target_reps_low: int
    target_reps_high: int
    target_weight_lb: float | None
    target_rest_s: int
    # When True, target_reps_low/high carry HOLD SECONDS and the
    # `actual_reps` field on each set should be interpreted as seconds.
    # Sourced from the catalog at serialization time so we don't need a
    # DB column or migration. Lets clients show "30-60s" instead of
    # "30-60 reps" for planks / isometric holds.
    is_timed: bool = False
    notes: str | None
    # LOAD-1: one-line "how to load it" hint when the prescribed weight needs
    # micro-loaders on top of a dumbbell (e.g. "30 lb DB + 2.5 lb wrist").
    # Null for bodyweight lifts and for plain-dumbbell weights (the number
    # already says it). Computed server-side from current equipment.
    load_hint: str | None = None
    # PROG-1: compact program-mode badge (e.g. "Greyskull LP · AMRAP last ·
    # +5") when this exercise is a program lift. Derived at serialization
    # time from the equipment program config — no DB column / migration.
    # Null for normal generator-driven exercises. The daily indicator on
    # both StrengthToday surfaces.
    program_scheme: str | None = None
    # LOG-1: the working sets from the LAST time this exercise was done (most
    # recent prior session), for a faint "last: 30×8 · 30×8" ghost line in the
    # logger. Empty when there's no prior real set. Excludes warmups/skipped
    # and this workout; computed server-side. Set-level filters only (no
    # workout-status gate — auto-skip flips forgotten-to-finish sessions to
    # "skipped" even though their sets are real).
    last_sets: list[LastSetOut] = []
    # SKIP-1: the user explicitly declined this slot. Clients render it
    # collapsed with an Undo affordance instead of a live logging table,
    # and count it as accounted-for so the exercise stops floating to the
    # top of an already-finished session. Distinct from "sets == []",
    # which means "never touched" — the AI reviewer consumes the
    # difference (deliberate skip vs forgotten exercise).
    skipped: bool = False
    # TD-10 — the user appended this slot mid-session; the generator did not
    # prescribe it. Mirrors the skipped/never-touched distinction above:
    # explain_workout must not claim to have reasoned its way to a lift the
    # user chose, and the AI reviewer reads a self-added accessory
    # differently from a planned one.
    added_ad_hoc: bool = False
    # TD-6 — the per-set prescription, with server-resolved prefills. Clients
    # render these verbatim; they must not derive their own starting values.
    planned_sets: list[PlannedSetOut] = []
    sets: list[SetOut] = []


class WorkoutIn(BaseModel):
    """Manual workout creation (rarely used in v1 — the generator is the
    primary creator). Useful for tests + ad-hoc 'log this session I just
    did' from the dashboard."""
    date: date
    split_focus: str
    seed: str | None = None
    exercises: list[WorkoutExerciseIn] = []
    notes: str | None = None


class SessionSummary(BaseModel):
    """What one finished session actually cost, computed once, server-side.

    Every field here was previously either absent or derived independently by
    each client. `net_duration_s` is the clearest example: both clients
    synthesised the activities-feed row with gross `completed_at - started_at`
    while `analytics/advanced.py:_strength_training_stress` subtracted the
    accumulated pause, so the feed and the CTL/ATL model already reported
    different durations for the same workout, and a session left open on the
    rack during a phone call read as a multi-hour effort in one of them.

    `kcal_method` is not decoration. It says whether the energy figure came
    from integrating the real heart-rate series over the session (`hr`), from
    a compendium MET value scaled by body weight (`met`), or whether there
    was not enough profile data to estimate honestly (`none`, with
    `kcal_est` null). An estimate rendered as a bare number is
    indistinguishable from a measurement, which is the specific failure this
    field exists to prevent.
    """
    net_duration_s: int | None = None
    working_sets: int = 0
    total_reps: int = 0
    total_volume_lb: float = 0.0
    avg_hr: float | None = None
    max_hr: float | None = None
    kcal_est: float | None = None
    kcal_method: Literal["hr", "met", "none"] = "none"


class WorkoutOut(BaseModel):
    id: int
    date: date
    generated_at: datetime
    split_focus: str
    status: str
    seed: str
    recovery_score_used: float | None
    readiness_score_used: float | None
    sleep_h_used: float | None
    started_at: datetime | None
    completed_at: datetime | None
    notes: str | None
    # WP-14 pause/resume. `paused_at` is non-null only while the session
    # is paused; `total_paused_s` is the running sum of paused intervals.
    paused_at: datetime | None = None
    total_paused_s: int = 0
    # FAST-18 — populated when the plan was generated against an
    # active fast. Shape: {active, current_hours, stage, modulation}.
    # Clients render an amber banner when modulation != "normal".
    fasting_context: dict[str, Any] | None = None
    # Automatic recovery/readiness deload multiplier applied to this plan's
    # weights (1.0 = none). When < 1.0, clients surface a "load eased for
    # recovery — Use full weight" banner; the action regenerates with
    # force_full_weight=true. `deload_reason` is a short human string
    # ("recovery 52", "readiness 28").
    deload_factor: float = 1.0
    deload_reason: str | None = None
    # SKIP-1 progress counters, computed server-side. Four separate client
    # formulas used to derive these independently and disagreed — the web
    # set pip excluded skipped sets while the phone's included them, so the
    # same session could read differently on the two surfaces. Per the
    # architecture rule (server is the source of truth for any number a
    # user sees), both clients now render these verbatim.
    #
    # An exercise counts as done when it is skipped outright, or when its
    # accounted sets (logged or individually skipped) reach target_sets.
    # `sets_done` counts accounted sets, capped per exercise at target_sets
    # so extra sets can't push a session over 100%; a skipped exercise
    # contributes its whole target.
    exercises_done: int = 0
    exercises_total: int = 0
    sets_done: int = 0
    sets_total: int = 0
    # TD-4 — net duration, tonnage and energy cost, all server-computed.
    # Null until the session is finished; there is nothing to summarise about
    # a workout that has not happened yet.
    session_summary: SessionSummary | None = None
    exercises: list[WorkoutExerciseOut] = []


class WorkoutPatch(BaseModel):
    # `regenerated` is the discard target — keeps the row for history
    # but takes it out of the "today's current workout" query so the
    # screen falls through to whatever was previously today's plan.
    status: Literal[
        "planned", "in_progress", "paused", "completed", "skipped",
        "regenerated",
    ] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    # SKIP-1 — on the transition into "completed", mark every exercise slot
    # that has no logged sets as skipped, so a finished session doesn't keep
    # rendering live logging tables for exercises the user walked away from.
    #
    # Defaults to True because the completion path is not always interactive:
    # the Android notification action completes a workout with no UI in which
    # to confirm anything. The interactive surfaces ask first (a dialog naming
    # the un-logged exercises) and then send this explicitly, which is what
    # keeps "I chose to skip" distinguishable from "I forgot" for the AI
    # reviewer. Every flag it sets is reversible from the client.
    close_remaining: bool = True


class CompleteCardioBody(BaseModel):
    """Body for `POST /workouts/{id}/complete-cardio`. Used when the user
    finished a cardio session that didn't come through Strava / Concept2 /
    Health Connect — e.g. Les Mills VR, an outdoor walk without a watch
    track, a treadmill that doesn't ANT+ broadcast. We mint a manual
    Activity row, link the strength workout to it, and the activity then
    flows through the existing feed + chart-marker + cardio-coach
    pipelines."""
    label: str = Field(min_length=1, max_length=120,
                       description="User-supplied name shown in the feed and chart marker.")
    duration_minutes: float = Field(gt=0, le=24 * 60)
    # When omitted: start = now - duration. Lets the user complete a
    # cardio session retroactively (e.g. they forgot to tap before
    # starting and the HR window is in the past).
    start_at: datetime | None = None
    type: str = Field(default="manual_cardio", max_length=64)
    notes: str | None = Field(default=None, max_length=400)


def _set_to_out(s: models.StrengthSet) -> SetOut:
    return SetOut(
        id=s.id,
        workout_exercise_id=s.workout_exercise_id,
        set_number=s.set_number,
        target_weight_lb=s.target_weight_lb,
        target_reps=s.target_reps,
        actual_weight_lb=s.actual_weight_lb,
        actual_reps=s.actual_reps,
        rating=s.rating,
        rest_seconds_taken=s.rest_seconds_taken,
        logged_at=s.logged_at,
        skipped=s.skipped,
        set_type=s.set_type or "working",
    )


async def _detect_pr(
    db: AsyncSession, exercise_id: str, s: "models.StrengthSet",
) -> tuple[bool, bool]:
    """PR-1: which records this set just set for the exercise, vs all PRIOR
    working sets (excluding this one). Returns (weight_pr, e1rm_pr). No prior
    history -> (False, False): the first-ever set isn't a "record"."""
    if (s.actual_weight_lb is None or s.actual_reps is None or s.skipped
            or (s.set_type or "working") == "warmup"):
        return (False, False)
    rows = (await db.execute(
        select(models.StrengthSet.actual_weight_lb, models.StrengthSet.actual_reps)
        .join(models.StrengthWorkoutExercise,
              models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id)
        .where(models.StrengthWorkoutExercise.exercise_id == exercise_id)
        .where(models.StrengthSet.id != s.id)
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .where(models.StrengthSet.set_type != "warmup")
    )).all()
    if not rows:
        return (False, False)
    prior_w = [r.actual_weight_lb for r in rows if r.actual_weight_lb is not None]
    prior_max_w = max(prior_w) if prior_w else None
    prior_max_e1 = max(
        (strength_algo.estimate_1rm(r.actual_weight_lb, r.actual_reps) or 0.0
         for r in rows), default=0.0)
    this_e1 = strength_algo.estimate_1rm(s.actual_weight_lb, s.actual_reps) or 0.0
    weight_pr = prior_max_w is not None and s.actual_weight_lb > prior_max_w
    e1rm_pr = this_e1 > prior_max_e1
    return (weight_pr, e1rm_pr)


def _program_badge(state: dict) -> str:
    """Compact PROG-1 daily indicator for a program lift's exercise card."""
    scheme = state.get("scheme", "linear")
    inc = f"{float(state.get('increment_lb', 5.0)):g}"
    if scheme == "greyskull":
        return f"Greyskull LP · AMRAP last · +{inc}"
    if scheme == "double":
        lo, hi = state.get("reps_low", 8), state.get("reps_high", 12)
        return f"Double {lo}-{hi} · +{inc} at top"
    return f"Linear · +{inc}/session"


def _accounted_sets(wex_out: WorkoutExerciseOut) -> int:
    """Sets on this slot the user has dealt with — logged or individually
    skipped — capped at the prescription so an extra set can't inflate the
    session's progress past 100%. A skipped slot accounts for all of them."""
    if wex_out.skipped:
        return wex_out.target_sets
    n = sum(1 for s in wex_out.sets if s.actual_reps is not None or s.skipped)
    return min(n, wex_out.target_sets)


def _exercise_done(wex_out: WorkoutExerciseOut) -> bool:
    """Nothing left to do on this slot. The single definition both clients
    consume via WorkoutOut.exercises_done — see the note there."""
    return wex_out.skipped or _accounted_sets(wex_out) >= wex_out.target_sets


def _planned_sets(
    wex: models.StrengthWorkoutExercise,
    sets: list[models.StrengthSet],
    last_sets: list[LastSetOut] | None,
    program: dict | None,
) -> list[PlannedSetOut]:
    """Expand a slot's flat prescription into one row per set.

    Deliberately derived, never materialised. `log_set` is idempotent on
    `(workout_exercise_id, set_number)` *because* sets are created lazily on
    log, and the SKIP-1 note already records why fabricated rows are
    poisonous: `recent_mobility_history` counts a skipped set as a failed one
    and lowers the next hold prescription, and the deload payload folds
    skipped sets into `missed_or_skipped_sets`, which the coach reads as
    accumulating fatigue. Writing placeholder rows here would reintroduce
    both, plus break the idempotency the offline replay path depends on.
    """
    logged_by_number = {
        s.set_number: s for s in sets
        if s.actual_reps is not None and not s.skipped
    }
    # Tier 1: the most recent real set in THIS session. An edit on set 1
    # should carry forward, which is the phone's rule and the correct one.
    most_recent = (
        logged_by_number[max(logged_by_number)] if logged_by_number else None
    )
    # Tier 2: the same-index set from last session.
    last_by_number = {ls.set_number: ls for ls in (last_sets or [])}

    amrap_last = bool((program or {}).get("amrap_last_set")) and \
        (program or {}).get("scheme") == "greyskull"

    out: list[PlannedSetOut] = []
    for n in range(1, max(1, wex.target_sets) + 1):
        # Working sets only for now. The set_type field exists so a warm-up
        # ramp can be added without another client change, but prescribing
        # warm-ups today would change what sets_total means and the SKIP-1
        # counters would need to learn to exclude them -- a separate,
        # riskier change that should not ride along with a prefill fix.
        set_type = "working"

        prefill_weight = wex.target_weight_lb
        prefill_reps = wex.target_reps_low
        prior = logged_by_number.get(n)
        if prior is not None:
            # Already logged: show what was actually done, so an edit starts
            # from the truth rather than from the plan.
            prefill_weight = prior.actual_weight_lb
            prefill_reps = prior.actual_reps or wex.target_reps_low
        elif most_recent is not None and most_recent.set_type == set_type:
            # Same tier only. A light warm-up must never seed a working set.
            prefill_weight = most_recent.actual_weight_lb
            prefill_reps = most_recent.actual_reps or wex.target_reps_low
        elif n in last_by_number:
            ls = last_by_number[n]
            prefill_weight = ls.weight_lb if ls.weight_lb is not None else prefill_weight
            prefill_reps = ls.reps if ls.reps is not None else prefill_reps

        out.append(PlannedSetOut(
            set_number=n,
            set_type=set_type,
            target_weight_lb=wex.target_weight_lb,
            target_reps=wex.target_reps_low,
            rest_s=wex.target_rest_s,
            is_amrap=amrap_last and n == wex.target_sets,
            prefill_weight_lb=prefill_weight,
            prefill_reps=prefill_reps,
            # Never defaulted. See PlannedSetOut's docstring: a pre-selected
            # rating is a fabricated input to next session's weight choice.
            prefill_rating=(prior.rating if prior is not None else None),
        ))
    return out


def _wex_to_out(
    wex: models.StrengthWorkoutExercise,
    sets: list[models.StrengthSet],
    pairs_lb: list[float] | None = None,
    wrist_lb: list[float] | None = None,
    last_sets: list[LastSetOut] | None = None,
    program_by_id: dict[str, dict] | None = None,
) -> WorkoutExerciseOut:
    prog = (program_by_id or {}).get(wex.exercise_id)
    return WorkoutExerciseOut(
        id=wex.id,
        workout_id=wex.workout_id,
        exercise_id=wex.exercise_id,
        order_index=wex.order_index,
        superset_id=wex.superset_id,
        target_sets=wex.target_sets,
        target_reps_low=wex.target_reps_low,
        target_reps_high=wex.target_reps_high,
        target_weight_lb=wex.target_weight_lb,
        target_rest_s=wex.target_rest_s,
        is_timed=bool(_CATALOG_BY_ID.get(wex.exercise_id, {}).get("is_timed")),
        notes=wex.notes,
        load_hint=strength_algo.describe_load(
            wex.target_weight_lb, pairs_lb or [], wrist_lb or [],
        ),
        program_scheme=_program_badge(prog) if prog else None,
        last_sets=last_sets or [],
        skipped=bool(wex.skipped),
        added_ad_hoc=bool(getattr(wex, "added_ad_hoc", False)),
        planned_sets=_planned_sets(wex, sets, last_sets, prog),
        sets=[_set_to_out(s) for s in sorted(sets, key=lambda x: x.set_number)],
    )


def _summary_from_parts(
    w: models.StrengthWorkout,
    set_stats: dict[str, Any],
    hr_stats: dict[str, Any],
    weight_kg: float | None,
    age: int | None,
    sex: str | None,
) -> SessionSummary | None:
    """Assemble a SessionSummary from figures already in hand.

    Pure and synchronous on purpose: the list endpoint batches its set and
    heart-rate aggregates across the whole page and then calls this once per
    row, so building the summary costs no extra queries. The detail endpoint
    fetches the same two aggregates for a single workout and calls the same
    function, which is what keeps the feed and the detail view from drifting
    apart the way the duration figures already had.
    """
    if w.status != "completed":
        return None
    net_s = energy.net_duration_s(w.started_at, w.completed_at, w.total_paused_s)
    kcal, method = energy.estimate_session_kcal(
        net_minutes=(net_s or 0) / 60.0,
        avg_hr=hr_stats.get("avg_hr"),
        weight_kg=weight_kg,
        age=age,
        sex=sex,
        split_focus=w.split_focus,
    )
    return SessionSummary(
        net_duration_s=net_s,
        working_sets=int(set_stats.get("set_count") or 0),
        total_reps=int(set_stats.get("total_reps") or 0),
        total_volume_lb=float(set_stats.get("total_volume_lb") or 0.0),
        avg_hr=hr_stats.get("avg_hr"),
        max_hr=hr_stats.get("max_hr"),
        kcal_est=kcal,
        kcal_method=method,
    )


async def _energy_inputs(
    db: AsyncSession,
) -> tuple[float | None, int | None, str | None]:
    """The body data the energy estimators need: `(weight_kg, age, sex)`.

    Any of the three may be None, and the estimator treats that as a reason
    to fall back or to decline rather than to substitute a default. Hoisted
    out of the per-workout path so the list endpoint fetches it once for the
    whole page instead of once per row.
    """
    profile = await db.get(models.UserProfile, 1)
    age: int | None = None
    if profile is not None and profile.birth_date is not None:
        # Local rather than UTC: a birthday begins in the user's own
        # timezone. The difference is at most a day and rarely changes the
        # integer year, but there is no reason for this to be the one
        # calendar-day derivation in the file that reads UTC.
        age = (_local_today() - profile.birth_date).days // 365
    latest_bw = (await db.execute(
        select(models.BodyMetric.weight_kg)
        .where(models.BodyMetric.weight_kg.is_not(None))
        .order_by(models.BodyMetric.time.desc())
        .limit(1)
    )).scalar()
    return (
        float(latest_bw) if latest_bw else None,
        age,
        profile.sex if profile else None,
    )


async def _session_summary(
    db: AsyncSession,
    w: models.StrengthWorkout,
    *,
    set_stats: dict[str, Any] | None = None,
    hr_stats: dict[str, Any] | None = None,
) -> SessionSummary | None:
    """Assemble the finished-session summary for one workout.

    Returns None for anything not yet finished — an in-progress session has
    no total to report, and reporting a partial one as though it were final
    is how a feed ends up disagreeing with itself.

    `set_stats` and `hr_stats` let the list endpoint pass in figures it has
    already batched across every workout in the page, so this does not
    reintroduce the per-row query it was written to remove.
    """
    if w.status != "completed":
        return None

    if set_stats is None:
        agg = (await db.execute(
            select(
                func.count(models.StrengthSet.id),
                func.coalesce(func.sum(models.StrengthSet.actual_reps), 0),
                func.coalesce(func.sum(
                    models.StrengthSet.actual_weight_lb * models.StrengthSet.actual_reps
                ), 0.0),
            )
            .join(models.StrengthWorkoutExercise,
                  models.StrengthSet.workout_exercise_id ==
                  models.StrengthWorkoutExercise.id)
            .where(models.StrengthWorkoutExercise.workout_id == w.id)
            .where(models.StrengthSet.actual_reps.is_not(None))
            .where(models.StrengthSet.skipped.is_(False))
            .where(models.StrengthSet.set_type != "warmup")
        )).first()
        set_stats = {
            "set_count": int(agg[0] or 0),
            "total_reps": int(agg[1] or 0),
            "total_volume_lb": round(float(agg[2] or 0.0), 1),
        }

    if hr_stats is None:
        hr_stats = {}
        if w.started_at and w.completed_at:
            row = (await db.execute(
                select(func.avg(models.HeartRate.bpm), func.max(models.HeartRate.bpm))
                .where(models.HeartRate.time >= w.started_at)
                .where(models.HeartRate.time <= w.completed_at)
            )).first()
            if row and row[0] is not None:
                hr_stats = {
                    "avg_hr": round(float(row[0]), 1),
                    "max_hr": round(float(row[1]), 1) if row[1] is not None else None,
                }

    weight_kg, age, sex = await _energy_inputs(db)
    return _summary_from_parts(w, set_stats, hr_stats, weight_kg, age, sex)


async def _hydrate_workout(
    db: AsyncSession, w: models.StrengthWorkout
) -> WorkoutOut:
    """Load exercises + sets for a workout in two queries and assemble."""
    wex_rows = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == w.id)
        .order_by(models.StrengthWorkoutExercise.order_index)
    )).scalars().all()
    wex_ids = [w.id for w in wex_rows]
    sets_rows: list[models.StrengthSet] = []
    if wex_ids:
        sets_rows = (await db.execute(
            select(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id.in_(wex_ids))
        )).scalars().all()
    sets_by_wex: dict[int, list[models.StrengthSet]] = {}
    for s in sets_rows:
        sets_by_wex.setdefault(s.workout_exercise_id, []).append(s)
    # LOAD-1: current equipment for the "how to load it" hints (one load).
    equip = await _equipment_payload(db)
    pairs_lb = (equip.get("dumbbells") or {}).get("pairs_lb") or []
    wrist_lb = equip.get("wrist_weights_lb") or []
    # PROG-1: program-lift map for the per-exercise scheme badge (empty
    # when program mode is off → no badge on any exercise).
    _prog = ((equip.get("training") or {}).get("program") or {})
    program_by_id: dict[str, dict] = {}
    if _prog.get("enabled"):
        for _pl in _prog.get("lifts") or []:
            if isinstance(_pl, dict) and _pl.get("exercise_id"):
                program_by_id[_pl["exercise_id"]] = _pl
    # LOG-1: previous-session working sets per exercise, for the ghost line.
    # One batched query for all of today's exercises; set-level filters only
    # (skipped/actual_reps/set_type) and NO workout-status gate — auto-skip
    # flips forgotten-to-finish sessions to "skipped" though their sets are
    # real. date < w.date excludes today (and, for history views, this
    # workout's own sets). Group by first-seen workout id per exercise so
    # only the single most-recent prior session survives.
    last_by_ex: dict[str, list[LastSetOut]] = {}
    ex_ids = list({wx.exercise_id for wx in wex_rows})
    if ex_ids:
        # 180d floor bounds the scan (exercise_id is unindexed) — a "last time"
        # older than that is stale enough to skip. The user trains multiple
        # times a week, so any live exercise is well inside the window.
        hist = (await db.execute(
            select(
                models.StrengthWorkoutExercise.exercise_id.label("ex_id"),
                models.StrengthWorkoutExercise.id.label("we_id"),
                models.StrengthSet.set_number,
                models.StrengthSet.actual_weight_lb,
                models.StrengthSet.actual_reps,
            )
            .join(models.StrengthWorkoutExercise,
                  models.StrengthSet.workout_exercise_id
                  == models.StrengthWorkoutExercise.id)
            .join(models.StrengthWorkout,
                  models.StrengthWorkout.id
                  == models.StrengthWorkoutExercise.workout_id)
            .where(models.StrengthWorkoutExercise.exercise_id.in_(ex_ids))
            .where(models.StrengthWorkout.date < w.date)
            .where(models.StrengthWorkout.date >= w.date - timedelta(days=180))
            .where(models.StrengthSet.skipped.is_(False))
            .where(models.StrengthSet.actual_reps.is_not(None))
            .where(models.StrengthSet.set_type != "warmup")
            .order_by(
                models.StrengthWorkoutExercise.exercise_id.asc(),
                models.StrengthWorkout.date.desc(),
                models.StrengthWorkout.id.desc(),
                models.StrengthWorkoutExercise.id.asc(),  # deterministic slot
                models.StrengthSet.set_number.asc(),
            )
        )).all()
        # Lock onto the FIRST workout_exercise slot seen per exercise (the most
        # recent session's first slot). Locking on the slot, not just the
        # workout, keeps the ghost to one clean set list even when the same
        # exercise occupied two slots of that session (via swap-to-duplicate).
        seen_wex: dict[str, int] = {}
        for r in hist:
            locked = seen_wex.get(r.ex_id)
            if locked is None:
                seen_wex[r.ex_id] = r.we_id
            elif r.we_id != locked:
                continue  # only the most-recent prior session's first slot
            last_by_ex.setdefault(r.ex_id, []).append(LastSetOut(
                set_number=r.set_number,
                weight_lb=r.actual_weight_lb,
                reps=r.actual_reps,
            ))
    # Surface the automatic recovery deload + a short reason so the client can
    # show a "load eased for recovery — Use full weight" banner. Legacy rows
    # (deload_factor NULL) are treated as 1.0 (no banner).
    df = w.deload_factor if w.deload_factor is not None else 1.0
    deload_reason: str | None = None
    if df < 1.0:
        bits: list[str] = []
        if w.recovery_score_used is not None and w.recovery_score_used < 60:
            bits.append(f"recovery {round(w.recovery_score_used)}")
        if w.readiness_score_used is not None and w.readiness_score_used < 30:
            bits.append(f"readiness {round(w.readiness_score_used)}")
        deload_reason = ("low " + " / ".join(bits)) if bits else "low recovery"
    ex_out = [
        _wex_to_out(wex, sets_by_wex.get(wex.id, []), pairs_lb, wrist_lb,
                    last_by_ex.get(wex.exercise_id), program_by_id)
        for wex in wex_rows
    ]
    return WorkoutOut(
        id=w.id,
        date=w.date,
        generated_at=w.generated_at,
        split_focus=w.split_focus,
        status=w.status,
        seed=w.seed,
        recovery_score_used=w.recovery_score_used,
        readiness_score_used=w.readiness_score_used,
        sleep_h_used=w.sleep_h_used,
        started_at=w.started_at,
        completed_at=w.completed_at,
        notes=w.notes,
        paused_at=w.paused_at,
        total_paused_s=w.total_paused_s or 0,
        # FAST-18 — fasting context is read live on every request, not
        # persisted on the workout row. The plan was generated against
        # the fast that was active at the time, so this reflects how
        # the fast looks *right now*; the UI can fade the banner once
        # the user has broken the fast.
        fasting_context=await strength_algo._active_fasting_context(db),
        deload_factor=df,
        deload_reason=deload_reason,
        exercises_done=sum(1 for e in ex_out if _exercise_done(e)),
        exercises_total=len(ex_out),
        sets_done=sum(_accounted_sets(e) for e in ex_out),
        sets_total=sum(e.target_sets for e in ex_out),
        session_summary=await _session_summary(db, w),
        exercises=ex_out,
    )


@router.get("/workouts")
async def list_workouts(
    limit: int = 100,
    status: str | None = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Workout history, newest first. Excludes 'regenerated' rows
    (internal regen-count bookkeeping). For completed workouts, the
    response includes lightweight aggregate stats (set count, total
    volume, total reps, avg/max HR over the workout window) so the
    web/phone activities feed can render them inline."""
    # Sweep stale planned rows before listing so yesterday's missed
    # workout shows as skipped in the feed, not as still-planned.
    await strength_algo.auto_skip_stale_workouts(db, _local_today())
    stmt = select(models.StrengthWorkout).order_by(
        models.StrengthWorkout.date.desc(),
        models.StrengthWorkout.generated_at.desc(),
    ).limit(limit)
    if status is not None:
        stmt = stmt.where(models.StrengthWorkout.status == status)
    else:
        stmt = stmt.where(models.StrengthWorkout.status != "regenerated")
    rows = (await db.execute(stmt)).scalars().all()

    # Bulk pull set aggregates per workout
    workout_ids = [w.id for w in rows if w.status == "completed"]
    set_stats: dict[int, dict[str, Any]] = {}
    if workout_ids:
        agg = await db.execute(
            select(
                models.StrengthWorkoutExercise.workout_id.label("wid"),
                func.count(models.StrengthSet.id).label("sets"),
                func.coalesce(func.sum(models.StrengthSet.actual_reps), 0).label("reps"),
                func.coalesce(
                    func.sum(models.StrengthSet.actual_weight_lb *
                             models.StrengthSet.actual_reps), 0
                ).label("volume"),
                func.avg(models.StrengthSet.rating).label("rpe_avg"),
            )
            .join(models.StrengthWorkoutExercise,
                  models.StrengthSet.workout_exercise_id ==
                  models.StrengthWorkoutExercise.id)
            .where(models.StrengthWorkoutExercise.workout_id.in_(workout_ids))
            .where(models.StrengthSet.actual_reps.is_not(None))
            .where(models.StrengthSet.skipped.is_(False))
            # TD-4 — warm-ups excluded, matching weekly_muscle_volume's
            # SETTYPE-1 rule. A warm-up single is not a working set, and the
            # feed counting it while the volume audit did not was one more
            # instance of the same number meaning two things.
            .where(models.StrengthSet.set_type != "warmup")
            .group_by(models.StrengthWorkoutExercise.workout_id)
        )
        for wid, sets, reps, vol, rpe in agg.all():
            set_stats[wid] = {
                "set_count": int(sets or 0),
                "total_reps": int(reps or 0),
                "total_volume_lb": round(float(vol or 0), 1),
                "rpe_avg": round(float(rpe), 2) if rpe is not None else None,
            }

    # HR window per workout (only when both started_at + completed_at present).
    #
    # TD-4, corrected in v0.8.1 — one round trip, aggregated by Postgres.
    #
    # The first version of this replaced an N+1 with something far worse: it
    # took the min start and max end across the whole page and pulled EVERY
    # heart-rate sample in that span into Python to bucket by hand. For a page
    # covering weeks that is hundreds of thousands of rows to compute a
    # handful of averages, and it took /workout/strength/workouts from
    # milliseconds to 5.5 seconds for five workouts and 17 seconds for two
    # hundred — slow enough that the phone's client timed out and reported it
    # as "can't reach server".
    #
    # A session window is a few thousand samples; the span between the first
    # and last session in a page is not. Joining the windows as a VALUES list
    # keeps it to one query while letting the index do the work and the
    # database do the aggregation, which is what "batched" should have meant.
    hr_stats: dict[int, dict[str, Any]] = {}
    windows = [
        (w.id, w.started_at, w.completed_at) for w in rows
        if w.status == "completed" and w.started_at and w.completed_at
    ]
    if windows:
        win = sa_values(
            sa_column("wid", BigInteger),
            sa_column("w_start", DateTime(timezone=True)),
            sa_column("w_end", DateTime(timezone=True)),
            name="win",
        ).data(windows)
        hr_rows = (await db.execute(
            select(
                win.c.wid,
                func.avg(models.HeartRate.bpm),
                func.max(models.HeartRate.bpm),
            )
            .select_from(win)
            .join(
                models.HeartRate,
                and_(
                    models.HeartRate.time >= win.c.w_start,
                    models.HeartRate.time <= win.c.w_end,
                ),
            )
            .group_by(win.c.wid)
        )).all()
        for wid, avg_bpm, max_bpm in hr_rows:
            if avg_bpm is not None:
                hr_stats[int(wid)] = {
                    "avg_hr": round(float(avg_bpm), 1),
                    "max_hr": round(float(max_bpm), 1) if max_bpm is not None else None,
                }

    weight_kg, age, sex = await _energy_inputs(db)

    return {
        "count": len(rows),
        "workouts": [
            {
                "id": w.id,
                "date": w.date.isoformat(),
                "split_focus": w.split_focus,
                "status": w.status,
                "started_at": w.started_at,
                "completed_at": w.completed_at,
                "generated_at": w.generated_at,
                "completed_by_activity_source": w.completed_by_activity_source,
                "completed_by_activity_source_id": w.completed_by_activity_source_id,
                **set_stats.get(w.id, {}),
                **hr_stats.get(w.id, {}),
                # TD-4 — the same summary object the detail endpoint returns,
                # so the feed stops deriving net duration and energy itself.
                "session_summary": _summary_from_parts(
                    w, set_stats.get(w.id, {}), hr_stats.get(w.id, {}),
                    weight_kg, age, sex,
                ),
            }
            for w in rows
        ],
    }


@router.get("/workouts/{workout_id}", response_model=WorkoutOut)
async def get_workout(
    workout_id: int, db: AsyncSession = Depends(get_session)
) -> WorkoutOut:
    w = await db.get(models.StrengthWorkout, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")
    return await _hydrate_workout(db, w)


@router.post("/workouts", response_model=WorkoutOut, status_code=201)
async def create_workout(
    body: WorkoutIn,
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """Create a workout manually (mainly for tests + ad-hoc 'I did this
    session, log it'). The generator in Phase 3 also writes through this
    table directly, not via this endpoint."""
    # Validate every exercise_id is in the catalog
    bad = [e.exercise_id for e in body.exercises if e.exercise_id not in _CATALOG_BY_ID]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"unknown exercise ids: {bad}",
        )
    now = datetime.now(timezone.utc)
    w = models.StrengthWorkout(
        date=body.date,
        generated_at=now,
        split_focus=body.split_focus,
        status="planned",
        seed=body.seed or body.date.isoformat(),
        notes=body.notes,
    )
    db.add(w)
    await db.flush()  # need w.id before children

    for ex in body.exercises:
        db.add(models.StrengthWorkoutExercise(
            workout_id=w.id,
            exercise_id=ex.exercise_id,
            order_index=ex.order_index,
            superset_id=ex.superset_id,
            target_sets=ex.target_sets,
            target_reps_low=ex.target_reps_low,
            target_reps_high=ex.target_reps_high,
            target_weight_lb=ex.target_weight_lb,
            target_rest_s=ex.target_rest_s,
            notes=ex.notes,
        ))
    await db.commit()
    await db.refresh(w)
    return await _hydrate_workout(db, w)


async def _advance_program_on_complete(
    db: AsyncSession, w: models.StrengthWorkout
) -> None:
    """PROG-1 — advance program-lift working weights when a workout is
    marked complete.

    For each program lift in this workout, reads the logged working sets,
    runs the pure scheme state machine (advance_program_lift), and writes
    the mutated state back into user_equipment.payload so the NEXT session
    prescribes the new weight. Idempotent per workout date via
    last_advanced_on (offline replay / re-PATCH can't double-advance).
    No-op when program mode is off. Runs inside patch_workout's txn."""
    eq = await db.get(models.UserEquipment, 1)
    if eq is None or not eq.payload:
        return
    payload = dict(eq.payload)
    training = dict(payload.get("training") or {})
    program = dict(training.get("program") or {})
    if not program.get("enabled"):
        return
    lifts = [dict(l) for l in (program.get("lifts") or []) if isinstance(l, dict)]
    by_id = {l["exercise_id"]: l for l in lifts if l.get("exercise_id")}
    if not by_id:
        return

    wex_rows = (await db.execute(
        select(
            models.StrengthWorkoutExercise.id,
            models.StrengthWorkoutExercise.exercise_id,
        ).where(models.StrengthWorkoutExercise.workout_id == w.id)
    )).all()
    on_date = w.date.isoformat()
    changed = False
    for wex_id, ex_id in wex_rows:
        st = by_id.get(ex_id)
        if st is None or st.get("last_advanced_on") == on_date:
            continue  # not a program lift, or already advanced for this date
        # Prescribed sets only: exclude warmups AND drop sets (lighter
        # supplementary work), but KEEP a to-failure AMRAP set — a
        # Greyskull last set taken to failure is naturally tagged
        # set_type="failure" and must count toward progression. Ordered
        # by set_number so reps[-1] is the true last set (the AMRAP),
        # regardless of the order the user logged them in.
        reps = [
            int(r) for r in (await db.execute(
                select(models.StrengthSet.actual_reps)
                .where(models.StrengthSet.workout_exercise_id == wex_id)
                .where(models.StrengthSet.set_type.notin_(("warmup", "drop")))
                .where(models.StrengthSet.actual_reps.is_not(None))
                .order_by(models.StrengthSet.set_number)
            )).scalars().all()
            if r is not None
        ]
        min_working = min(reps) if reps else None
        amrap = reps[-1] if reps else None  # Greyskull's last-set AMRAP
        new_st = strength_algo.advance_program_lift(
            st, min_working, amrap, on_date=on_date)
        if new_st != st:
            by_id[ex_id] = new_st
            changed = True
    if not changed:
        return
    program["lifts"] = [by_id.get(l.get("exercise_id"), l) for l in lifts]
    training["program"] = program
    payload["training"] = training
    eq.payload = payload  # reassign → SQLAlchemy flags the JSON col dirty


async def _close_remaining_exercises(db: AsyncSession, workout_id: int) -> int:
    """SKIP-1 — mark every exercise in this workout that has no logged sets
    as skipped. Returns how many it flipped.

    "No logged sets" means no set row with an actual_reps value: a slot whose
    sets are all individually skipped is already accounted for, and a slot
    with partial work keeps its partial record (the user did some of it, and
    the AI reviewer should see the shortfall as missed, not declined).

    Deliberately does NOT write placeholder StrengthSet rows. Fabricating
    sets for work that never happened feeds recent_mobility_history's fail
    counter, which lowers the next hold prescription, and inflates the
    deload payload's missed_or_skipped_sets, which reads as fatigue.
    """
    slots = (
        select(models.StrengthWorkoutExercise.id)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .scalar_subquery()
    )
    # Scoped to this workout's slots so the NOT IN doesn't scan the whole
    # set table. workout_exercise_id is non-nullable, so the usual
    # NOT IN + NULL trap doesn't apply.
    worked = (
        select(models.StrengthSet.workout_exercise_id)
        .where(models.StrengthSet.workout_exercise_id.in_(slots))
        .where(models.StrengthSet.actual_reps.isnot(None))
        .scalar_subquery()
    )
    res = await db.execute(
        sa_update(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .where(models.StrengthWorkoutExercise.skipped.is_(False))
        .where(models.StrengthWorkoutExercise.id.notin_(worked))
        .values(skipped=True)
    )
    return int(res.rowcount or 0)


@router.patch("/workouts/{workout_id}", response_model=WorkoutOut)
async def patch_workout(
    workout_id: int,
    body: WorkoutPatch,
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    w = await db.get(models.StrengthWorkout, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")
    data = body.model_dump(exclude_unset=True)
    # Not a column — pop it before the setattr loop below.
    close_remaining = bool(data.pop("close_remaining", True))

    # WP-14 pause/resume accounting. Pause/resume ride on the generic
    # status patch (so the phone's offline write-buffer covers them for
    # free), but the paused_at / total_paused_s bookkeeping is derived
    # server-side from the transition rather than trusted from the client.
    new_status = data.get("status")
    # PROG-1: capture the completion transition BEFORE setattr mutates
    # w.status, so the program-state advance fires exactly once.
    became_completed = new_status == "completed" and w.status != "completed"
    if new_status is not None and new_status != w.status:
        now = datetime.now(timezone.utc)
        if new_status == "paused":
            # Entering pause: stamp the start of this paused interval.
            # started_at may be null if the user pauses before logging a
            # set — backfill it so duration math has a left edge.
            if w.started_at is None:
                w.started_at = now
            w.paused_at = now
        elif w.paused_at is not None:
            # Leaving pause (resume / complete / skip): fold the elapsed
            # paused interval into the accumulator and clear the marker.
            w.total_paused_s = (w.total_paused_s or 0) + max(
                0, int((now - w.paused_at).total_seconds())
            )
            w.paused_at = None

    for field, value in data.items():
        setattr(w, field, value)
    if became_completed:
        # Stamp the finish server-side when the client didn't send one.
        # complete_cardio already does this; the generic patch used to rely
        # on the client, so a notification-action complete left it null.
        if w.completed_at is None:
            w.completed_at = datetime.now(timezone.utc)
        if close_remaining:
            await _close_remaining_exercises(db, w.id)
        await _advance_program_on_complete(db, w)
    await db.commit()
    await db.refresh(w)
    return await _hydrate_workout(db, w)


@router.post("/workouts/{workout_id}/complete-cardio", response_model=WorkoutOut)
async def complete_cardio_with_activity(
    workout_id: int,
    body: CompleteCardioBody,
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """Mark a cardio-day strength workout complete AND mint a manual
    Activity row so the session shows up in the activity feed, on HR
    chart markers (existing activity-window overlay), and counts toward
    the weekly cardio dose in the cardio coach payload.

    Use case: user does Les Mills VR or a treadmill jog that doesn't
    push to Strava/Concept2/Health Connect. Without this, completing
    the workout marks it done but leaves the cardio dose payload
    showing zero minutes for the week.
    """
    w = await db.get(models.StrengthWorkout, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")
    if w.split_focus not in ("cardio", "active_recovery", "yoga"):
        # Strength sessions already have a different completion path
        # (sets logged). Don't widen the door here.
        raise HTTPException(
            status_code=400,
            detail=f"complete-cardio is for cardio/recovery/yoga splits, "
                   f"not split_focus={w.split_focus!r}",
        )

    now = datetime.now(timezone.utc)
    duration_s = int(body.duration_minutes * 60)
    start_at = body.start_at or (now - timedelta(seconds=duration_s))
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    end_at = start_at + timedelta(seconds=duration_s)

    # Pull HR samples in the activity window and compute summary stats.
    hr_rows = (await db.execute(
        select(models.HeartRate.bpm)
        .where(models.HeartRate.time >= start_at)
        .where(models.HeartRate.time <= end_at)
    )).scalars().all()
    avg_hr = (sum(hr_rows) / len(hr_rows)) if hr_rows else None
    max_hr = max(hr_rows) if hr_rows else None

    # source_id needs to be stable + unique. Pair the workout id with
    # the start timestamp so a regenerate / accidental double-tap can't
    # collide. 64 chars max in the column.
    source_id = f"workout-{workout_id}-{int(start_at.timestamp())}"

    activity = models.Activity(
        source="manual",
        source_id=source_id,
        type=body.type,
        name=body.label,
        start_at=start_at,
        duration_s=duration_s,
        avg_hr=avg_hr,
        max_hr=max_hr,
        notes=body.notes,
    )
    db.add(activity)

    w.status = "completed"
    w.completed_at = now
    w.completed_by_activity_source = "manual"
    w.completed_by_activity_source_id = source_id
    if body.notes:
        w.notes = body.notes

    await db.commit()
    await db.refresh(w)
    return await _hydrate_workout(db, w)


@router.delete("/workouts/{workout_id}", status_code=204)
async def delete_workout(
    workout_id: int, db: AsyncSession = Depends(get_session)
) -> None:
    w = await db.get(models.StrengthWorkout, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")
    # Cascade by hand — we don't model FKs in the schema (matches house style).
    wex_ids = (await db.execute(
        select(models.StrengthWorkoutExercise.id)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
    )).scalars().all()
    if wex_ids:
        await db.execute(
            delete(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id.in_(wex_ids))
        )
    await db.execute(
        delete(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
    )
    await db.delete(w)
    await db.commit()


# ------------------------------------------------------------------
# Sets — POST one-at-a-time from the phone during the active workout
# ------------------------------------------------------------------

@router.post("/sets", response_model=SetOut, status_code=201)
async def log_set(
    body: SetIn,
    db: AsyncSession = Depends(get_session),
) -> SetOut:
    """Idempotent on (workout_exercise_id, set_number). Re-POSTing the
    same set updates the row in place — useful when the phone retries
    after a flaky network."""
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(status_code=400, detail="rating must be 1..5")
    if body.set_type not in ("working", "warmup", "drop", "failure"):
        raise HTTPException(status_code=400, detail="invalid set_type")
    wex = await db.get(models.StrengthWorkoutExercise, body.workout_exercise_id)
    if wex is None:
        raise HTTPException(status_code=404, detail="workout_exercise not found")

    existing = (await db.execute(
        select(models.StrengthSet)
        .where(models.StrengthSet.workout_exercise_id == body.workout_exercise_id)
        .where(models.StrengthSet.set_number == body.set_number)
        .limit(1)
    )).scalar_one_or_none()

    logged_at = body.logged_at or datetime.now(timezone.utc)
    if existing is None:
        s = models.StrengthSet(
            workout_exercise_id=body.workout_exercise_id,
            set_number=body.set_number,
            target_weight_lb=body.target_weight_lb,
            target_reps=body.target_reps,
            actual_weight_lb=body.actual_weight_lb,
            actual_reps=body.actual_reps,
            rating=body.rating,
            rest_seconds_taken=body.rest_seconds_taken,
            logged_at=logged_at,
            skipped=body.skipped,
            set_type=body.set_type,
        )
        db.add(s)
    else:
        s = existing
        s.target_weight_lb = body.target_weight_lb
        s.target_reps = body.target_reps
        s.actual_weight_lb = body.actual_weight_lb
        s.actual_reps = body.actual_reps
        s.rating = body.rating
        s.rest_seconds_taken = body.rest_seconds_taken
        s.logged_at = logged_at
        s.skipped = body.skipped
        s.set_type = body.set_type

    # Auto-advance the parent workout to in_progress on the first logged set
    workout = await db.get(models.StrengthWorkout, wex.workout_id)
    if workout is not None and workout.status == "planned":
        workout.status = "in_progress"
        if workout.started_at is None:
            workout.started_at = logged_at

    await db.commit()
    await db.refresh(s)
    out = _set_to_out(s)
    if not s.skipped:
        out.is_weight_pr, out.is_e1rm_pr = await _detect_pr(db, wex.exercise_id, s)
    return out


class SwapBody(BaseModel):
    exercise_id: str


@router.get("/upcoming")
async def upcoming_workouts(
    days: int = 7,
    per_day_count: int = 4,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Project the next `days` calendar days. For each one that maps to a
    workout day (per training.days_per_week), simulate the split + exercise
    selection and return a preview. Does NOT persist anything; this is a
    pure read-only forecast that lets the user see what's coming up."""
    from datetime import date as _date, timedelta as _td
    import random as _random

    equip = await _equipment_payload(db)
    training = equip.get("training") or {}
    dpw = int(training.get("days_per_week", strength_algo.DEFAULT_DAYS_PER_WEEK))
    pref = training.get("split_preference", strength_algo.DEFAULT_SPLIT_PREFERENCE)
    level = training.get("level", strength_algo.DEFAULT_LEVEL)
    exercise_prefs = equip.get("exercise_prefs") or {}

    # Mon-first weekday pattern matching the web/Android strip
    PATTERN = {2: {0, 3}, 3: {0, 2, 4}, 4: {0, 1, 3, 4},
               5: {0, 1, 2, 3, 4}, 6: {0, 1, 2, 3, 4, 5}}
    workout_dows = PATTERN.get(dpw, PATTERN[3])

    catalog_filtered = strength_algo.filter_catalog_for_equipment(
        strength_algo.CATALOG, equip,
    )

    # Walk forward, advancing the rotation each time we land on a workout day.
    # If the user just trained off-schedule, the day after gets demoted
    # to rest so they don't hit two consecutive workout days.
    today = _local_today()
    last_split = await strength_algo.last_split_for_user(db)

    # Last completed STRENGTH workout date — drives the "don't schedule
    # two strength sessions back-to-back" spacing rule. Yoga + cardio
    # are intentionally NOT counted; finishing a 30-min yoga flow
    # yesterday isn't a reason to push tomorrow's strength day to the
    # day after. Before this filter, a daily yoga habit would walk the
    # strength rotation forward indefinitely (Mon→Tue→Thu→Sat) and the
    # WeekStrip preview disagreed with the real schedule.
    last_done_q = await db.execute(
        select(func.max(models.StrengthWorkout.date))
        .where(models.StrengthWorkout.status == "completed")
        .where(models.StrengthWorkout.split_focus.notin_(["yoga", "cardio"]))
    )
    last_done = last_done_q.scalar()

    out: list[dict[str, Any]] = []
    cursor_split = last_split

    # Today already has a persisted plan (the app generates one daily). The
    # forecast MUST agree with it rather than simulate a fresh strength session
    # for today. Today is frequently a yoga / cardio / rest day; simulating a
    # phantom strength session here (a) disagreed with the real plan and (b)
    # consumed a rotation step — so the strip showed the rotation one slot
    # behind ("legs" the day after a just-completed legs session). Emit today's
    # real plan, advance the cursor only when today is itself a rotation-
    # strength day, then simulate strictly the FUTURE days. (Read-only: never
    # generate a missing plan here — fall back to simulating today instead.)
    start_offset = 0
    today_plan = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == today)
        .order_by(models.StrengthWorkout.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if today_plan is not None:
        today_count = (await db.execute(
            select(func.count(models.StrengthWorkoutExercise.id))
            .where(models.StrengthWorkoutExercise.workout_id == today_plan.id)
        )).scalar() or 0
        out.append({
            "date": today.isoformat(),
            "is_today": True,
            "split_focus": today_plan.split_focus,
            "preview_exercises": [],
            "exercise_count": int(today_count),
        })
        if today_plan.split_focus in strength_algo._ROTATION_FOCUSES:  # noqa: SLF001
            # Today is a real rotation session — future days rotate off it, and
            # it counts as the most recent training day for the spacing rule.
            cursor_split = today_plan.split_focus
            last_done = today
        start_offset = 1

    for offset in range(start_offset, days + 1):
        d = today + _td(days=offset)
        # Mon-first index
        mon_first = (d.weekday())  # Python's weekday(): Mon=0..Sun=6 ✓
        if mon_first not in workout_dows:
            continue
        # Spacing: if this scheduled day lands the day after the last training
        # day, push it back one day when possible so the user doesn't hit two
        # strength sessions back-to-back. The shifted day is the SINGLE session
        # for this slot — the rotation advances exactly once for it just below,
        # so we must NOT advance the cursor here as well (that double-advance
        # was the rotation-misalignment bug).
        if last_done is not None and (d - last_done).days == 1:
            shifted = d + _td(days=1)
            if shifted.weekday() not in workout_dows:
                d = shifted
            # else: next day is already a workout day — leave both alone.

        focus = strength_algo.select_split(dpw, pref, cursor_split)
        cursor_split = focus
        seed = strength_algo._seed(d, 0)  # noqa: SLF001
        rng = _random.Random(seed)
        try:
            chosen, _slots, _notes = strength_algo.select_exercises_for_split(
                catalog_filtered, focus, level, rng, exercise_prefs=exercise_prefs,
            )
        except Exception:
            chosen = []
        names = [
            strength_algo.CATALOG_BY_ID.get(c["id"], {}).get("name", c["id"])
            for c in chosen[:per_day_count]
        ]
        out.append({
            "date": d.isoformat(),
            "is_today": offset == 0,
            "split_focus": focus,
            "preview_exercises": names,
            "exercise_count": len(chosen),
        })
        last_done = d  # treat this scheduled day as the new "last" for spacing
    return {"count": len(out), "upcoming": out}


class WorkoutExercisePatch(BaseModel):
    skipped: bool


@router.patch("/workout-exercises/{wex_id}", response_model=WorkoutOut)
async def patch_workout_exercise(
    wex_id: int,
    body: WorkoutExercisePatch,
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """SKIP-1 — mark one exercise slot skipped, or un-skip it.

    Returns the whole rehydrated workout rather than just the slot, so the
    caller picks up the recomputed progress counters in the same round trip
    (they're workout-level, and the clients render them verbatim).

    Un-skipping is the Undo path and is always allowed. Skipping a slot that
    already has real logged sets is refused — the sets are the record of work
    performed, and hiding them behind a skip flag would quietly drop them out
    of the exercise-done count while leaving them in every tonnage aggregate.
    Delete the sets first if that's genuinely the intent.
    """
    wex = await db.get(models.StrengthWorkoutExercise, wex_id)
    if wex is None:
        raise HTTPException(status_code=404, detail="workout exercise not found")
    if body.skipped and not wex.skipped:
        logged = (await db.execute(
            select(func.count())
            .select_from(models.StrengthSet)
            .where(models.StrengthSet.workout_exercise_id == wex_id)
            .where(models.StrengthSet.actual_reps.isnot(None))
            .where(models.StrengthSet.skipped.is_(False))
        )).scalar_one()
        if logged:
            raise HTTPException(
                status_code=409,
                detail=f"{logged} set(s) already logged for this exercise",
            )
    wex.skipped = body.skipped
    w = await db.get(models.StrengthWorkout, wex.workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")
    await db.commit()
    await db.refresh(w)
    return await _hydrate_workout(db, w)


class AddExerciseBody(BaseModel):
    """Append an off-plan exercise to today's session."""
    exercise_id: str
    # Omitted means "same as the generator would prescribe for an accessory".
    target_sets: int | None = None
    # Where to insert. Omitted appends to the end, which is almost always
    # right: an accessory added mid-session belongs after the planned work,
    # not spliced into the middle of a superset.
    position: int | None = None


@router.post("/workouts/{workout_id}/exercises", response_model=WorkoutOut)
async def add_exercise(
    workout_id: int, body: AddExerciseBody,
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """Append an exercise the generator did not prescribe.

    Until TD-10 there was no route that added an exercise to a session. The
    API had `POST /workout-exercises/{id}/swap` (strictly 1:1, and refusing
    once a set is logged), `DELETE /workouts/{id}` and `DELETE /sets/{id}`,
    and nothing else -- `POST /workouts` exists but no client has ever called
    it. So three extra sets of curls done in the moment had nowhere to go,
    which meant they were missing from tonnage, `weekly_muscle_volume`,
    `/records`, the four-week rotation-pressure map, and every AI payload.

    The prescription is server-computed, reusing the same chain `swap_exercise`
    uses: last target weight from history, progressed by the trailing rating,
    falling back to the starting-weight table, then rounded against the
    user's actual dumbbell pairs and micro-loaders. A client-guessed weight
    would violate the architecture rule and then disagree with the server on
    the next reload.

    Returns the whole rehydrated workout, matching the SKIP-1 PATCH
    convention, so the caller picks up the recomputed progress counters and
    session summary in one round trip.
    """
    if body.exercise_id not in _CATALOG_BY_ID:
        raise HTTPException(status_code=404, detail="exercise not found")

    w = await db.get(models.StrengthWorkout, workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")
    if w.status in ("completed", "skipped", "regenerated"):
        raise HTTPException(
            status_code=409,
            detail=f"cannot add to a {w.status} workout",
        )

    new_ex = _CATALOG_BY_ID[body.exercise_id]
    equip = await _equipment_payload(db)
    level = (equip.get("training") or {}).get("level", "intermediate")
    pairs = (equip.get("dumbbells") or {}).get("pairs_lb") or []
    wrist = equip.get("wrist_weights_lb") or []
    goal = (equip.get("training") or {}).get("goal", "general")

    # Same weight chain as swap_exercise — one prescription policy.
    avg_rating, avg_weight, _avg_reps = await strength_algo.last_target_weight_for_exercise(
        db, body.exercise_id,
    )
    if avg_rating is not None and avg_weight is not None:
        target = strength_algo.progress_from_rating(
            avg_weight, avg_rating, new_ex["is_compound"],
        )
    else:
        target = strength_algo.starting_weight_lb(new_ex["movement_pattern"], level)
    if target is not None and "dumbbell" in new_ex["equipment"]:
        target = strength_algo.round_weight(target, pairs, wrist)
    if "dumbbell" not in new_ex["equipment"]:
        target = None

    # Reuse the generator's own prescription rather than inventing a second
    # policy. slot_role="isolation" is the honest description of an appended
    # accessory, and going through prescribe_slot also gets the is_timed
    # handling for free -- adding a plank should prescribe seconds, not reps.
    weight_kg, age, _sex = await _energy_inputs(db)
    bodyweight_lb = (weight_kg * 2.20462) if weight_kg else None
    sets_n, reps_low, reps_high, rest_s = strength_algo.prescribe_slot(
        new_ex, "isolation", goal, age=age, bodyweight_lb=bodyweight_lb,
    )

    existing = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .order_by(models.StrengthWorkoutExercise.order_index)
    )).scalars().all()

    if body.position is None or body.position >= len(existing):
        order_index = (existing[-1].order_index + 1) if existing else 0
    else:
        order_index = max(0, body.position)
        # Shift everything at or after the insertion point down one.
        for row in existing:
            if row.order_index >= order_index:
                row.order_index += 1

    wex = models.StrengthWorkoutExercise(
        workout_id=workout_id,
        exercise_id=body.exercise_id,
        order_index=order_index,
        # Never joined into a superset: the pairing in SPLIT_SLOTS is
        # deliberate and an appended accessory has no partner.
        superset_id=None,
        target_sets=max(1, min(10, body.target_sets or sets_n)),
        target_reps_low=reps_low,
        target_reps_high=reps_high,
        target_weight_lb=target,
        target_rest_s=rest_s,
        added_ad_hoc=True,
    )
    db.add(wex)
    await db.commit()

    log.info(
        "ad-hoc exercise added: workout=%s exercise=%s target=%s",
        workout_id, body.exercise_id,
        f"{target:.1f}lb" if target is not None else "bodyweight",
    )
    await db.refresh(w)
    return await _hydrate_workout(db, w)


@router.delete("/workout-exercises/{wex_id}", response_model=WorkoutOut)
async def delete_exercise(
    wex_id: int, db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """Remove an exercise slot from a session.

    Refuses (409) when real sets are logged against it, matching
    `swap_exercise`'s contract: the actuals are a record of work that was
    performed, and deleting the slot would silently erase it. Skipping the
    slot is the right move for "I'm not doing the rest of this"; deleting is
    for "this should not be here at all".
    """
    wex = await db.get(models.StrengthWorkoutExercise, wex_id)
    if wex is None:
        raise HTTPException(status_code=404, detail="workout_exercise not found")

    logged = (await db.execute(
        select(models.StrengthSet.id)
        .where(models.StrengthSet.workout_exercise_id == wex_id)
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.actual_reps.is_not(None))
    )).scalars().all()
    if logged:
        raise HTTPException(
            status_code=409,
            detail="cannot delete — sets already logged for this slot. "
                   "Skip it instead, or delete the logged sets first.",
        )

    w = await db.get(models.StrengthWorkout, wex.workout_id)
    if w is None:
        raise HTTPException(status_code=404, detail="workout not found")

    # Drop any skipped placeholder sets along with the slot; they exist only
    # to describe this slot and become orphans otherwise.
    await db.execute(
        delete(models.StrengthSet)
        .where(models.StrengthSet.workout_exercise_id == wex_id)
    )
    await db.delete(wex)
    await db.commit()
    await db.refresh(w)
    return await _hydrate_workout(db, w)


@router.post("/workout-exercises/{wex_id}/swap", response_model=WorkoutExerciseOut)
async def swap_exercise(
    wex_id: int, body: SwapBody,
    db: AsyncSession = Depends(get_session),
) -> WorkoutExerciseOut:
    """Replace one exercise within an in-progress / planned workout.

    Refuses (409) if any non-skipped sets have already been logged for
    this slot — the actuals belong to the original exercise and would
    be misleading attached to a different one. Caller should delete
    the offending sets first if they really want to swap mid-session.

    Preserves order_index, superset_id, target_sets/reps_low/reps_high,
    target_rest_s. Recomputes target_weight_lb for the new exercise from
    its starting-weight table (history-driven progression kicks in next
    session)."""
    if body.exercise_id not in _CATALOG_BY_ID:
        raise HTTPException(status_code=404, detail="exercise not found")

    wex = await db.get(models.StrengthWorkoutExercise, wex_id)
    if wex is None:
        raise HTTPException(status_code=404, detail="workout_exercise not found")

    # Refuse if sets are logged (excluding skipped placeholders)
    logged = (await db.execute(
        select(models.StrengthSet.id)
        .where(models.StrengthSet.workout_exercise_id == wex_id)
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.actual_reps.is_not(None))
    )).scalars().all()
    if logged:
        raise HTTPException(
            status_code=409,
            detail="cannot swap — sets already logged for this slot. "
                   "Delete the logged sets first.",
        )

    new_ex = _CATALOG_BY_ID[body.exercise_id]
    equip = await _equipment_payload(db)
    level = (equip.get("training") or {}).get("level", "intermediate")
    pairs = (equip.get("dumbbells") or {}).get("pairs_lb") or []
    wrist = equip.get("wrist_weights_lb") or []

    # Recompute target weight from history (if any) or starting table.
    # Swap keeps the slot's existing rep range, so we use the weight-only
    # policy here; double progression lives in full plan generation.
    avg_rating, avg_weight, _avg_reps = await strength_algo.last_target_weight_for_exercise(
        db, body.exercise_id,
    )
    if avg_rating is not None and avg_weight is not None:
        target = strength_algo.progress_from_rating(
            avg_weight, avg_rating, new_ex["is_compound"],
        )
    else:
        target = strength_algo.starting_weight_lb(new_ex["movement_pattern"], level)

    if target is not None and "dumbbell" in new_ex["equipment"]:
        target = strength_algo.round_weight(target, pairs, wrist)
    if "dumbbell" not in new_ex["equipment"]:
        target = None

    wex.exercise_id = body.exercise_id
    wex.target_weight_lb = target
    await db.commit()
    await db.refresh(wex)

    sets = (await db.execute(
        select(models.StrengthSet)
        .where(models.StrengthSet.workout_exercise_id == wex.id)
    )).scalars().all()
    return _wex_to_out(wex, sets, pairs, wrist)


@router.delete("/sets/{set_id}", status_code=204)
async def delete_set(
    set_id: int, db: AsyncSession = Depends(get_session)
) -> None:
    s = await db.get(models.StrengthSet, set_id)
    if s is None:
        raise HTTPException(status_code=404, detail="set not found")
    await db.delete(s)
    await db.commit()


# ------------------------------------------------------------------
# Today's plan — generates if missing, returns existing otherwise
# ------------------------------------------------------------------

async def _equipment_payload(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(models.UserEquipment, 1)
    if row is None:
        return EquipmentPayload().model_dump()
    return row.payload


async def _existing_workout_for(
    db: AsyncSession, target_date: date
) -> models.StrengthWorkout | None:
    """The most recent live workout for that date. Excludes 'regenerated'
    rows (those are kept around only to bump the regen seed counter)."""
    return (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == target_date)
        .where(models.StrengthWorkout.status != "regenerated")
        .order_by(models.StrengthWorkout.generated_at.desc())
        .limit(1)
    )).scalar_one_or_none()


@router.get("/today", response_model=WorkoutOut | None)
async def get_today(
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut | None:
    """Today's planned workout. Generates a new one if none exists yet.

    If a workout already exists for today (planned, in_progress, or
    completed), returns it as-is — the caller uses POST /today/regenerate
    to bump the seed and rebuild.
    """
    today = _local_today()
    # Sweep past-dated planned/in_progress rows to skipped. Idempotent.
    await strength_algo.auto_skip_stale_workouts(db, today)
    existing = await _existing_workout_for(db, today)
    if existing is not None:
        return await _hydrate_workout(db, existing)

    equipment = await _equipment_payload(db)
    profile = await db.get(models.UserProfile, 1)
    plan = await strength_algo.generate_plan(db, today, equipment, profile)
    if plan.rest_day_recommended:
        # Don't persist a "rest" row — the absence of a planned workout
        # plus the rest_day flag in the response tells the UI to render
        # a rest-day card. Re-call regenerates if the user wants to push.
        return None
    workout = await strength_algo.persist_plan(db, plan, today)
    return await _hydrate_workout(db, workout)


@router.get("/stats")
async def strength_stats(
    days: int = 90,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Aggregate strength stats over the last `days` days. Used by phone
    + web chart panels. No external deps beyond strength_sets."""
    from datetime import date as _date, timedelta as _td
    # CONS-1: the user's LOCAL today. Deriving the window from the UTC
    # date shifts it forward every evening after 7pm Central, so the
    # "last 90 days" chart silently starts a day late.
    since = _local_today() - _td(days=days)

    # Pull every logged set in window with its parent workout date + exercise id.
    sets_q = await db.execute(
        select(
            models.StrengthWorkout.date,
            models.StrengthWorkoutExercise.exercise_id,
            models.StrengthSet.set_number,
            models.StrengthSet.actual_weight_lb,
            models.StrengthSet.actual_reps,
            models.StrengthSet.rating,
            models.StrengthSet.skipped,
            models.StrengthSet.set_type,
        )
        .join(models.StrengthWorkoutExercise,
              models.StrengthSet.workout_exercise_id ==
              models.StrengthWorkoutExercise.id)
        .join(models.StrengthWorkout,
              models.StrengthWorkoutExercise.workout_id ==
              models.StrengthWorkout.id)
        .where(models.StrengthWorkout.date >= since)
        .order_by(models.StrengthWorkout.date)
    )
    rows = sets_q.all()

    # Daily volume + per-day set count.
    daily_vol: dict[str, float] = {}
    daily_sets: dict[str, int] = {}
    rpe_vals: list[float] = []
    per_muscle: dict[str, float] = {}
    progression: dict[str, list[dict[str, Any]]] = {}
    workout_dates: set[str] = set()

    for d, ex_id, _setn, w_lb, reps, rating, skipped, set_type in rows:
        if skipped or w_lb is None or reps is None or set_type == "warmup":
            continue
        date_iso = d.isoformat()
        workout_dates.add(date_iso)
        vol = float(w_lb) * float(reps)
        daily_vol[date_iso] = daily_vol.get(date_iso, 0.0) + vol
        daily_sets[date_iso] = daily_sets.get(date_iso, 0) + 1
        if rating is not None:
            rpe_vals.append(float(rating))

        # Muscle group from catalog
        meta = strength_algo.CATALOG_BY_ID.get(ex_id, {})
        muscle = meta.get("primary_muscle") or "other"
        per_muscle[muscle] = per_muscle.get(muscle, 0.0) + vol

        # Track top weight + top e1RM per (exercise, date) for the
        # progression series (e1RM-1). e1RM is the canonical strength signal;
        # a light warmup can't beat a working set's e1RM anyway.
        e1 = strength_algo.estimate_1rm(w_lb, reps) or 0.0
        prog = progression.setdefault(ex_id, [])
        existing = next((p for p in prog if p["date"] == date_iso), None)
        if existing is None:
            prog.append({"date": date_iso, "top_weight_lb": float(w_lb), "e1rm": e1})
        else:
            if float(w_lb) > existing["top_weight_lb"]:
                existing["top_weight_lb"] = float(w_lb)
            if e1 > existing.get("e1rm", 0.0):
                existing["e1rm"] = e1

    # Sort daily series by date for the line chart.
    daily = sorted(
        [{"date": k, "volume_lb": round(v, 1),
          "sets": daily_sets.get(k, 0)}
         for k, v in daily_vol.items()],
        key=lambda r: r["date"],
    )

    # Weight progression — keep top 8 exercises by total set count for chart UX.
    progression_by_count = sorted(
        progression.items(),
        key=lambda kv: -sum(1 for _ in kv[1]),
    )[:8]
    progression_out = {
        ex_id: sorted(pts, key=lambda r: r["date"])
        for ex_id, pts in progression_by_count
    }
    progression_names = {
        ex_id: strength_algo.CATALOG_BY_ID.get(ex_id, {}).get("name", ex_id)
        for ex_id in progression_out
    }

    # CONS-1: streaks and frequency over FULL history, not the selected
    # window. `workout_dates` above is bounded by `days`, so deriving a
    # streak from it would report a shorter streak whenever the user
    # narrowed the chart range — a number that moves with the date picker
    # is describing the picker.
    today_local = _local_today()
    all_dates = set((await db.execute(
        select(models.StrengthWorkout.date)
        .where(models.StrengthWorkout.status == "completed")
    )).scalars().all())
    streaks = consistency.compute_streaks(all_dates, today_local)

    # Already exists and is already correct — the planner uses it to pick a
    # focus. Surfacing it rather than re-deriving it in two clients.
    rested = await strength_algo.days_since_muscle_trained(db, today_local)

    return {
        "since": since.isoformat(),
        "days": days,
        "n_workouts": len(workout_dates),
        "n_sets": sum(daily_sets.values()),
        "total_volume_lb": round(sum(daily_vol.values()), 1),
        "rpe_avg": round(sum(rpe_vals) / len(rpe_vals), 2) if rpe_vals else None,
        "daily": daily,
        "per_muscle": [
            {"muscle": k, "volume_lb": round(v, 1)}
            for k, v in sorted(per_muscle.items(), key=lambda kv: -kv[1])
        ],
        "progression": progression_out,
        "progression_names": progression_names,
        "consistency": {
            "current_streak_days": streaks.current_days,
            "longest_streak_days": streaks.longest_days,
            "last_active": (
                streaks.last_active.isoformat() if streaks.last_active else None
            ),
            "today_pending": streaks.today_pending,
            "sessions_per_week_actual": consistency.sessions_per_week(
                all_dates, today_local, 28,
            ),
            "sessions_last_7d": consistency.count_in_window(all_dates, today_local, 7),
            "sessions_last_28d": consistency.count_in_window(all_dates, today_local, 28),
            "frequency_window_days": 28,
            # Days since each muscle last took a working set. 28 means
            # "not in the lookback window", i.e. maximally rested.
            "days_since_by_muscle": {
                k: round(v, 1) for k, v in sorted(rested.items(), key=lambda kv: -kv[1])
            },
        },
    }


@router.get("/volume-trend")
async def strength_volume_trend(
    weeks: int = 16,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """VOLT-1: total working-set volume per ISO week (Monday-anchored) over the
    last `weeks` weeks — the mesocycle load trend (accumulation / deload waves).
    Fixed window, independent of the /stats range picker. Uses the SAME volume
    formula as strength_stats.daily (weight*reps, skip warmup/skipped/NULL) so
    the weekly bars reconcile with the daily series on the same screen. The
    spine is zero-filled so rest weeks show as empty bars."""
    from datetime import date as _date, timedelta as _td
    weeks = max(1, min(52, int(weeks)))
    today = _local_today()
    this_monday = today - _td(days=today.weekday())
    since = this_monday - _td(days=(weeks - 1) * 7)

    rows = (await db.execute(
        select(
            models.StrengthWorkout.date,
            models.StrengthWorkout.id,
            models.StrengthSet.actual_weight_lb,
            models.StrengthSet.actual_reps,
            models.StrengthSet.skipped,
            models.StrengthSet.set_type,
        )
        .join(models.StrengthWorkoutExercise,
              models.StrengthSet.workout_exercise_id ==
              models.StrengthWorkoutExercise.id)
        .join(models.StrengthWorkout,
              models.StrengthWorkoutExercise.workout_id ==
              models.StrengthWorkout.id)
        .where(models.StrengthWorkout.date >= since)
    )).all()

    vol: dict[_date, float] = {}
    setc: dict[_date, int] = {}
    wkos: dict[_date, set] = {}
    for d, wid, w_lb, reps, skipped, set_type in rows:
        if skipped or w_lb is None or reps is None or set_type == "warmup":
            continue
        wk = d - _td(days=d.weekday())
        vol[wk] = vol.get(wk, 0.0) + float(w_lb) * float(reps)
        setc[wk] = setc.get(wk, 0) + 1
        wkos.setdefault(wk, set()).add(wid)

    trend: list[dict[str, Any]] = []
    wk = since
    while wk <= this_monday:
        trend.append({
            "week_start": wk.isoformat(),
            "volume_lb": round(vol.get(wk, 0.0), 1),
            "sets": setc.get(wk, 0),
            "workouts": len(wkos.get(wk, ())),
        })
        wk += _td(days=7)
    return {"weeks": weeks, "since": since.isoformat(), "trend": trend}


@router.get("/records")
async def strength_records(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """PR-1: per-exercise personal bests — heaviest working set + best e1RM,
    each with the date it was set, plus last-performed. Powers the Records
    card. Working sets only (warmups/skipped excluded)."""
    rows = (await db.execute(
        select(
            models.StrengthWorkout.date,
            models.StrengthWorkoutExercise.exercise_id,
            models.StrengthSet.actual_weight_lb,
            models.StrengthSet.actual_reps,
        )
        .join(models.StrengthWorkoutExercise,
              models.StrengthSet.workout_exercise_id == models.StrengthWorkoutExercise.id)
        .join(models.StrengthWorkout,
              models.StrengthWorkoutExercise.workout_id == models.StrengthWorkout.id)
        .where(models.StrengthSet.skipped.is_(False))
        .where(models.StrengthSet.actual_reps.is_not(None))
        .where(models.StrengthSet.actual_weight_lb.is_not(None))
        .where(models.StrengthSet.set_type != "warmup")
        # ASC + strict-> below means the FIRST date a max was hit wins ties,
        # so the reported PR date is deterministic and reads as "first achieved".
        .order_by(models.StrengthWorkout.date.asc())
    )).all()
    recs: dict[str, dict[str, Any]] = {}
    for d, ex_id, w, reps in rows:
        e1 = strength_algo.estimate_1rm(w, reps) or 0.0
        r = recs.setdefault(ex_id, {
            "best_weight_lb": 0.0, "best_weight_date": None,
            "best_e1rm": 0.0, "best_e1rm_date": None, "last_date": None})
        if float(w) > r["best_weight_lb"]:
            r["best_weight_lb"] = float(w); r["best_weight_date"] = d
        if e1 > r["best_e1rm"]:
            r["best_e1rm"] = e1; r["best_e1rm_date"] = d
        if r["last_date"] is None or d > r["last_date"]:
            r["last_date"] = d
    out = [{
        "exercise_id": ex_id,
        "name": strength_algo.CATALOG_BY_ID.get(ex_id, {}).get("name", ex_id),
        "best_weight_lb": round(r["best_weight_lb"], 1),
        "best_weight_date": r["best_weight_date"].isoformat() if r["best_weight_date"] else None,
        "best_e1rm": round(r["best_e1rm"], 1),
        "best_e1rm_date": r["best_e1rm_date"].isoformat() if r["best_e1rm_date"] else None,
        "last_performed_date": r["last_date"].isoformat() if r["last_date"] else None,
    } for ex_id, r in recs.items()]
    out.sort(key=lambda x: x["best_e1rm"], reverse=True)
    return {"records": out}


@router.get("/explain/{workout_id}")
async def explain_workout(
    workout_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Plain-English rationale for a generated workout. Pure rules-based —
    no Claude call, no daily limit. Explains: why this split, why these
    exercises, why these targets. The phone surfaces this behind a
    'Why this workout?' button on the workout header."""
    w = await db.get(models.StrengthWorkout, workout_id)
    if w is None:
        raise HTTPException(404, "workout not found")

    equip = await _equipment_payload(db)
    training = equip.get("training") or {}
    dpw = int(training.get("days_per_week", strength_algo.DEFAULT_DAYS_PER_WEEK))
    pref = training.get("split_preference", strength_algo.DEFAULT_SPLIT_PREFERENCE)
    level = training.get("level", strength_algo.DEFAULT_LEVEL)

    # Why this split?
    why_split = (
        f"Split: <strong>{w.split_focus}</strong>. "
        f"You're on a {dpw}-day {pref} rotation"
        f" ({level} progression). The selector picks today's focus to "
        "balance recovery and rotate through your week."
    )

    # Why these exercises? Look at slots + recent variety. We use the
    # planner's variety/anti-repeat heuristic — restate it conceptually.
    exercises = (await db.execute(
        select(models.StrengthWorkoutExercise)
        .where(models.StrengthWorkoutExercise.workout_id == workout_id)
        .order_by(models.StrengthWorkoutExercise.order_index)
    )).scalars().all()
    exercise_names = [
        strength_algo.CATALOG_BY_ID.get(
            e.exercise_id, {}).get("name", e.exercise_id) for e in exercises
    ]
    # TD-10 — the generator did not choose the ad-hoc slots, so it must not
    # take credit for them. Claiming to have reasoned its way to an exercise
    # the user added themselves is the sort of small dishonesty that makes
    # the whole explanation less trustworthy.
    generated = [
        e for e in exercises if not getattr(e, "added_ad_hoc", False)
    ]
    ad_hoc_names = [
        strength_algo.CATALOG_BY_ID.get(e.exercise_id, {}).get("name", e.exercise_id)
        for e in exercises if getattr(e, "added_ad_hoc", False)
    ]
    generated_names = [
        strength_algo.CATALOG_BY_ID.get(e.exercise_id, {}).get("name", e.exercise_id)
        for e in generated
    ]
    why_exercises = (
        f"Today's {len(generated_names)} planned exercises: "
        + ", ".join(generated_names[:5])
        + (f" + {len(generated_names) - 5} more" if len(generated_names) > 5 else "")
        + ". Picked from your equipment + favorites; sets 2 weeks of variety "
        "so you're not repeating the same lifts every session."
    )
    if ad_hoc_names:
        why_exercises += (
            " You added "
            + ", ".join(ad_hoc_names)
            + " yourself — the weight came from your history, but the choice "
            "was yours, not the planner's."
        )

    # Why these targets? Pull last sets for these exercises; describe RPE-driven progression.
    last_top_set: dict[str, dict[str, Any]] = {}
    for ex in exercises:
        last_q = await db.execute(
            select(
                models.StrengthSet.actual_weight_lb,
                models.StrengthSet.actual_reps,
                models.StrengthSet.rating,
                models.StrengthWorkout.date,
            )
            .join(models.StrengthWorkoutExercise,
                  models.StrengthSet.workout_exercise_id ==
                  models.StrengthWorkoutExercise.id)
            .join(models.StrengthWorkout,
                  models.StrengthWorkoutExercise.workout_id ==
                  models.StrengthWorkout.id)
            .where(models.StrengthWorkoutExercise.exercise_id == ex.exercise_id)
            .where(models.StrengthWorkout.id != workout_id)
            .where(models.StrengthSet.actual_weight_lb.is_not(None))
            .order_by(models.StrengthWorkout.date.desc(),
                      models.StrengthSet.actual_weight_lb.desc())
            .limit(1)
        )
        row = last_q.first()
        if row is not None:
            last_top_set[ex.exercise_id] = {
                "weight_lb": row[0], "reps": row[1],
                "rpe": row[2], "date": row[3].isoformat(),
            }

    # Walk through any progressed exercises.
    bumps: list[str] = []
    for ex in exercises:
        prev = last_top_set.get(ex.exercise_id)
        if prev is None:
            continue
        prev_w = float(prev["weight_lb"])
        cur_w = float(ex.target_weight_lb or 0)
        if cur_w > prev_w + 0.1:
            rpe = prev["rpe"]
            rpe_note = (
                f" (last RPE {int(rpe)})" if rpe is not None else ""
            )
            name = strength_algo.CATALOG_BY_ID.get(
                ex.exercise_id, {}).get("name", ex.exercise_id)
            bumps.append(
                f"{name}: {prev_w:g} → {cur_w:g} lb{rpe_note}"
            )

    why_targets = (
        "Targets follow your RPE feedback: easy sessions (RPE ≤ 7) bump "
        "weight via micro-loaders so the next prescription lands closer "
        "to challenging-but-doable. Failed/RPE 9-10 sets pull back."
    )
    if bumps:
        why_targets += " This session: " + "; ".join(bumps[:4]) + "."

    return {
        "workout_id": workout_id,
        "split_focus": w.split_focus,
        "why_split": why_split,
        "why_exercises": why_exercises,
        "why_targets": why_targets,
    }


@router.get("/by-date/{date_iso}")
async def get_workout_by_date(
    date_iso: str,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the workout for a specific date.

    - Past or today: returns the persisted StrengthWorkout (hydrated) if
      one exists, else a 404.
    - Future: synthesises a preview using the same generator the
      /upcoming endpoint uses (but a single day, full plan with sets).
      Returns the WorkoutOut shape with id=-1 so callers can tell it's
      not persisted.
    """
    from datetime import date as _date
    try:
        d = _date.fromisoformat(date_iso)
    except ValueError as e:
        raise HTTPException(400, f"invalid date: {e}") from e
    today = _local_today()
    # Sweep stale planned rows before reading so a past date returns
    # status="skipped" rather than a stuck "planned".
    await strength_algo.auto_skip_stale_workouts(db, today)
    existing = await _existing_workout_for(db, d)
    if existing is not None:
        wo = await _hydrate_workout(db, existing)
        return wo.model_dump() if hasattr(wo, "model_dump") else wo
    if d < today:
        raise HTTPException(
            404, f"no workout recorded for {date_iso}",
        )
    # Future date — preview using the planner. Don't persist.
    equipment = await _equipment_payload(db)
    profile = await db.get(models.UserProfile, 1)
    plan = await strength_algo.generate_plan(db, d, equipment, profile)
    now_iso = datetime.now(timezone.utc).isoformat()
    if plan.rest_day_recommended:
        return {
            "id": -1,
            "date": d.isoformat(),
            "generated_at": now_iso,
            "split_focus": "rest",
            "status": "preview",
            "seed": "",
            "preview": True,
            "rest_day_recommended": True,
            "rest_day_reason": plan.rest_day_reason,
            "exercises": [],
        }
    return {
        "id": -1,
        "date": d.isoformat(),
        "generated_at": now_iso,
        "split_focus": plan.split_focus,
        "status": "preview",
        "seed": "",
        "preview": True,
        "rest_day_recommended": False,
        "exercises": [
            {
                "id": -1 - idx,
                "workout_id": -1,
                "exercise_id": ex.exercise_id,
                "order_index": idx,
                "target_sets": ex.target_sets,
                "target_reps_low": ex.target_reps_low,
                "target_reps_high": ex.target_reps_high,
                "target_weight_lb": ex.target_weight_lb,
                "target_rest_s": ex.target_rest_s,
                "superset_id": ex.superset_id,
                "sets": [],
            }
            for idx, ex in enumerate(plan.exercises)
        ],
    }


class RegenerateBody(BaseModel):
    force: bool = False  # bypass rest-day recommendation
    force_full_weight: bool = False  # ignore the recovery deload (use full load)


@router.post("/today/regenerate", response_model=WorkoutOut)
async def regenerate_today(
    body: RegenerateBody = RegenerateBody(),
    db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """Bump the seed and rebuild today's plan.

    Refuses if a workout for today is already in_progress or completed
    (don't blow away mid-session work). Pass force=true to override the
    rest-day recommendation.
    """
    today = _local_today()
    existing = await _existing_workout_for(db, today)
    if existing is not None and existing.status in ("in_progress", "completed"):
        raise HTTPException(
            status_code=409,
            detail=f"workout for {today} is already {existing.status}; "
                   f"won't overwrite",
        )

    # Count prior plans for today → use as regen seed
    regen = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == today)
    )).scalars().all()
    regen_count = len(regen)

    equipment = await _equipment_payload(db)
    profile = await db.get(models.UserProfile, 1)
    plan = await strength_algo.generate_plan(
        db, today, equipment, profile, regen_count=regen_count,
        force_no_rest=body.force, force_full_weight=body.force_full_weight,
    )

    if plan.rest_day_recommended and not body.force:
        raise HTTPException(
            status_code=409,
            detail={
                "rest_day_recommended": True,
                "reason": plan.rest_day_reason,
                "notes": plan.notes,
                "hint": "POST again with {'force': true} to generate anyway.",
            },
        )

    workout = await strength_algo.persist_plan(db, plan, today)
    return await _hydrate_workout(db, workout)


class SwapTypeBody(BaseModel):
    """Override today's plan as a different workout type.

    Used by /today/swap-type and the phone "ad-hoc workout" picker.
    `duration_minutes` and `difficulty` are honored when the user wants
    a one-off session (longer / shorter / harder) instead of the
    profile-default plan. `replace_completed` lets the caller stack a
    second session on top of an already-completed day (legs in the
    morning + yoga in the evening) — without it, the handler 409s to
    avoid clobbering a finished workout by accident."""
    type: Literal["strength", "yoga", "cardio"]
    # Optional split override for strength: push / pull / legs / etc.
    split: str | None = None
    # Optional length / intensity overrides for ad-hoc sessions.
    duration_minutes: int | None = None  # clamped 10-120 by the handler
    difficulty: Literal["easy", "normal", "hard"] | None = None
    replace_completed: bool = False


@router.post("/today/swap-type", response_model=WorkoutOut)
async def swap_today_type(
    body: SwapTypeBody, db: AsyncSession = Depends(get_session),
) -> WorkoutOut:
    """Replace today's plan with a different workout type. Marks any
    prior plan for today as regenerated (preserving sets that were
    already logged), then persists the new plan.

    - type=strength: re-runs the normal generator (auto-pick split or
      use `split`). Same shape as POST /today/regenerate force=true.
    - type=yoga: 5-pose mobility flow, 45 s holds, no weight.
    - type=cardio: a recommendation-card workout — no exercises, just a
      Z2 cardio prescription in the notes field that the UI surfaces.
    """
    today = _local_today()
    existing = await _existing_workout_for(db, today)
    if (existing is not None and existing.status == "completed"
            and not body.replace_completed):
        raise HTTPException(
            status_code=409,
            detail=f"today's workout already completed — finish or wait "
                   f"for tomorrow",
        )

    regen = (await db.execute(
        select(models.StrengthWorkout)
        .where(models.StrengthWorkout.date == today)
    )).scalars().all()
    regen_count = len(regen)

    equipment = await _equipment_payload(db)
    profile = await db.get(models.UserProfile, 1)

    duration = (
        max(10, min(120, body.duration_minutes))
        if body.duration_minutes is not None else None
    )
    if body.type == "strength":
        plan = await strength_algo.generate_plan(
            db, today, equipment, profile,
            regen_count=regen_count, force_no_rest=True,
            override_split=body.split,
            duration_minutes=duration,
            difficulty=body.difficulty,
        )
    elif body.type == "yoga":
        mob_hist = await strength_algo.recent_mobility_history(db)
        plan = strength_algo.build_yoga_plan(
            today, regen_count=regen_count, mobility_history=mob_hist,
            duration_minutes=duration,
            difficulty=body.difficulty,
        )
    else:  # cardio
        plan = strength_algo.build_cardio_plan(
            today, regen_count=regen_count,
            duration_minutes=duration,
            difficulty=body.difficulty,
            equipment=equipment,
        )

    workout = await strength_algo.persist_plan(db, plan, today)
    return await _hydrate_workout(db, workout)


@router.get("/muscle-volume")
async def get_muscle_volume(
    days: int = 7,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Weekly direct-set audit per primary muscle vs research-backed
    MEV / MAV targets (#WP-4). days=7 by default — clamp 1-28.

    Returns:
        {
          "window_days": 7,
          "muscles": {
            "chest":     {"sets": 12, "mev": 10, "mav": 20, "status": "in_range"},
            "biceps":    {"sets": 4,  "mev": 8,  "mav": 16, "status": "under"},
            ...
          }
        }

    status ∈ {"untrained","under","in_range","over"} drives UI colour.
    """
    days = max(1, min(28, int(days)))
    muscles = await strength_algo.weekly_muscle_volume(db, days=days)
    return {"window_days": days, "muscles": muscles}


@router.get("/recovery")
async def get_recovery(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Today's per-day recovery context (the inputs the planner reads).

    Useful for the UI to show "you're at recovery 42, that's why today's
    targets are 8% lighter than last week" without the user having to
    cross-reference daily_summary."""
    today = _local_today()
    profile = await db.get(models.UserProfile, 1)
    aware = profile is None or profile.strength_recovery_aware
    inputs = await strength_algo.read_recovery_inputs(db, today)
    blocked, reason = inputs.is_blocking()
    return {
        "date": today.isoformat(),
        "recovery_aware": aware,
        "recovery_score": inputs.recovery_score,
        "readiness_score": inputs.readiness_score,
        "sleep_h": inputs.sleep_h,
        "deload_factor": inputs.deload_factor() if aware else 1.0,
        "rest_day_recommended": blocked,
        "rest_day_reason": reason,
    }
