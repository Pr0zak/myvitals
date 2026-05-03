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
    """Sum stage durations for the night ending on `day`."""
    start = datetime.combine(day - timedelta(days=1), time(hour=20), tzinfo=timezone.utc)
    end = datetime.combine(day, time(hour=12), tzinfo=timezone.utc)
    result = await db.execute(
        select(models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= start)
        .where(models.SleepStage.time <= end)
    )
    by_stage: dict[str, int] = {}
    for stage, dur in result.all():
        by_stage[stage] = by_stage.get(stage, 0) + dur
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
