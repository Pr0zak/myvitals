"""Advanced derived analytics: readiness, training load, sleep consistency,
HR recovery, sleep debt. All run as part of compute_daily_summary so the
nightly job populates daily_summary in one transaction.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models


# ===== Readiness score (0-100, Whoop-style composite) ===============

async def readiness_score(
    db: AsyncSession, target: date, hrv: float | None,
    rhr: float | None, sleep_score: float | None,
    sleep_duration_s: int | None,
) -> float | None:
    """Composite of HRV, RHR, sleep — all relative to 28-day baselines."""
    # Pull 28-day baselines from daily_summary so we don't re-aggregate
    # raw vitals here.
    cutoff = target - timedelta(days=28)
    bl = (await db.execute(
        select(
            func.avg(models.DailySummary.hrv_avg),
            func.stddev_pop(models.DailySummary.hrv_avg),
            func.avg(models.DailySummary.resting_hr),
            func.stddev_pop(models.DailySummary.resting_hr),
        ).where(models.DailySummary.date >= cutoff)
         .where(models.DailySummary.date < target)
    )).first()
    if bl is None:
        return None
    hrv_mu, hrv_sd, rhr_mu, rhr_sd = bl

    parts: list[tuple[float, float]] = []  # (weight, score 0-100)

    if hrv is not None and hrv_mu and hrv_sd and hrv_sd > 0:
        # +1σ above baseline → 80, mean → 50, -1σ → 20.
        z = (hrv - float(hrv_mu)) / float(hrv_sd)
        parts.append((0.40, max(0.0, min(100.0, 50 + 30 * z))))
    if rhr is not None and rhr_mu and rhr_sd and rhr_sd > 0:
        z = (rhr - float(rhr_mu)) / float(rhr_sd)  # lower is better → invert
        parts.append((0.30, max(0.0, min(100.0, 50 - 30 * z))))
    if sleep_score is not None:
        parts.append((0.15, max(0.0, min(100.0, sleep_score))))
    if sleep_duration_s is not None:
        # 8h target; below 6h → 0, at/above 8h → 100, linear in between.
        h = sleep_duration_s / 3600.0
        parts.append((0.15, max(0.0, min(100.0, (h - 6.0) / 2.0 * 100))))

    if not parts:
        return None
    w_total = sum(w for w, _ in parts)
    return round(sum(w * s for w, s in parts) / w_total, 1)


# ===== Training load (TSS / CTL / ATL / TSB) ========================
#
# Banister model:
#   CTL_t = CTL_{t-1} + (TSS_t - CTL_{t-1}) / 42
#   ATL_t = ATL_{t-1} + (TSS_t - ATL_{t-1}) / 7
#   TSB_t = CTL_{t-1} - ATL_{t-1}   (yesterday's form, so today's race-day form)
# Daily TSS is roughly the sum of suffer_score across the day. Where suffer
# is null we fall back to (duration_min * intensity_factor) where IF is a
# heuristic per type.
TYPE_INTENSITY = {
    "ride": 0.7, "ebikeride": 0.5, "virtualride": 0.7,
    "run": 0.85, "trailrun": 0.85, "running": 0.85,
    "walk": 0.4, "walking": 0.4, "hike": 0.5, "hiking": 0.5,
    "swim": 0.75, "swimming_pool": 0.75, "swimming_open_water": 0.85,
    "strength": 0.6, "weightlifting": 0.6, "strength_training": 0.6,
    "yoga": 0.3, "pilates": 0.3,
    "indoor_cardio": 0.7, "indoor_rowing": 0.75, "rowing": 0.75,
    "cycling": 0.7, "mountain_biking": 0.85,
    "kayaking_v2": 0.6, "kayaking": 0.6,
}


async def daily_training_stress(
    db: AsyncSession, target: date,
) -> float | None:
    """Sum of suffer_score for the day, or duration*intensity fallback."""
    day_start = datetime.combine(target, time.min, tzinfo=timezone.utc)
    day_end = datetime.combine(target, time.max, tzinfo=timezone.utc)
    rows = (await db.execute(
        select(models.Activity.duration_s, models.Activity.suffer_score, models.Activity.type)
        .where(models.Activity.start_at >= day_start)
        .where(models.Activity.start_at <= day_end)
    )).all()
    if not rows:
        return None
    total = 0.0
    for dur_s, suffer, atype in rows:
        if suffer is not None and suffer > 0:
            total += float(suffer)
        elif dur_s:
            intensity = TYPE_INTENSITY.get(str(atype or "").lower(), 0.5)
            total += (dur_s / 60.0) * intensity
    return round(total, 1) if total > 0 else None


async def update_training_load(
    db: AsyncSession, target: date, tss_today: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Apply EWMA: CTL (42d), ATL (7d), TSB = CTL_yesterday - ATL_yesterday."""
    yesterday = target - timedelta(days=1)
    prev = (await db.execute(
        select(models.DailySummary.ctl, models.DailySummary.atl)
        .where(models.DailySummary.date == yesterday)
    )).first()
    prev_ctl = float(prev[0]) if prev and prev[0] is not None else 0.0
    prev_atl = float(prev[1]) if prev and prev[1] is not None else 0.0
    tss = float(tss_today or 0)
    ctl = prev_ctl + (tss - prev_ctl) / 42.0
    atl = prev_atl + (tss - prev_atl) / 7.0
    tsb = prev_ctl - prev_atl  # yesterday's form
    return round(ctl, 1), round(atl, 1), round(tsb, 1)


