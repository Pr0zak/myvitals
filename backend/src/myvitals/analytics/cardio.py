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

# Human labels for the five zones. Kept next to the bounds so the two cannot
# drift, and exported so no client has to carry its own copy -- both surfaces
# used to hard-code their own list, and they did not agree on the wording.
ZONE_LABELS: dict[str, str] = {
    "Z1": "Recovery",
    "Z2": "Endurance",
    "Z3": "Tempo",
    "Z4": "Threshold",
    "Z5": "VO2 Max",
}

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


async def resolve_max_hr(db: AsyncSession) -> tuple[float, str, int | None]:
    """The max HR to build zones from, plus where it came from.

    Returns ``(max_hr, source, age)`` where source is one of:

    ``profile``
        The user entered a measured maximum. Trust it.
    ``estimated``
        Tanaka (208 - 0.7 x age) from their birth date.
    ``default``
        No birth date either, so the age-40 fallback inside
        :func:`_estimated_max_hr` is doing the work. Every zone boundary
        downstream is then a guess built on a guess, which is worth saying
        out loud rather than presenting a chart as though it were measured.

    The provenance is not decoration. A zone distribution is only as
    meaningful as the maximum it is a percentage of, and the difference
    between a ramp-tested 186 and an assumed 180 moves the Z4/Z5 boundary by
    five beats -- enough to reclassify a whole session.
    """
    prof = await db.get(models.UserProfile, 1)
    if prof is None:
        return _estimated_max_hr(None), "default", None
    if prof.max_hr:
        return float(prof.max_hr), "profile", None
    age: int | None = None
    if prof.birth_date is not None:
        age = (datetime.now(timezone.utc).date() - prof.birth_date).days // 365
    return _estimated_max_hr(age), ("estimated" if age is not None else "default"), age


async def user_max_hr(db: AsyncSession) -> float:
    """Back-compat wrapper for callers that do not care about provenance."""
    value, _source, _age = await resolve_max_hr(db)
    return value


def zone_bounds(max_hr: float) -> list[dict[str, Any]]:
    """The five zones as absolute bpm ranges for a given maximum.

    This is the single definition of a zone boundary in the app. Both
    clients previously derived their own -- and disagreed with each other and
    with the server, because one of them was dividing by the *session's*
    observed peak HR rather than the user's physiological maximum, which
    makes an easy ride look like it was spent in Z4.
    """
    out: list[dict[str, Any]] = []
    for label, lo_pct, hi_pct in ZONE_BOUNDS_PCT:
        out.append({
            "zone": label,
            "label": ZONE_LABELS[label],
            "lo_pct": lo_pct,
            "hi_pct": None if hi_pct >= 2.0 else hi_pct,
            "lo_bpm": round(max_hr * lo_pct),
            "hi_bpm": None if hi_pct >= 2.0 else round(max_hr * hi_pct),
        })
    return out


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


async def activity_zone_detail(
    db: AsyncSession, activity: models.Activity, buckets: int = 50,
) -> dict[str, Any]:
    """Everything a client needs to render HR zones for one activity.

    Time-weighted seconds per zone from :func:`time_in_zone_for_activity`,
    the absolute bpm boundaries those zones correspond to, the provenance of
    the maximum they were derived from, and an optional bucketed series so a
    stacked area chart can show how the session moved between zones without
    the client classifying a single sample itself.

    ``sampled`` distinguishes the two very different cases that both produce
    numbers: a real per-second HR series, versus the coarse fallback where
    only ``avg_hr`` survived and the whole session is attributed to one zone.
    A client that cannot tell them apart will present a flat bar as though it
    were measured detail.
    """
    max_hr, source, age = await resolve_max_hr(db)
    tiz = await time_in_zone_for_activity(db, activity, max_hr)
    sampled = any(tiz.values())

    if not sampled and activity.avg_hr is not None:
        # Same fallback cardio_summary uses, so the per-activity view and the
        # rolling aggregate never disagree about a session with no series.
        tiz[zone_for(activity.avg_hr, max_hr)] = activity.duration_s

    total = sum(tiz.values())
    zones = []
    for spec in zone_bounds(max_hr):
        seconds = tiz.get(spec["zone"], 0)
        zones.append({
            **spec,
            "seconds": seconds,
            "pct": round(100.0 * seconds / total, 1) if total else 0.0,
        })

    series: list[dict[str, Any]] = []
    if sampled and buckets > 0 and activity.duration_s > 0:
        end_at = activity.start_at + timedelta(seconds=activity.duration_s)
        rows = (await db.execute(
            select(models.HeartRate.time, models.HeartRate.bpm)
            .where(models.HeartRate.time >= activity.start_at)
            .where(models.HeartRate.time <= end_at)
            .order_by(models.HeartRate.time)
        )).all()
        width_s = activity.duration_s / buckets
        grid = [{z: 0 for z, _, _ in ZONE_BOUNDS_PCT} for _ in range(buckets)]
        prev_ts = activity.start_at
        for ts, bpm in rows:
            # Same 30s gap cap as the totals, so the series sums back to the
            # zone seconds above rather than telling a second story.
            dt = min(max(0, int((ts - prev_ts).total_seconds())), 30)
            prev_ts = ts
            if dt == 0:
                continue
            offset = (ts - activity.start_at).total_seconds()
            idx = min(buckets - 1, max(0, int(offset / width_s)))
            grid[idx][zone_for(bpm, max_hr)] += dt
        series = [
            {"minute": round(i * width_s / 60, 1), **counts}
            for i, counts in enumerate(grid)
        ]

    return {
        "source": activity.source,
        "source_id": activity.source_id,
        "max_hr": round(max_hr),
        "max_hr_source": source,
        "age_used": age,
        "sampled": sampled,
        "total_seconds": total,
        "zones": zones,
        "series": series,
    }


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
