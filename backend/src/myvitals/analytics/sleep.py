"""Sleep score: 0-100 based on duration + deep/REM proportion.

Heuristic — useful as a personal trend signal, not a clinical metric.
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

# Targets — tweak based on what feels right in production.
IDEAL_HOURS = 8.0
HOURS_PENALTY = 15.0          # per hour off ideal
IDEAL_DEEP_REM_PCT = 0.30     # combined deep + REM


async def _stages_for_night(db: AsyncSession, day: date) -> dict[str, int]:
    """Sum stage durations for the night ending on `day`.

    Prefer the canonical SleepSession boundary when one exists (HC /
    Fitbit / Garmin all ship session start+end). For a session, we sum
    stage durations only within the session window AND clamp each
    stage's duration to the gap before the next stage starts so
    overlapping rows from multiple imports don't inflate the night.

    Falls back to the older 20:00→12:00 window for nights without a
    canonical session row.
    """
    night_start = datetime.combine(day - timedelta(days=1), time(hour=18), tzinfo=timezone.utc)
    night_end = datetime.combine(day, time(hour=14), tzinfo=timezone.utc)

    # 1. Most relevant canonical session (one whose end falls in the night
    # window). Take the longest if multiple.
    sess = (await db.execute(
        select(models.SleepSession)
        .where(models.SleepSession.end_at >= night_start)
        .where(models.SleepSession.end_at <= night_end)
        .order_by((models.SleepSession.end_at - models.SleepSession.start_at).desc())
        .limit(1)
    )).scalar_one_or_none()
    if sess is not None:
        rows = (await db.execute(
            select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
            .where(models.SleepStage.time >= sess.start_at)
            .where(models.SleepStage.time <= sess.end_at)
            .order_by(models.SleepStage.time)
        )).all()
        by_stage: dict[str, int] = {}
        for i, (ts, stage, dur) in enumerate(rows):
            if i + 1 < len(rows):
                clamped = min(dur, max(0, int((rows[i + 1][0] - ts).total_seconds())))
            else:
                clamped = min(dur, max(0, int((sess.end_at - ts).total_seconds())))
            by_stage[stage] = by_stage.get(stage, 0) + clamped
        # If stages weren't tagged for this night, attribute the entire
        # session to "light" so duration is still right.
        if not by_stage:
            by_stage["light"] = int((sess.end_at - sess.start_at).total_seconds())
        return by_stage

    # 2. Fallback: stage-walk (overlap-clamped to be defensible).
    rows = (await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= night_start)
        .where(models.SleepStage.time <= night_end)
        .order_by(models.SleepStage.time)
    )).all()
    by_stage = {}
    for i, (ts, stage, dur) in enumerate(rows):
        if i + 1 < len(rows):
            clamped = min(dur, max(0, int((rows[i + 1][0] - ts).total_seconds())))
        else:
            clamped = dur
        by_stage[stage] = by_stage.get(stage, 0) + clamped
    return by_stage


async def sleep_score(db: AsyncSession, day: date) -> tuple[float | None, int | None]:
    """Returns (score 0-100, total_seconds_excluding_awake) for the night ending on `day`."""
    by_stage = await _stages_for_night(db, day)
    if not by_stage:
        return None, None

    asleep = sum(v for k, v in by_stage.items() if k != "awake")
    if asleep == 0:
        return None, None

    duration_hours = asleep / 3600.0
    duration_score = max(0.0, 100.0 - abs(duration_hours - IDEAL_HOURS) * HOURS_PENALTY)

    deep_rem = by_stage.get("deep", 0) + by_stage.get("rem", 0)
    quality_pct = deep_rem / asleep
    quality_score = min(100.0, 100.0 * (quality_pct / IDEAL_DEEP_REM_PCT))

    final = 0.6 * duration_score + 0.4 * quality_score
    return max(0.0, min(100.0, final)), asleep
