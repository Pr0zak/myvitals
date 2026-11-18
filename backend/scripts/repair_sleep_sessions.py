"""Give back the sleep that truncated sessions cut off, then recompute.

Until v0.54.2 ingest upserted sleep sessions with ON CONFLICT DO NOTHING on
`start_at`. The watch writes a session while the night is still going and
rewrites it later with a later end, so the first, shorter version won and
the rest of the night's stages were left outside every session. Measured on
2026-11-18: 37 nights from May to November 2026, up to 7.7 h each.

The stages themselves were stored, so the true end is recoverable. For each
stage outside every session, this extends the session that precedes it in
the same night, provided the stage starts within MAX_GAP of the session's
current end (counting the end of any stage that started inside it, since a
long "awake" stage can run past the stored end). It never extends a session
across the start of the next one. Stages with no such session are reported
and left alone: inventing a session from stages alone is a guess.

Then it recomputes daily_summary from --since to today, oldest first,
because training load seeds each day off the one before, and because
v0.54.2 also changed how a split night is counted (every session, not only
the longest), which affects nights this repair does not touch.

Dry run by default.

    docker compose exec -T backend python /app/scripts/repair_sleep_sessions.py
    docker compose exec -T backend python /app/scripts/repair_sleep_sessions.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, update

from myvitals.analytics.jobs import _local_tz, compute_daily_summary
from myvitals.analytics.sleep import _night_window
from myvitals.db import models
from myvitals.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("repair")

MAX_GAP = timedelta(hours=2)


def owning_night(t: datetime) -> date | None:
    """The day whose night window (sleep.py) contains `t`, if any."""
    for cand in (t.date(), t.date() + timedelta(days=1)):
        start, end = _night_window(cand)
        if start <= t <= end:
            return cand
    return None


def plan_extensions(
    sessions: list[tuple[datetime, datetime]],
    stages: list[tuple[datetime, str, int]],
    max_gap: timedelta = MAX_GAP,
) -> tuple[dict[datetime, datetime], list[tuple[datetime, str, int]]]:
    """Return ({session start: new end}, stages left unattached).

    Pure, so it can be tested without a database. `sessions` and `stages`
    are sorted by start time.
    """
    sessions = sorted(sessions)
    stored = {s: e for s, e in sessions}
    ends = dict(stored)
    # How far the stages already inside each session reach.
    reach = dict(ends)
    for ts, _stage, dur in stages:
        for s, _e in sessions:
            if s <= ts <= stored[s]:
                reach[s] = max(reach[s], ts + timedelta(seconds=dur))
                break

    new_end: dict[datetime, datetime] = {}
    orphans: list[tuple[datetime, str, int]] = []
    for ts, stage, dur in stages:
        # Judged against the STORED end: a stage that only falls inside after
        # an earlier extension must still push the end to its own finish.
        if any(s <= ts <= stored[s] for s, _ in sessions):
            continue
        before = [s for s, _ in sessions if s <= ts]
        if not before:
            orphans.append((ts, stage, dur))
            continue
        s = before[-1]
        night = owning_night(ts)
        if night is None or night != owning_night(stored[s]) or ts - reach[s] > max_gap:
            orphans.append((ts, stage, dur))
            continue
        later = [x for x, _ in sessions if x > s]
        stage_end = ts + timedelta(seconds=dur)
        if later:
            stage_end = min(stage_end, later[0])
        ends[s] = max(ends[s], stage_end)
        reach[s] = max(reach[s], stage_end)
        new_end[s] = ends[s]
    return new_end, orphans


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--since", type=date.fromisoformat, default=date(2026, 3, 1))
    args = ap.parse_args()

    async with SessionLocal() as db:
        since_ts = datetime.combine(args.since - timedelta(days=1), datetime.min.time(),
                                    tzinfo=_local_tz())
        sessions = (await db.execute(
            select(models.SleepSession.start_at, models.SleepSession.end_at)
            .where(models.SleepSession.end_at >= since_ts)
            .order_by(models.SleepSession.start_at)
        )).all()
        stages = (await db.execute(
            select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
            .where(models.SleepStage.time >= since_ts)
            .order_by(models.SleepStage.time)
        )).all()
        plan, orphans = plan_extensions([tuple(r) for r in sessions],
                                        [tuple(r) for r in stages])
        old = {s: e for s, e in sessions}
        for s, e in sorted(plan.items()):
            log.info("extend %s: end %s -> %s (+%.1f h)",
                     s.isoformat(), old[s].isoformat(), e.isoformat(),
                     (e - old[s]).total_seconds() / 3600)
        log.info("%d session(s) to extend; %d stage row(s) left unattached",
                 len(plan), len(orphans))
        for night in sorted({owning_night(t) for t, _, _ in orphans} - {None}):
            log.info("  unattached stages on night ending %s", night)

        if not args.apply:
            log.info("dry run; pass --apply to write and recompute")
            return
        for s, e in plan.items():
            await db.execute(
                update(models.SleepSession)
                .where(models.SleepSession.start_at == s)
                .where(models.SleepSession.end_at < e)
                .values(end_at=e)
            )
        await db.commit()

    today = datetime.now(_local_tz()).date()
    d = args.since
    n = 0
    while d <= today:
        try:
            await compute_daily_summary(d)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("recompute %s failed: %s", d, e)
        d += timedelta(days=1)
    log.info("recomputed %d day(s) from %s", n, args.since)


if __name__ == "__main__":
    asyncio.run(main())