# ===== Sleep consistency score =====================================

async def sleep_consistency_score(
    db: AsyncSession, target: date, window_days: int = 14,
) -> float | None:
    """Score 0-100 based on stddev of sleep start + wake times over the window.

    σ=0 → 100, σ=120min → 0 (linear). Uses circular stats so a 23:30 bed
    time and a 00:30 bed time count as 1h apart, not 23h.
    """
    cutoff_start = datetime.combine(
        target - timedelta(days=window_days), time.min, tzinfo=timezone.utc,
    )
    cutoff_end = datetime.combine(target, time.max, tzinfo=timezone.utc)
    rows = (await db.execute(
        select(models.SleepStage.time, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= cutoff_start)
        .where(models.SleepStage.time <= cutoff_end)
        .order_by(models.SleepStage.time)
    )).all()
    if not rows:
        return None
    # Group into nightly sessions: any gap > 2h ends the prior night.
    sessions: list[tuple[datetime, datetime]] = []
    cur_start: datetime | None = None
    cur_last: datetime | None = None
    for ts, dur in rows:
        if cur_start is None:
            cur_start = ts; cur_last = ts + timedelta(seconds=dur)
            continue
        if ts - (cur_last or ts) > timedelta(hours=2):
            sessions.append((cur_start, cur_last or cur_start))
            cur_start = ts
        cur_last = ts + timedelta(seconds=dur)
    if cur_start and cur_last:
        sessions.append((cur_start, cur_last))
    if len(sessions) < 5:
        return None

    def _circ_std_minutes(times: list[datetime]) -> float:
        # Convert each time to angle (minute-of-day → radians), compute
        # circular standard deviation, return in minutes.
        sins = []; coss = []
        for t in times:
            mins = t.hour * 60 + t.minute
            ang = (mins / 1440.0) * 2 * math.pi
            sins.append(math.sin(ang)); coss.append(math.cos(ang))
        n = len(times)
        r = math.hypot(sum(sins) / n, sum(coss) / n)
        if r >= 1.0:
            return 0.0
        sigma_rad = math.sqrt(-2 * math.log(r))
        return sigma_rad / (2 * math.pi) * 1440.0

    starts = [s[0] for s in sessions]
    wakes = [s[1] for s in sessions]
    sigma_start = _circ_std_minutes(starts)
    sigma_wake = _circ_std_minutes(wakes)
    sigma = (sigma_start + sigma_wake) / 2
    # 0 σ = 100, 120 min σ = 0
    return round(max(0.0, min(100.0, 100 - sigma * 100 / 120)), 1)


# ===== Sleep debt (running deficit vs target) =======================

