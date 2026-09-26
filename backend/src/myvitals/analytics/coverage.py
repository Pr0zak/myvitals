"""Per-day data coverage — was a day measured, or only carried?

Answers the question every consumer of this data has to settle before
reading a value: is an absent or unchanged number a real "nothing
happened", or did the watch simply not record? Five facts per local day:

``hr_samples``
    Heart-rate samples that day (count).
``hr_wear_min``
    Distinct minutes with at least one HR sample (minutes). 0 means the
    watch recorded nothing — off the wrist, or not synced yet — not a
    resting day.
``main_session``
    The longest sleep session of at least ``MAIN_SESSION_MIN_S`` that ENDS
    on that local day, as ``{start, end, hours}``; null when there was none.
    Ending, not starting: a night belongs to the morning it ends on, the
    same attribution `daily_summary` uses.
``hrv_samples``
    HRV samples inside the main session, or — with no main session — inside
    the 22:00→09:00 local fallback night `analytics/baselines.py` uses.
``carried``
    `daily_summary` fields whose value is identical to the previous day's
    on a day with no main session. Those are not that day's measurements:
    the nightly computation reached back to the previous night. Listed so a
    consumer can drop them instead of charting yesterday twice.

Cost. `vitals_heartrate` is the one big table here (tens of millions of
rows). It is read once, bounded on `time` so TimescaleDB excludes every
chunk outside the window, and collapsed in the database — per minute, then
per local day — so at most one row per day crosses the wire. Everything
else is small: sleep sessions and HRV samples for the window, and one
`daily_summary` row per day.
"""
from __future__ import annotations

import bisect
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

#: Longest window one request may cover, in days.
MAX_RANGE_DAYS = 400

#: A sleep session shorter than this is a nap, not the night.
MAIN_SESSION_MIN_S = 3 * 3600

#: Nightly `daily_summary` fields checked for carry-forward. Each is
#: recomputed from the night that ends on the day, so an exact repeat on a
#: day with no night of its own is the previous night read twice. Fields
#: that legitimately persist (weight, body fat) or are decay-filled every
#: day (ctl/atl/tsb) are not in the list.
CARRY_FIELDS: tuple[str, ...] = (
    "resting_hr",
    "hrv_avg",
    "recovery_score",
    "readiness_score",
    "sleep_duration_s",
    "sleep_score",
    "sleep_debt_h",
    "sleep_consistency_score",
    "skin_temp_delta_avg",
)


