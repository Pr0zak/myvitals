"""Cardio HR-zone analytics. Used by the Coach AI cards and the
Insights surfaces. Pure math + DB reads — no AI side effects here.

Zones use percent-of-max-HR (simple model). HRR (Karvonen) would be
more accurate but requires resting HR which can be stale; %max is
robust to noise. Defaults:
  Z1: ≤60% max — recovery / warmup
  Z2: 60-70%  — aerobic / fat oxidation
  Z3: 70-80%  — tempo / threshold approach (the "grey zone")
  Z4: 80-90%  — VO2 / lactate threshold
  Z5: ≥90%    — anaerobic / max
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models


ZONE_BOUNDS_PCT: list[tuple[str, float, float]] = [
    ("Z1", 0.0, 0.60),
    ("Z2", 0.60, 0.70),
    ("Z3", 0.70, 0.80),
    ("Z4", 0.80, 0.90),
    ("Z5", 0.90, 2.0),   # 2.0 as upper sentinel
]

CARDIO_TYPES = {
    # Case-insensitive match — see _is_cardio. Strava-import path
    # writes lowercase slugs; older paths use TitleCase.
    "ride", "virtualride", "ebikeride", "mountainbikeride", "cycling",
    "run", "trailrun", "virtualrun", "running",
    "rowing", "rower", "rowingergometer", "indoor_rowing",
    "walk", "hike", "walking",
    "workout", "indoor_cardio",
    "swim", "swimming", "elliptical",
    "kayaking", "kayaking_v2",
}


def _is_cardio(t: str | None) -> bool:
    return bool(t) and t.lower().replace("-", "_") in CARDIO_TYPES


def _estimated_max_hr(age: int | None) -> float:
    """Tanaka formula (208 - 0.7*age) — newer than 220-age and a touch
    more accurate for older adults. Defaults to age 40 if unknown."""
    a = age if age is not None else 40
    return 208.0 - 0.7 * a


async def user_max_hr(db: AsyncSession) -> float:
    """Try profile.max_hr → age-estimate. Used by zone math."""
    prof = await db.get(models.UserProfile, 1)
    if prof is None:
        return _estimated_max_hr(None)
    # max_hr isn't on user_profile; estimate from birth_date.
    age: int | None = None
    if prof.birth_date is not None:
        age = (datetime.now(timezone.utc).date() - prof.birth_date).days // 365
    return _estimated_max_hr(age)


def zone_for(bpm: float, max_hr: float) -> str:
    pct = bpm / max_hr
    for label, lo, hi in ZONE_BOUNDS_PCT:
        if lo <= pct < hi:
            return label
    return "Z5"


async def time_in_zone_for_activity(
    db: AsyncSession, activity: models.Activity, max_hr: float,
) -> dict[str, int]:
    """Returns {Z1..Z5: seconds} for one activity by sampling HR series
    over [start_at, start_at + duration_s]. HR is sampled at the
    watch's native cadence (typically ≤5s); we treat each row as
    representing the seconds since the previous row's timestamp.
    """
    end_at = activity.start_at + timedelta(seconds=activity.duration_s)
    rows = (await db.execute(
        select(models.HeartRate.time, models.HeartRate.bpm)
        .where(models.HeartRate.time >= activity.start_at)
        .where(models.HeartRate.time <= end_at)
        .order_by(models.HeartRate.time)
    )).all()

    counts: dict[str, int] = {z[0]: 0 for z in ZONE_BOUNDS_PCT}
    if not rows:
        return counts

    prev_ts = activity.start_at
    for ts, bpm in rows:
        dt = max(0, int((ts - prev_ts).total_seconds()))
        # Cap large gaps at 30s to avoid attributing long stretches of
        # missing data to the zone we landed in afterwards.
        dt = min(dt, 30)
        z = zone_for(bpm, max_hr)
        counts[z] = counts[z] + dt
        prev_ts = ts
    return counts


async def cardio_summary(
    db: AsyncSession, days: int = 30,
) -> dict[str, Any]:
    """Time-in-zone aggregates over the last `days` of cardio activities.

    Returns:
      {
        max_hr: float,
        days: int,
        sessions: int,
        zone_minutes: {Z1: int, Z2: int, ..., Z5: int},
        polarized_ratio: float | None,   # (Z1+Z2) / (Z3+Z4+Z5)
        weekly_zone_minutes: list[{week_iso, Z1..Z5}],
        by_type: {type_name: {sessions, total_min, avg_hr_pct_max}},
      }
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    activities_all = (await db.execute(
        select(models.Activity)
        .where(models.Activity.start_at >= since)
        .order_by(models.Activity.start_at)
    )).scalars().all()
    activities = [a for a in activities_all if _is_cardio(a.type)]

    max_hr = await user_max_hr(db)

    zone_total: dict[str, int] = {z[0]: 0 for z in ZONE_BOUNDS_PCT}
    by_type: dict[str, dict[str, Any]] = {}
    weekly: dict[str, dict[str, int]] = {}

    for a in activities:
        # Time-in-zone for this activity.
        tiz = await time_in_zone_for_activity(db, a, max_hr)
        # Fallback: if no HR samples landed, use avg_hr × duration as
        # a coarse approximation (single bucket).
        if not any(tiz.values()) and a.avg_hr is not None:
            z = zone_for(a.avg_hr, max_hr)
            tiz[z] = a.duration_s
        for z, secs in tiz.items():
            zone_total[z] += secs
        # Bucket by ISO week.
        wk = a.start_at.isocalendar()
        wkey = f"{wk[0]}-W{wk[1]:02d}"
        weekly.setdefault(wkey, {z: 0 for z, _, _ in ZONE_BOUNDS_PCT})
        for z, secs in tiz.items():
            weekly[wkey][z] += secs
        # Per-type aggregates.
        t = a.type
        by_type.setdefault(t, {"sessions": 0, "total_min": 0, "avg_hr_pct_max": []})
        by_type[t]["sessions"] += 1
        by_type[t]["total_min"] += int(a.duration_s / 60)
        if a.avg_hr:
            by_type[t]["avg_hr_pct_max"].append(round(a.avg_hr / max_hr, 3))

    # Collapse avg_hr_pct_max lists into means.
    for t in by_type.values():
        vals = t["avg_hr_pct_max"]
        t["avg_hr_pct_max"] = round(sum(vals) / len(vals), 3) if vals else None

    zone_minutes = {z: round(s / 60) for z, s in zone_total.items()}
    easy = zone_minutes["Z1"] + zone_minutes["Z2"]
    hard = zone_minutes["Z3"] + zone_minutes["Z4"] + zone_minutes["Z5"]
    polarized_ratio = round(easy / hard, 2) if hard > 0 else None

    return {
        "max_hr": round(max_hr, 0),
        "days": days,
        "sessions": len(activities),
        "zone_minutes": zone_minutes,
        "polarized_ratio": polarized_ratio,
        "weekly_zone_minutes": [
            {"week": k, **{z: round(s / 60) for z, s in v.items()}}
            for k, v in sorted(weekly.items())
        ],
        "by_type": by_type,
    }
