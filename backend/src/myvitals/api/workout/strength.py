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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...analytics import strength as strength_algo
from ...auth import require_any
from ...db import models
from ...db.session import get_session

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


class TrainingPreferences(BaseModel):
    """Settings the workout generator reads when picking today's plan.

    Stored as a sub-object inside user_equipment.payload to keep all
    strength configuration in one place. Pure JSON, no migration when
    adding fields here."""
    level: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    # 2-6 sessions per week — drives "auto" split selection
    days_per_week: int = 3
    split_preference: Literal["auto", "full_body", "upper_lower", "ppl"] = "auto"
    # Target session length in minutes (informational; not yet used by
    # the generator — placeholder for v0.8 progressive shortening logic)
    workout_minutes: int = 50


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
    notes: str | None
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
    exercises: list[WorkoutExerciseOut] = []


class WorkoutPatch(BaseModel):
    status: Literal["planned", "in_progress", "completed", "skipped"] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None


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
    )


def _wex_to_out(
    wex: models.StrengthWorkoutExercise, sets: list[models.StrengthSet]
) -> WorkoutExerciseOut:
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
        notes=wex.notes,
        sets=[_set_to_out(s) for s in sorted(sets, key=lambda x: x.set_number)],
    )


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
        exercises=[
            _wex_to_out(wex, sets_by_wex.get(wex.id, [])) for wex in wex_rows
        ],
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
            .group_by(models.StrengthWorkoutExercise.workout_id)
        )
        for wid, sets, reps, vol, rpe in agg.all():
            set_stats[wid] = {
                "set_count": int(sets or 0),
                "total_reps": int(reps or 0),
                "total_volume_lb": round(float(vol or 0), 1),
                "rpe_avg": round(float(rpe), 2) if rpe is not None else None,
            }

    # HR window per workout (only when both started_at + completed_at present)
    hr_stats: dict[int, dict[str, Any]] = {}
    for w in rows:
        if w.status != "completed" or w.started_at is None or w.completed_at is None:
            continue
        hr_q = await db.execute(
            select(
                func.avg(models.HeartRate.bpm).label("avg"),
                func.max(models.HeartRate.bpm).label("max"),
            )
            .where(models.HeartRate.time >= w.started_at)
            .where(models.HeartRate.time <= w.completed_at)
        )
        row = hr_q.first()
        if row and row[0] is not None:
            hr_stats[w.id] = {
                "avg_hr": round(float(row[0]), 1),
                "max_hr": round(float(row[1]), 1) if row[1] is not None else None,
            }

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
                **set_stats.get(w.id, {}),
                **hr_stats.get(w.id, {}),
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
    for field, value in data.items():
        setattr(w, field, value)
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

    # Auto-advance the parent workout to in_progress on the first logged set
    workout = await db.get(models.StrengthWorkout, wex.workout_id)
    if workout is not None and workout.status == "planned":
        workout.status = "in_progress"
        if workout.started_at is None:
            workout.started_at = logged_at

    await db.commit()
    await db.refresh(s)
    return _set_to_out(s)


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
    today = _date.today()
    last_split = await strength_algo.last_split_for_user(db)

    # Last completed workout date — drives the "skip the day after" logic.
    last_done_q = await db.execute(
        select(func.max(models.StrengthWorkout.date))
        .where(models.StrengthWorkout.status == "completed")
    )
    last_done = last_done_q.scalar()

    out: list[dict[str, Any]] = []
    cursor_split = last_split
    for offset in range(days + 1):
        d = today + _td(days=offset)
        # Mon-first index
        mon_first = (d.weekday())  # Python's weekday(): Mon=0..Sun=6 ✓
        if mon_first not in workout_dows:
            continue
        # Skip if the previous calendar day already had a completed workout.
        if last_done is not None and (d - last_done).days == 1:
            # Push this scheduled session back one day if possible.
            shifted = d + _td(days=1)
            shifted_mon = shifted.weekday()
            if shifted_mon not in workout_dows:
                # advance the rotation cursor as if we'd done it on `d`
                cursor_split = strength_algo.select_split(dpw, pref, cursor_split)
                # treat `d` as rest, inject `shifted` as the workout instead
                d = shifted
            else:
                # next day is already a workout day — leave both alone
                pass

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

    # Recompute target weight from history (if any) or starting table
    avg_rating, avg_weight = await strength_algo.last_target_weight_for_exercise(
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
    return _wex_to_out(wex, sets)


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
    today = datetime.now(timezone.utc).date()
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
    since = _date.today() - _td(days=days)

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

    for d, ex_id, _setn, w_lb, reps, rating, skipped in rows:
        if skipped or w_lb is None or reps is None:
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

        # Track top weight per (exercise, date) for weight-progression series
        prog = progression.setdefault(ex_id, [])
        existing = next((p for p in prog if p["date"] == date_iso), None)
        if existing is None:
            prog.append({"date": date_iso, "top_weight_lb": float(w_lb)})
        elif float(w_lb) > existing["top_weight_lb"]:
            existing["top_weight_lb"] = float(w_lb)

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
    }


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
    why_exercises = (
        f"Today's {len(exercise_names)} exercises: "
        + ", ".join(exercise_names[:5])
        + (f" + {len(exercise_names) - 5} more" if len(exercise_names) > 5 else "")
        + ". Picked from your equipment + favorites; sets 2 weeks of variety "
        "so you're not repeating the same lifts every session."
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
    today = _date.today()
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
    today = datetime.now(timezone.utc).date()
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
        force_no_rest=body.force,
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


@router.get("/recovery")
async def get_recovery(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Today's per-day recovery context (the inputs the planner reads).

    Useful for the UI to show "you're at recovery 42, that's why today's
    targets are 8% lighter than last week" without the user having to
    cross-reference daily_summary."""
    today = datetime.now(timezone.utc).date()
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
