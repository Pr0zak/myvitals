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
    return float(val) if val is not None else None


async def nightly_hrv(db: AsyncSession, day: date) -> float | None:
    """Mean RMSSD during the sleep window for the night ending on `day`."""
    start, end = _night_window(day)
    result = await db.execute(
        select(func.avg(models.Hrv.rmssd_ms))
        .where(models.Hrv.time >= start)
        .where(models.Hrv.time <= end)
    )
    val = result.scalar()
    return float(val) if val is not None else None


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