def local_bounds(since: date, until: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[local midnight of `since`, local midnight after `until`)."""
    start = datetime.combine(since, time.min, tzinfo=tz)
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def hrv_night_window(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """22:00 the evening before → 09:00 on `day`, local.

    The same fallback window `analytics/baselines.py:_night_window` uses
    for a night with no canonical session, with the zone passed in rather
    than read from settings so the day-builder below stays pure.
    """
    start = datetime.combine(day - timedelta(days=1), time(hour=22), tzinfo=tz)
    end = datetime.combine(day, time(hour=9), tzinfo=tz)
    return start, end


def pick_main_sessions(
    sessions: Iterable[tuple[datetime, datetime]],
    tz: tzinfo,
    since: date,
    until: date,
) -> dict[date, tuple[datetime, datetime]]:
    """The longest session of at least MAIN_SESSION_MIN_S ending on each
    local day in [since, until]. Several sources can log the same night;
    the longest wins, and on a tie the one that ended later."""
    best: dict[date, tuple[datetime, datetime]] = {}
    for start, end in sessions:
        dur = (end - start).total_seconds()
        if dur < MAIN_SESSION_MIN_S:
            continue
        day = end.astimezone(tz).date()
        if day < since or day > until:
            continue
        cur = best.get(day)
        if cur is None or (dur, end) > ((cur[1] - cur[0]).total_seconds(), cur[1]):
            best[day] = (start, end)
    return best


def count_between(sorted_times: Sequence[datetime], lo: datetime, hi: datetime) -> int:
    """How many of `sorted_times` fall in [lo, hi]."""
    return bisect.bisect_right(sorted_times, hi) - bisect.bisect_left(sorted_times, lo)


def carried_fields(row: Any, prev: Any) -> list[str]:
    """CARRY_FIELDS whose value on `row` equals `prev`'s (both non-null)."""
    if row is None or prev is None:
        return []
    out: list[str] = []
    for f in CARRY_FIELDS:
        v = getattr(row, f, None)
        p = getattr(prev, f, None)
        if v is not None and p is not None and v == p:
            out.append(f)
    return out


def build_coverage(
    since: date,
    until: date,
    tz: tzinfo,
    hr_by_day: dict[date, tuple[int, int]],
    sessions: Iterable[tuple[datetime, datetime]],
    hrv_times: Sequence[datetime],
    summaries: dict[date, Any],
    today: date,
    night_window: Callable[[date, tzinfo], tuple[datetime, datetime]] = hrv_night_window,
) -> list[dict[str, Any]]:
    """One coverage row per local day in [since, until], oldest first.

    `hr_by_day` maps day → (hr_samples, hr_wear_min); `summaries` maps
    day → daily_summary row and should include the day before `since` so
    the first day's carry check has something to compare against.
    """
    mains = pick_main_sessions(sessions, tz, since, until)
    hrv_sorted = sorted(hrv_times)
    out: list[dict[str, Any]] = []
    day = since
    while day <= until:
        samples, wear = hr_by_day.get(day, (0, 0))
        main = mains.get(day)
        if main is not None:
            lo, hi = main
            session = {
                "start": main[0].astimezone(tz).isoformat(),
                "end": main[1].astimezone(tz).isoformat(),
                "hours": round((main[1] - main[0]).total_seconds() / 3600.0, 2),
            }
            carried: list[str] = []
        else:
            lo, hi = night_window(day, tz)
            session = None
            carried = carried_fields(summaries.get(day), summaries.get(day - timedelta(days=1)))
        out.append({
            "date": day.isoformat(),
            "in_progress": day == today,
            "hr_samples": int(samples),
            "hr_wear_min": int(wear),
            "main_session": session,
            "hrv_samples": count_between(hrv_sorted, lo, hi),
            "carried": carried,
        })
        day += timedelta(days=1)
    return out


def hr_by_day_stmt(start: datetime, end: datetime, tzname: str):
    """HR samples and worn minutes per local day, computed in the database.

    Inner query: one row per minute that has any sample, on a time-bounded
    scan — the bound is what lets TimescaleDB skip every chunk outside the
    window. Outer query: those minutes per local day. For a 400-day window
    that is at most ~576k minute groups in the database and 400 rows back
    to the app, however many raw samples there were.

    `time_bucket` rather than `date_trunc('minute', …)`: same minutes (UTC
    offsets are whole minutes), but it skips date_trunc's time-zone
    handling — measured ~28% faster over 400 days of ~2.5 s samples.
    """
    minute = func.time_bucket(timedelta(minutes=1), models.HeartRate.time).label("minute")
    per_minute = (
        select(minute, func.count().label("n"))
        .where(models.HeartRate.time >= start)
        .where(models.HeartRate.time < end)
        .group_by(minute)
        .subquery("per_minute")
    )
    local_day = cast(func.timezone(tzname, per_minute.c.minute), Date).label("day")
    return (
        select(local_day, func.sum(per_minute.c.n), func.count())
        .group_by(local_day)
    )


async def day_coverage(
    db: AsyncSession,
    since: date,
    until: date,
    tz: tzinfo,
    tzname: str,
    today: date,
) -> list[dict[str, Any]]:
    start, end = local_bounds(since, until, tz)

    hr_rows = (await db.execute(hr_by_day_stmt(start, end, tzname))).all()
    hr_by_day = {d: (int(n or 0), int(m or 0)) for d, n, m in hr_rows if d is not None}

    sessions = [
        (s, e) for s, e in (await db.execute(
            select(models.SleepSession.start_at, models.SleepSession.end_at)
            .where(models.SleepSession.end_at >= start)
            .where(models.SleepSession.end_at < end)
            .where(
                models.SleepSession.end_at - models.SleepSession.start_at
                >= timedelta(seconds=MAIN_SESSION_MIN_S)
            )
        )).all()
    ]

    # HRV only for the windows that will be counted: from the earliest
    # main-session start or the first fallback night, to the window's end.
    hrv_lo = min([s for s, _ in sessions] + [hrv_night_window(since, tz)[0]])
    hrv_times = list((await db.execute(
        select(models.Hrv.time)
        .where(models.Hrv.time >= hrv_lo)
        .where(models.Hrv.time <= end)
    )).scalars().all())

    rows = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since - timedelta(days=1))
        .where(models.DailySummary.date <= until)
    )).scalars().all()
    summaries = {r.date: r for r in rows}

    return build_coverage(
        since, until, tz, hr_by_day, sessions, hrv_times, summaries, today,
    )
