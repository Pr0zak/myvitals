"""Sleep score: 0-100 based on duration + deep/REM proportion.

Heuristic — useful as a personal trend signal, not a clinical metric.

SA-N3: the deep/REM term below is NOT a validated sleep-quality or
recovery signal — don't caption it "quality" anywhere new. Measured
against production: with IDEAL_DEEP_REM_PCT=0.30 the term saturates at
100 on ~90% of real nights (this user's deep+REM average sits above the
anchor), so the blended score correlates at r=-0.89 with how far
duration sits from 8h and only weakly with the architecture split it's
supposed to add. Same-night deep sleep also barely predicts next-day
HRV here (r=0.15, n=432) — there's no measured basis for treating deep/
REM share as a recovery forecast. Every caller of `sleep_score` should
present it as what it is: a duration-led sleep score. See
docs/sa-findings.json SA-N3 for the full measurement; the computation
itself is deliberately unchanged (this is a stored daily_summary column
read by Compare, Insights and five AI payloads — a formula change needs
a backfill plan, not a single-finding patch).
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

# Targets — tweak based on what feels right in production.
IDEAL_HOURS = 8.0
HOURS_PENALTY = 15.0          # per hour off ideal
IDEAL_DEEP_REM_PCT = 0.30     # combined deep + REM


def _night_window(day: date) -> tuple[datetime, datetime]:
    """The 18:00→14:00 UTC window for the night ending on `day`.

    Pulled out of `_stages_for_night` (SA-N2) so callers that need to know
    which day a raw sample's night belongs to — without wanting the full
    stage/session query — can attribute it the same way this module does,
    instead of re-deriving these hours a second time somewhere else.
    """
    start = datetime.combine(day - timedelta(days=1), time(hour=18), tzinfo=timezone.utc)
    end = datetime.combine(day, time(hour=14), tzinfo=timezone.utc)
    return start, end


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
    night_start, night_end = _night_window(day)

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
