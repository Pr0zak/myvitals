"""Rolling baselines for resting HR and HRV.

These are intentionally simple and personal-scale — we're tracking single-user
trends, not building a population model. "Nightly" values use the 22:00 → 09:00
window of the night ending on the target date.
"""
from datetime import date, datetime, time, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models


def _night_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day - timedelta(days=1), time(hour=22), tzinfo=timezone.utc)
    end = datetime.combine(day, time(hour=9), tzinfo=timezone.utc)
    return start, end


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
    start, end = _night_window(day)
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
    start, end = _night_window(day)
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