async def sleep_debt_hours(
    db: AsyncSession, target: date, target_h: float,
) -> float | None:
    """Cumulative deficit (target - actual) over the last 7 days.
    Positive = behind on sleep; negative = ahead."""
    cutoff = target - timedelta(days=6)
    rows = (await db.execute(
        select(models.DailySummary.sleep_duration_s)
        .where(models.DailySummary.date >= cutoff)
        .where(models.DailySummary.date <= target)
        .where(models.DailySummary.sleep_duration_s.is_not(None))
    )).all()
    if not rows:
        return None
    debt_h = 0.0
    for (s,) in rows:
        debt_h += target_h - (float(s) / 3600.0)
    return round(debt_h, 1)


# ===== Illness early warning composite =============================

async def illness_warning_signals(
    db: AsyncSession, target: date, *, rhr: float | None,
    hrv: float | None, recovery: float | None, skin_temp: float | None,
) -> dict[str, Any] | None:
    """Returns alert payload if 3+ of the four illness signals are true,
    None otherwise. Caller is responsible for inserting the Alert row."""
    cutoff = target - timedelta(days=28)
    bl = (await db.execute(
        select(
            func.avg(models.DailySummary.resting_hr),
            func.avg(models.DailySummary.hrv_avg),
            func.avg(models.DailySummary.skin_temp_delta_avg),
        ).where(models.DailySummary.date >= cutoff)
         .where(models.DailySummary.date < target)
    )).first()
    if bl is None:
        return None
    rhr_mu, hrv_mu, st_mu = (float(x) if x is not None else None for x in bl)
    signals: dict[str, Any] = {}
    if rhr is not None and rhr_mu is not None and (rhr - rhr_mu) >= 5:
        signals["rhr_elevated"] = {"current": rhr, "baseline": rhr_mu}
    if hrv is not None and hrv_mu is not None and hrv_mu > 0 and (hrv - hrv_mu) / hrv_mu <= -0.15:
        signals["hrv_suppressed"] = {"current": hrv, "baseline": hrv_mu}
    if skin_temp is not None and st_mu is not None and (skin_temp - st_mu) >= 0.4:
        signals["skin_temp_elevated"] = {"current": skin_temp, "baseline": st_mu}
    if recovery is not None and recovery < 60:
        signals["recovery_low"] = {"current": recovery}
    if len(signals) >= 3:
        return {
            "date": target.isoformat(), "signals": signals, "n_signals": len(signals),
        }
    return None


# ===== Per-activity HR recovery =====================================

async def compute_hr_recovery_for_activity(
    db: AsyncSession, source: str, source_id: str,
) -> tuple[float | None, float | None]:
    """Reads HR samples in the 3-minute window after activity end, finds the
    drop from peak (within last 60s of activity) at +60s and +120s."""
    act = (await db.execute(
        select(models.Activity.start_at, models.Activity.duration_s, models.Activity.max_hr)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )).first()
    if not act:
        return (None, None)
    start_at, dur_s, max_hr = act
    if not start_at or not dur_s or not max_hr:
        return (None, None)
    end_at = start_at + timedelta(seconds=dur_s)
    # Anchor "peak" as max HR in last 60s of activity (close to "end of effort").
    peak_window_start = end_at - timedelta(seconds=60)
    peak = (await db.execute(
        select(func.max(models.HeartRate.bpm))
        .where(models.HeartRate.time >= peak_window_start)
        .where(models.HeartRate.time <= end_at)
    )).scalar()
    if peak is None:
        peak = max_hr
    # Sample 60s and 120s post-end (±5s tolerance).
    async def hr_at(seconds_after: int) -> float | None:
        t_target = end_at + timedelta(seconds=seconds_after)
        v = (await db.execute(
            select(func.avg(models.HeartRate.bpm))
            .where(models.HeartRate.time >= t_target - timedelta(seconds=5))
            .where(models.HeartRate.time <= t_target + timedelta(seconds=5))
        )).scalar()
        return float(v) if v is not None else None
    hr60 = await hr_at(60)
    hr120 = await hr_at(120)
    rec_60 = float(peak) - hr60 if hr60 is not None else None
    rec_120 = float(peak) - hr120 if hr120 is not None else None
    return (rec_60, rec_120)
