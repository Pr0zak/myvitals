"""Per-tile statistics: value, trend, and whether that value is good.

The dashboards render a grid of bare numbers. "HRV 27 ms" is unreadable
without two extra facts: what YOUR normal is, and which way is better.
55 bpm is excellent resting HR and alarming max HR; 27 ms HRV is poor for
one person and a personal best for another.

Everything here is derived server-side per the architecture rule, so the
phone grid and the web grid cannot disagree. Clients render; they never
decide what counts as good.

Two threshold families, deliberately kept apart:

  * `baseline` — judged against the user's OWN trailing 28-day mean and
    standard deviation (HRV, resting HR). There is no population-normal
    worth applying here; the useful question is "is today unusual *for
    me*". Uses the same window and minimum-days floor as
    `readiness_breakdown`, so a tile and the readiness hero can never
    tell different stories about the same metric on the same day.

  * `target` — judged against a goal or a published reference range
    (steps, sleep duration, blood pressure). These have meaningful
    absolute values, and a personal baseline would be actively wrong:
    someone habitually sleeping five hours would have "typical" sleep
    scored as fine.

Metrics with no defensible direction (weight, skin-temperature delta)
report `neutral`: a trend and a delta, but no verdict. Inventing one
would mean guessing at a goal the user never set.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

# Matches `readiness_breakdown` exactly. If one changes, change both.
BASELINE_WINDOW_DAYS = 28
MIN_BASELINE_DAYS = 7

# Series length for the tile sparklines.
SERIES_DAYS = 14

KG_TO_LB = 2.2046226218

# Status vocabulary. Deliberately three plain words, not a clinical scale
# and not a score — a tile has room for one word.
GOOD, TYPICAL, WATCH = "good", "typical", "watch"

# How far from baseline before a metric stops being "typical". 1.0σ is
# about the 16th/84th percentile — frequent enough to be informative,
# rare enough that the grid isn't a wall of colour.
Z_NOTABLE = 1.0

# Half-width of the "your normal" band, as a fraction of baseline. Lives
# here rather than in each client: the band is a statement about what
# counts as normal for this user, which is a health judgement and belongs
# server-side. It was briefly duplicated in MetricCard.vue and
# MetricCard.kt, which is how two surfaces drift.
BAND_FRACTION = 0.08

# Past this, a carried-forward reading is reported but NOT judged. A
# verdict is a claim about how you are *now*; "your blood pressure is in
# the stage 1 range" off a two-month-old cuff reading is a claim the data
# can't support. The value and its date still show — only the verdict is
# withheld.
STALE_VERDICT_DAYS = 14


def _band_from_z(z: float, higher_is_better: bool) -> tuple[str, str]:
    """Status + a plain-language reason for a personal-baseline metric."""
    favourable = z if higher_is_better else -z
    sigma = f"{abs(z):.1f}σ"
    side = "above" if z > 0 else "below"
    if favourable >= Z_NOTABLE:
        return GOOD, f"{sigma} {side} your 28-day baseline"
    if favourable <= -Z_NOTABLE:
        return WATCH, f"{sigma} {side} your 28-day baseline"
    return TYPICAL, "in your usual range"


def bp_category(systolic: float, diastolic: float) -> tuple[str, str]:
    """AHA blood-pressure category for a reading.

    Tested HIGHEST category first. A reading falls in a category if EITHER
    number reaches it, so 139/92 is stage 2 on the diastolic even though the
    systolic alone would read as stage 1. Written as an ascending chain this
    is easy to get backwards — the first cut used `sys < 140 or dia < 90` for
    stage 1, which swallowed every stage 2 reading whose systolic happened to
    be under 140. That is exactly the live reading this shipped against.

    Tiers match `frontend/src/bp.ts`, which had this right already — the
    crisis tier (180+/120+) was missing here and would have reported a
    crisis-level reading as merely stage 2.

    These are published reference ranges, not a diagnosis; the range itself
    is echoed to the user so the tile shows its working.
    """
    if systolic >= 180 or diastolic >= 120:
        return WATCH, "hypertensive crisis range (180+ or 120+)"
    if systolic >= 140 or diastolic >= 90:
        return WATCH, "stage 2 range (140+ or 90+)"
    if systolic >= 130 or diastolic >= 80:
        return WATCH, "stage 1 range (130-139 or 80-89)"
    if systolic >= 120:
        return TYPICAL, "elevated range (120-129 over under 80)"
    return GOOD, "within the normal range (under 120/80)"


def suppress_stale_verdict(tile: dict[str, Any]) -> dict[str, Any]:
    """Strip the verdict from a tile whose reading is too old to judge.

    Mutates and returns `tile`. The value and `as_of` survive — only the
    status and its reason are replaced, because a status is a claim about
    the present and a months-old reading cannot support one.
    """
    sd = tile.get("stale_days")
    if sd is not None and sd > STALE_VERDICT_DAYS:
        # Drop the verdict if there was one...
        tile["status"] = None
        # ...and disclose the age either way. A `neutral` tile never had a
        # status to strip, so gating the message on one left weight showing
        # a 90-day-old weigh-in with nothing to say it wasn't today's.
        tile["status_reason"] = f"last reading {sd} days ago"
    return tile


def _pct_of_target(value: float, target: float) -> float:
    return (value / target * 100.0) if target else 0.0


async def _series(
    db: AsyncSession, column, day: date, days: int, scale: float = 1.0,
) -> list[dict[str, Any]]:
    """Trailing `days` of one daily_summary column, oldest first.

    Missing days are emitted as null rather than skipped — a gap must stay
    a gap in the sparkline, not silently close up and imply continuity that
    the data doesn't have.
    """
    since = day - timedelta(days=days - 1)
    rows = dict(
        (d, v) for d, v in (await db.execute(
            select(models.DailySummary.date, column)
            .where(models.DailySummary.date >= since)
            .where(models.DailySummary.date <= day)
        )).all()
    )
    out = []
    for i in range(days):
        d = since + timedelta(days=i)
        v = rows.get(d)
        out.append({
            "date": d.isoformat(),
            "value": (round(float(v) * scale, 2) if v is not None else None),
        })
    return out


async def _intermittent_series(
    db: AsyncSession, time_col, value_col, day: date, days: int,
    scale: float = 1.0,
) -> list[dict[str, Any]]:
    """Daily series for a metric that ISN'T measured every day.

    Weight and blood pressure come from their own tables, not from
    daily_summary — the nightly job leaves those columns null because you
    don't weigh yourself every morning. Days with no reading stay null, so
    the sparkline shows the real cadence of measurement rather than
    implying a daily habit that doesn't exist.
    """
    since = day - timedelta(days=days - 1)
    day_expr = func.date(time_col)
    rows = dict(
        (d, v) for d, v in (await db.execute(
            select(day_expr, func.avg(value_col))
            .where(func.date(time_col) >= since)
            .where(func.date(time_col) <= day)
            .where(value_col.is_not(None))
            .group_by(day_expr)
        )).all()
    )
    out = []
    for i in range(days):
        d = since + timedelta(days=i)
        v = rows.get(d)
        out.append({
            "date": d.isoformat(),
            "value": (round(float(v) * scale, 2) if v is not None else None),
        })
    return out


def _local_date(ts, day: date) -> date:
    """Calendar date of a timestamp in the user's timezone.

    Reading timestamps are tz-aware UTC while `day` arrives already resolved
    locally, so a bare `.date()` mixes zones: a cuff reading taken at 8pm
    Central lands on the next UTC day and its reported age is a day off.
    Third appearance of the UTC-vs-local trap here — see
    test_local_day_boundary.py.
    """
    if ts is None:
        return day
    if getattr(ts, "tzinfo", None) is None:
        return ts.date()
    try:
        from zoneinfo import ZoneInfo

        from ..config import settings
        local = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
        return ts.astimezone(local).date()
    except Exception:
        return ts.date()


async def tile_stats(
    db: AsyncSession, day: date, profile: Any | None = None,
    steps_override: int | None = None,
) -> list[dict[str, Any]]:
    """Every vital tile's number, trend and verdict for `day`.

    `day` must already be resolved in the user's local timezone by the
    caller — see the local-day note in `api/summary.py`.
    """
    row = await db.get(models.DailySummary, day)

    cutoff = day - timedelta(days=BASELINE_WINDOW_DAYS)
    bl = (await db.execute(
        select(
            func.avg(models.DailySummary.hrv_avg),
            func.stddev_pop(models.DailySummary.hrv_avg),
            func.count(models.DailySummary.hrv_avg),
            func.avg(models.DailySummary.resting_hr),
            func.stddev_pop(models.DailySummary.resting_hr),
            func.count(models.DailySummary.resting_hr),
        ).where(models.DailySummary.date >= cutoff)
         .where(models.DailySummary.date < day)
    )).first()
    hrv_mu, hrv_sd, hrv_n, rhr_mu, rhr_sd, rhr_n = bl or (None,) * 6

    extra = (getattr(profile, "extra", None) or {}) if profile else {}
    steps_goal = int(extra.get("steps_goal") or 10_000)
    sleep_target = float(getattr(profile, "sleep_target_h", None) or 8.0)

    tiles: list[dict[str, Any]] = []

    def add(**kw):
        # Explicit band bounds so no client has to know the rule.
        bl = kw.get("baseline")
        if bl is not None:
            spread = abs(bl) * BAND_FRACTION
            kw.setdefault("band_low", round(bl - spread, 2))
            kw.setdefault("band_high", round(bl + spread, 2))
        else:
            kw.setdefault("band_low", None)
            kw.setdefault("band_high", None)
        kw.setdefault("status", None)
        kw.setdefault("status_reason", None)
        kw.setdefault("delta", None)
        kw.setdefault("baseline", None)
        # Only intermittently-measured tiles carry these; present on every
        # tile so clients can read one shape instead of branching per key.
        kw.setdefault("as_of", None)
        kw.setdefault("stale_days", None)
        tiles.append(suppress_stale_verdict(kw))

    # ── personal-baseline metrics ────────────────────────────────────
    hrv = row.hrv_avg if row else None
    status = reason = None
    delta = z = None
    if hrv is not None and hrv_mu is not None:
        delta = round(hrv - float(hrv_mu), 1)
        if hrv_sd and float(hrv_sd) > 0 and (hrv_n or 0) >= MIN_BASELINE_DAYS:
            z = (hrv - float(hrv_mu)) / float(hrv_sd)
            status, reason = _band_from_z(z, higher_is_better=True)
    add(key="hrv", label="HRV", unit="ms",
        value=(round(hrv, 1) if hrv is not None else None),
        kind="baseline", higher_is_better=True,
        baseline=(round(float(hrv_mu), 1) if hrv_mu is not None else None),
        delta=delta, z=(round(z, 2) if z is not None else None),
        status=status, status_reason=reason,
        series=await _series(db, models.DailySummary.hrv_avg, day, SERIES_DAYS))

    rhr = row.resting_hr if row else None
    status = reason = None
    delta = z = None
    if rhr is not None and rhr_mu is not None:
        delta = round(rhr - float(rhr_mu), 1)
        if rhr_sd and float(rhr_sd) > 0 and (rhr_n or 0) >= MIN_BASELINE_DAYS:
            z = (rhr - float(rhr_mu)) / float(rhr_sd)
            status, reason = _band_from_z(z, higher_is_better=False)
    add(key="resting_hr", label="Resting HR", unit="bpm",
        value=(round(rhr, 1) if rhr is not None else None),
        kind="baseline", higher_is_better=False,
        baseline=(round(float(rhr_mu), 1) if rhr_mu is not None else None),
        delta=delta, z=(round(z, 2) if z is not None else None),
        status=status, status_reason=reason,
        series=await _series(db, models.DailySummary.resting_hr, day, SERIES_DAYS))

    # ── target metrics ───────────────────────────────────────────────
    # The stored column goes stale within the day — see live_steps_today.
    steps = steps_override if steps_override is not None else (
        row.steps_total if row else None
    )
    status = reason = None
    if steps is not None:
        pct = _pct_of_target(steps, steps_goal)
        if pct >= 100:
            status, reason = GOOD, f"goal of {steps_goal:,} met"
        elif pct >= 70:
            status, reason = TYPICAL, f"{pct:.0f}% of {steps_goal:,}"
        else:
            status, reason = WATCH, f"{pct:.0f}% of {steps_goal:,}"
    add(key="steps", label="Steps", unit="",
        value=(int(steps) if steps is not None else None),
        kind="target", higher_is_better=True, target=steps_goal,
        status=status, status_reason=reason,
        series=await _series(db, models.DailySummary.steps_total, day, SERIES_DAYS))

    sleep_s = row.sleep_duration_s if row else None
    sleep_h = round(sleep_s / 3600.0, 2) if sleep_s else None
    status = reason = None
    delta = None
    if sleep_h is not None:
        delta = round(sleep_h - sleep_target, 2)
        # A band, not a floor: oversleeping well past target is worth
        # flagging too, and "more is always better" is false for sleep.
        if sleep_h >= sleep_target - 0.5:
            status = GOOD if sleep_h <= sleep_target + 1.5 else TYPICAL
            reason = f"target {sleep_target:g} h"
        elif sleep_h >= sleep_target - 1.5:
            status, reason = TYPICAL, f"{abs(delta):.1f} h under target"
        else:
            status, reason = WATCH, f"{abs(delta):.1f} h under target"
    add(key="sleep_duration", label="Sleep", unit="h", value=sleep_h,
        kind="target", higher_is_better=True, target=sleep_target,
        delta=delta, status=status, status_reason=reason,
        series=await _series(
            db, models.DailySummary.sleep_duration_s, day, SERIES_DAYS,
            scale=1 / 3600.0))

    # Blood pressure against the published AHA category boundaries. These
    # are reference ranges, not a diagnosis — the exact range is echoed in
    # `status_reason` so the tile shows its working rather than asking the
    # user to trust a colour. Judged on the higher of the two categories,
    # since that is how the categories are defined.
    # Read from the cuff table, not daily_summary — the nightly job leaves
    # those columns null on days with no reading, which is most days.
    bp = (await db.execute(
        select(models.BloodPressure.systolic, models.BloodPressure.diastolic,
               models.BloodPressure.time)
        .order_by(models.BloodPressure.time.desc()).limit(1)
    )).first()
    sys_v = float(bp[0]) if bp else None
    dia_v = float(bp[1]) if bp else None
    bp_as_of = _local_date(bp[2], day) if bp else None
    status = reason = None
    if sys_v is not None and dia_v is not None:
        # Tested HIGHEST category first. A reading falls in a category if
        # EITHER number reaches it, so 139/92 is stage 2 on the diastolic
        # even though the systolic alone would read as stage 1. Written as
        # an ascending chain this is easy to get backwards — the first cut
        # used `sys < 140 or dia < 90` for stage 1, which swallowed every
        # stage 2 reading whose systolic happened to be under 140.
        status, reason = bp_category(sys_v, dia_v)
    add(key="blood_pressure", label="Blood pressure", unit="mmHg",
        value=(f"{sys_v:.0f}/{dia_v:.0f}"
               if sys_v is not None and dia_v is not None else None),
        kind="target", higher_is_better=False,
        status=status, status_reason=reason,
        as_of=(bp_as_of.isoformat() if bp_as_of else None),
        stale_days=((day - bp_as_of).days if bp_as_of else None),
        series=await _intermittent_series(
            db, models.BloodPressure.time, models.BloodPressure.systolic,
            day, SERIES_DAYS))

    # Recovery is already a 0-100 composite, so it carries its own scale —
    # banding it against a personal baseline would score a score.
    rec = row.recovery_score if row else None
    status = reason = None
    if rec is not None:
        if rec >= 65:
            status, reason = GOOD, "recovered"
        elif rec >= 30:
            status, reason = TYPICAL, "partially recovered"
        else:
            status, reason = WATCH, "under-recovered"
    add(key="recovery", label="Recovery", unit="",
        value=(round(rec) if rec is not None else None),
        kind="target", higher_is_better=True, target=100,
        status=status, status_reason=reason,
        series=await _series(db, models.DailySummary.recovery_score, day, SERIES_DAYS))

    # ── neutral metrics ──────────────────────────────────────────────
    # Weight has no universal good direction — it depends on a goal the
    # user may not have set. Report the trend and stay quiet about it.
    # Same carry-forward as `/summary/today`: show the latest weigh-in
    # rather than nothing on days without one. `as_of` / `stale_days` go
    # with it — presenting a three-week-old reading as today's number
    # without saying so is the kind of quiet lie a health app can't afford.
    wrow = (await db.execute(
        select(models.BodyMetric.weight_kg, models.BodyMetric.time)
        .where(models.BodyMetric.weight_kg.is_not(None))
        .order_by(models.BodyMetric.time.desc()).limit(1)
    )).first()
    wkg = float(wrow[0]) if wrow else None
    w_as_of = _local_date(wrow[1], day) if wrow else None
    add(key="weight", label="Weight", unit="lb",
        value=(round(wkg * KG_TO_LB, 1) if wkg is not None else None),
        kind="neutral", higher_is_better=None,
        as_of=(w_as_of.isoformat() if w_as_of else None),
        stale_days=((day - w_as_of).days if w_as_of else None),
        series=await _intermittent_series(
            db, models.BodyMetric.time, models.BodyMetric.weight_kg,
            day, SERIES_DAYS, scale=KG_TO_LB))

    return tiles
