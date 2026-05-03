"""Recovery score: 0-100, anchored at 50 when HRV equals its 7-day baseline.

Heuristic, not medical-grade. Intent is a personal trend signal — "am I more
or less recovered than the past week" — rather than an absolute health score.
"""
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from .baselines import nightly_hrv, rolling_baseline


async def recovery_score(db: AsyncSession, day: date) -> float | None:
    today_hrv = await nightly_hrv(db, day)
    baseline = await rolling_baseline(db, day, metric="hrv", window_days=7)

    if today_hrv is None or baseline is None or baseline <= 0:
        return None

    # Map deviation to a 0-100 scale: ±100% deviation hits the rails.
    deviation = (today_hrv - baseline) / baseline
    score = 50.0 + deviation * 50.0
    return max(0.0, min(100.0, score))
