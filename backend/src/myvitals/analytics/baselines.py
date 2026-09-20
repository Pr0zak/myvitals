"""Rolling baselines for resting HR and HRV.

These are intentionally simple and personal-scale — we're tracking single-user
trends, not building a population model. "Nightly" values prefer the canonical
SleepSession boundary when one exists (HC / Fitbit / Garmin all ship session
start+end — the same pattern `sleep.py:_stages_for_night` already uses), and
fall back to a 22:00 → 09:00 clock window resolved in `settings.tz` for nights
without one.

SA-N1: that clock window used to be hard-coded `tzinfo=timezone.utc`, so on
this deployment (settings.tz = America/Chicago, UTC-5/6) the "night" actually
ran 17:00→04:00 local — five-plus hours of evening wakefulness folded in, the
last two-plus hours of real sleep cut off. Measured against the canonical
sleep session as ground truth: not a systematic bias (RHR bias -0.13 bpm,
mean -0.13; the ratios and z-scores downstream cancel a *proportional* window
bias exactly), but real per-night noise (RHR sd_diff 4.08 bpm, |diff|>=2bpm on
60/124 nights; HRV sd_diff 1.29, mean skewed -1.31 because the fallback window
draws in ~12 evening HRV samples/night it should not and misses ~24 real ones)
that inflates the 7-day rolling baseline's spread and damps recovery/readiness
rather than skewing them. See docs/sa-findings.json SA-N1 for the full
measurement.
"""
from datetime import date, datetime, time, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models


def _local_tz():
    """The user's configured timezone, falling back to UTC if unresolvable.

    Same self-contained pattern as `analytics/jobs.py:_local_tz` — duplicated
    rather than imported to avoid a `jobs.py` <-> `baselines.py` import cycle
    (`jobs.py` already imports from this module).
    """
    try:
        from zoneinfo import ZoneInfo

        from ..config import settings
        return ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:  # noqa: BLE001
        return timezone.utc


def _night_window(day: date) -> tuple[datetime, datetime]:
    """The 22:00→09:00 fallback window for the night ending on `day`,
    resolved in `settings.tz`.

    Pure and synchronous on purpose, mirroring `sleep.py:_night_window`
    (SA-N2's extraction of the same shape): a day-attribution bisector like
    `api/summary.py:_owning_days` needs a plain function of `day` alone, not
    a database round-trip, to place raw sample timestamps into calendar
    nights across a whole date range. `nightly_rhr` / `nightly_hrv` layer a
    DB-backed canonical-SleepSession preference on top of this
    (`_resolve_night_bounds`) for the value they actually compute; this
    function is what a night falls back to when there is no session to
    prefer.
    """
    local_tz = _local_tz()
    start = datetime.combine(day - timedelta(days=1), time(hour=22), tzinfo=local_tz)
    end = datetime.combine(day, time(hour=9), tzinfo=local_tz)
    return start, end


async def _resolve_night_bounds(db: AsyncSession, day: date) -> tuple[datetime, datetime]:
    """The night ending on `day`, for computing an actual RHR/HRV value.

    Prefers the canonical SleepSession boundary when one exists — mirrors
    `sleep.py:_stages_for_night`'s search (a generous local-day-plus-reach-back
    window used only to LOCATE the session; the session's own start_at/end_at,
    not this search window, become the actual RHR/HRV bounds). Falls back to
    `_night_window(day)` for nights without a canonical session row.
    """
    local_tz = _local_tz()
    day_start = datetime.combine(day, time.min, tzinfo=local_tz)
    day_end = datetime.combine(day, time.max, tzinfo=local_tz)
    search_start = day_start - timedelta(hours=18)

    sess = (await db.execute(
        select(models.SleepSession)
        .where(models.SleepSession.end_at >= search_start)
        .where(models.SleepSession.end_at <= day_end)
        .order_by((models.SleepSession.end_at - models.SleepSession.start_at).desc())
        .limit(1)
    )).scalar_one_or_none()
    if sess is not None:
        return sess.start_at, sess.end_at

    return _night_window(day)


async def nightly_rhr(db: AsyncSession, day: date) -> float | None:
    """Resting HR for the night ending on `day` — the lowest sustained HR
    during the sleep window, matching the Fitbit/Garmin convention.

    Implemented as the minimum of 5-minute bucket means. Taking the mean of
    the whole window (the pre-v0.7.348 behaviour) is NOT a resting HR: it
    folds in wake periods, sleep-onset, and REM spikes, and read 20-40 bpm
    high — e.g. 72 against a true overnight minimum of 53. That number feeds
    readiness_score / recovery_score and anything doing Karvonen zone math,
    so the bias was systematic, not cosmetic.

    Bucketing rather than a bare MIN() is deliberate: a single-sample floor
    tracks optical-sensor dropouts. Five minutes is long enough to require
    the low HR to be *sustained* and short enough to catch the true trough.
    """
    start, end = await _resolve_night_bounds(db, day)
    bucket = func.to_timestamp(
        func.floor(func.extract("epoch", models.HeartRate.time) / 300.0) * 300.0
    ).label("bucket")
    buckets = (
        select(func.avg(models.HeartRate.bpm).label("bpm"))
        .where(models.HeartRate.time >= start)
        .where(models.HeartRate.time <= end)
        .group_by(bucket)
        .subquery()
    )
    result = await db.execute(select(func.min(buckets.c.bpm)))
    val = result.scalar()
    if val is not None:
        return float(val)
    # GH-2 — fall back to Google's own daily resting HR when we hold no
    # samples for the night, which in practice means the phone was not
    # syncing. See _google_health_daily for why a measured value always wins.
    return await _google_health_daily(db, day, "resting_hr")


async def nightly_hrv(db: AsyncSession, day: date) -> float | None:
    """Mean RMSSD during the sleep window for the night ending on `day`."""
    start, end = await _resolve_night_bounds(db, day)
    result = await db.execute(
        select(func.avg(models.Hrv.rmssd_ms))
        .where(models.Hrv.time >= start)
        .where(models.Hrv.time <= end)
    )
    val = result.scalar()
    if val is not None:
        return float(val)
    return await _google_health_daily(db, day, "hrv_avg_ms")


async def _google_health_daily(
    db: AsyncSession, day: date, column: str,
) -> float | None:
    """GH-2 — Google's own daily figure for `day`, as a LAST RESORT.

    Reached only when the sample-derived computation above returned None,
    which in practice means the phone was not syncing that night. A measured
    value always wins: an aggregate Google computed from data we do not hold
    is better than a blank, and worse than our own arithmetic over the raw
    samples.

    Kept in its own table for exactly this reason. Writing these into
    daily_summary would have them clobbered by the next lazy recompute, and
    writing them into vitals_hrv would skew every average taken over a
    per-sample table with a single daily number.
    """
    try:
        row = await db.get(models.GoogleHealthDaily, day)
    except Exception:  # noqa: BLE001
        # Mid-rollout the app can run against a database that has not taken
        # migration 0053 yet. A missing table must degrade to "no fallback"
        # rather than break every daily summary at once.
        return None
    if row is None:
        return None
    value = getattr(row, column, None)
    return float(value) if value is not None else None


async def rolling_baseline(
    db: AsyncSession,
    day: date,
    metric: str,
    window_days: int = 7,
) -> float | None:
    """Median nightly value of `metric` over the past `window_days` nights, excluding `day`."""
    fn = nightly_rhr if metric == "rhr" else nightly_hrv
    values: list[float] = []
    for offset in range(1, window_days + 1):
        v = await fn(db, day - timedelta(days=offset))
        if v is not None:
            values.append(v)
    return median(values) if values else None
