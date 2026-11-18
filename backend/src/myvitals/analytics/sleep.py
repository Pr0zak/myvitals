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


def merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Union of possibly-overlapping (start, end) spans, sorted by start."""
    out: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def sum_stages_in(
    rows: list[tuple[datetime, str, int]],
    spans: list[tuple[datetime, datetime]],
) -> dict[str, int]:
    """Sum stage durations that fall inside `spans`.

    `rows` are (time, stage, duration_s) sorted by time. Each stage is
    clamped to the gap before the next stage starts (overlapping rows from
    multiple writers must not inflate the night) and to the end of the span
    it starts in. A stage starting outside every span is not counted.
    """
    by_stage: dict[str, int] = {}
    for i, (ts, stage, dur) in enumerate(rows):
        span = next((s for s in spans if s[0] <= ts <= s[1]), None)
        if span is None:
            continue
        limit = span[1]
        if i + 1 < len(rows) and rows[i + 1][0] < limit:
            limit = rows[i + 1][0]
        clamped = min(dur, max(0, int((limit - ts).total_seconds())))
        by_stage[stage] = by_stage.get(stage, 0) + clamped
    return by_stage


# How far a session may sit from the main sleep and still be the same night.
# Measured on production sessions March-November 2026: going back to sleep
# after waking left gaps of 2.3-3.5 h; the eleven afternoon/evening naps all
# ended 3.6 h or more before bedtime. Back-to-sleep gaps after the main
# session are therefore allowed up to 4 h; a session BEFORE it must sit
# within 2 h, which keeps every one of those naps out.
CHAIN_GAP_AFTER = timedelta(hours=4)
CHAIN_GAP_BEFORE = timedelta(hours=2)


def chain_night(
    sessions: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """The longest session plus every session chained to it, merged.

    Pure. A session joins when it starts within CHAIN_GAP_AFTER of the
    chain's end, or ends within CHAIN_GAP_BEFORE of the chain's start.
    """
    sessions = sorted((s, e) for s, e in sessions if e > s)
    if not sessions:
        return []
    anchor = max(sessions, key=lambda x: x[1] - x[0])
    chosen = [anchor]
    lo, hi = anchor
    for s, e in sessions:
        if s > anchor[0] and s - hi <= CHAIN_GAP_AFTER:
            chosen.append((s, e))
            hi = max(hi, e)
    for s, e in reversed(sessions):
        if s < anchor[0] and lo - e <= CHAIN_GAP_BEFORE:
            chosen.append((s, e))
            lo = min(lo, s)
    return merge_intervals(chosen)


async def night_session_spans(
    db: AsyncSession, day: date,
) -> list[tuple[datetime, datetime]]:
    """The canonical sessions that make up the night ending on `day`,
    merged into non-overlapping spans.

    The watch splits a broken night into several sessions. This used to
    keep only the LONGEST one, so the rest of the night counted for
    nothing: the night ending 2026-11-17 had sessions 04:06-08:51 and
    10:46-13:30 UTC and read 4.7 h, the second 2.7 h ignored. Taking every
    session in the window instead would sweep in afternoon naps, because
    the window opens at 18:00 UTC the day before; `chain_night` keeps only
    sessions close to the main sleep.
    """
    night_start, night_end = _night_window(day)
    sessions = (await db.execute(
        select(models.SleepSession.start_at, models.SleepSession.end_at)
        .where(models.SleepSession.end_at >= night_start)
        .where(models.SleepSession.end_at <= night_end)
    )).all()
    return chain_night([(s, e) for s, e in sessions])


async def _stages_for_night(db: AsyncSession, day: date) -> dict[str, int]:
    """Sum stage durations for the night ending on `day`.

    Prefer the canonical SleepSession boundaries when any exist (HC /
    Fitbit / Garmin all ship session start+end): stages are summed only
    inside the night's sessions (all of them, see `night_session_spans`),
    each clamped to the gap before the next stage starts so overlapping
    rows from multiple imports don't inflate the night.

    Falls back to the older 18:00 -> 14:00 UTC window for nights without a
    canonical session row.
    """
    spans = await night_session_spans(db, day)
    if spans:
        rows = (await db.execute(
            select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
            .where(models.SleepStage.time >= spans[0][0])
            .where(models.SleepStage.time <= spans[-1][1])
            .order_by(models.SleepStage.time)
        )).all()
        by_stage = sum_stages_in([tuple(r) for r in rows], spans)
        # If stages weren't tagged for this night, attribute the sessions
        # to "light" so duration is still right.
        if not by_stage:
            by_stage["light"] = int(sum((e - s).total_seconds() for s, e in spans))
        return by_stage

    # 2. Fallback: stage-walk (overlap-clamped to be defensible).
    night_start, night_end = _night_window(day)
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
