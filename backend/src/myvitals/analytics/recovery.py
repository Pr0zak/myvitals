"""Recovery score: 0-100, anchored at 50 when HRV equals its 7-day baseline.

Heuristic, not medical-grade. Intent is a personal trend signal — "am I more
or less recovered than the past week" — rather than an absolute health score.

SA-N4 measured this score's day-to-day volatility (median absolute change
15.6-15.9 points against production, corroborating OG2-C1's independent
15.9-point measurement in TODO.md) and confirmed the CoachHub verdict built
on top of it flipped on the majority of consecutive days. The fix shipped
for SA-N4 was narrower than a rework of this function: the verdict was
re-thresholding this score in the frontend at numbers that disagreed with
`analytics/tiles.py`'s own 65/30 banding of the same number — see
`frontend/src/views/CoachHub.vue`'s `readTone`, now reading the tile's
`status` instead. This function's single-night-vs-7-day-mean computation is
UNCHANGED: a rolling-mean smoothing of the input (the way Garmin/Whoop/Oura
do it) would reduce the volatility, but per SA-N4's own report that is a
bigger, separately-scoped change — and no defensible smoothing constant for
it has been derived from this user's own data yet, the way `WEIGHT_NOISE_
BAND_KG` was for weight (GOAL-STATE). `recovery_score` also feeds the
strength planner's deload factor directly (`analytics/strength.py:
RecoveryInputs.deload_factor`) — smoothing it would move deload decisions
retroactively and needs its own dedicated look, not a side effect of a
verdict-display fix.
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
