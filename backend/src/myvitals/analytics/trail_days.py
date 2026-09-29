"""Trail status per local day — what was rideable this morning, what flipped.

For each local day:

``open_at_0700`` / ``delayed_at_0700``
    Trails whose status in effect at 07:00 local was `open` / `delayed`.
    "In effect" means the latest snapshot at or before 07:00 — the poller
    only writes a snapshot when something changes (SA-C5), so a trail that
    has been open for a month has no snapshot this morning and is still
    open.
``known_at_0700``
    Trails with a status at 07:00 other than `unknown` / `pending`. The
    denominator for "share open": unknown is not closed, so it is left out
    rather than counted against the trails.
``total``
    Trails with any status at all at 07:00 (known or not).
``closures`` / ``reopenings``
    Status flips during the local day (00:00–24:00) into `closed` / into
    `open`, from the trail's previous KNOWN status. `unknown` / `pending`
    readings are skipped when looking for the previous status, so
    open → unknown → closed is one closure and closed → unknown → closed is
    none. A trail's first-ever sighting is not a flip.

Cost: three small queries. The latest status per trail before the window
(an index lookup per trail on `(trail_id, fetched_at)`), and the snapshots
inside the window collapsed in the database to the rows where a trail's
status actually changed — older history has one row per trail per poll,
so this is the difference between hundreds of thousands of rows and a
few hundred.
"""
from __future__ import annotations

import bisect
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

MAX_RANGE_DAYS = 400

#: Local clock time the morning status is read at.
MORNING = time(hour=7)

#: Statuses that say nothing about the trail. Excluded from `known`.
UNKNOWN_STATUSES = frozenset({"unknown", "pending"})


def _is_known(status: str | None) -> bool:
    return status is not None and status not in UNKNOWN_STATUSES


def build_trail_days(
    since: date,
    until: date,
    tz: tzinfo,
    seeds: dict[int, tuple[str | None, str | None]],
    changes: Iterable[tuple[int, datetime, str]],
    today: date,
) -> list[dict[str, Any]]:
    """One row per local day in [since, until], oldest first.

    `seeds` maps trail_id → (latest status before the window, latest KNOWN
    status before the window), either None when there was none. `changes`
    are (trail_id, fetched_at, status) snapshots inside the window; they
    may include repeats of the same status (only a change counts).
    """
    per_trail: dict[int, list[tuple[datetime, str]]] = {}
    for tid, ts, status in changes:
        per_trail.setdefault(tid, []).append((ts, status))
    for events in per_trail.values():
        events.sort(key=lambda e: e[0])

    days: list[date] = []
    d = since
    while d <= until:
        days.append(d)
        d += timedelta(days=1)
    idx = {day: i for i, day in enumerate(days)}
    cutoffs = [datetime.combine(day, MORNING, tzinfo=tz) for day in days]

    open_n = [0] * len(days)
    delayed_n = [0] * len(days)
    known_n = [0] * len(days)
    total_n = [0] * len(days)
    closures = [0] * len(days)
    reopenings = [0] * len(days)

    for tid in set(seeds) | set(per_trail):
        seed_any, seed_known = seeds.get(tid, (None, None))
        events = per_trail.get(tid, [])
        times = [ts for ts, _ in events]

        # Morning status: latest reading at or before 07:00, else the seed.
        for i, cutoff in enumerate(cutoffs):
            j = bisect.bisect_right(times, cutoff) - 1
            status = events[j][1] if j >= 0 else seed_any
            if status is None:
                continue
            total_n[i] += 1
            if _is_known(status):
                known_n[i] += 1
            if status == "open":
                open_n[i] += 1
            elif status == "delayed":
                delayed_n[i] += 1

        # Flips, against the previous KNOWN status.
        last_known = seed_known
        for ts, status in events:
            if not _is_known(status):
                continue
            if last_known is not None and status != last_known:
                i = idx.get(ts.astimezone(tz).date())
                if i is not None:
                    if status == "closed":
                        closures[i] += 1
                    elif status == "open":
                        reopenings[i] += 1
            last_known = status

    return [
        {
            "date": day.isoformat(),
            "in_progress": day == today,
            "open_at_0700": open_n[i],
            "delayed_at_0700": delayed_n[i],
            "known_at_0700": known_n[i],
            "total": total_n[i],
            "closures": closures[i],
            "reopenings": reopenings[i],
        }
        for i, day in enumerate(days)
    ]


def _latest_before(start: datetime, known_only: bool):
    """Correlated subquery: a trail's latest status before `start`."""
    snap = models.TrailStatusSnapshot
    q = (
        select(snap.status)
        .where(snap.trail_id == models.Trail.id)
        .where(snap.fetched_at < start)
    )
    if known_only:
        q = q.where(snap.status.not_in(tuple(UNKNOWN_STATUSES)))
    return q.order_by(snap.fetched_at.desc()).limit(1).scalar_subquery()


def seeds_stmt(start: datetime):
    # Status-board trails only: an OSM trail row (no DNIS, migration 0070)
    # has no status and would count as a permanently-unknown trail in
    # every day's total.
    return select(
        models.Trail.id,
        _latest_before(start, known_only=False),
        _latest_before(start, known_only=True),
    ).where(models.Trail.dnis.is_not(None))


def changes_stmt(start: datetime, end: datetime):
    """In-window snapshots, keeping only rows where the status differs from
    the trail's previous in-window row (the first row per trail is kept)."""
    snap = models.TrailStatusSnapshot
    prev = func.lag(snap.status).over(
        partition_by=snap.trail_id, order_by=snap.fetched_at,
    ).label("prev")
    windowed = (
        select(snap.trail_id, snap.fetched_at, snap.status, prev)
        .where(snap.fetched_at >= start)
        .where(snap.fetched_at < end)
        .subquery("w")
    )
    return (
        select(windowed.c.trail_id, windowed.c.fetched_at, windowed.c.status)
        .where(
            windowed.c.prev.is_(None)
            | and_(windowed.c.prev.is_not(None), windowed.c.prev != windowed.c.status)
        )
        .order_by(windowed.c.trail_id, windowed.c.fetched_at)
    )


async def trail_days(
    db: AsyncSession, since: date, until: date, tz: tzinfo, today: date,
) -> list[dict[str, Any]]:
    start = datetime.combine(since, time.min, tzinfo=tz)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=tz)
    seeds = {
        tid: (last_any, last_known)
        for tid, last_any, last_known in (await db.execute(seeds_stmt(start))).all()
    }
    changes = (await db.execute(changes_stmt(start, end))).all()
    return build_trail_days(since, until, tz, seeds, changes, today)
