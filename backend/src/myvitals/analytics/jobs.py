"""Nightly analytics job: writes a daily_summary row + emits health alerts."""
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Date, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models
from ..db.session import SessionLocal
from .advanced import (
    daily_training_stress, illness_warning_signals, readiness_score,
    sleep_consistency_score, sleep_debt_hours, update_training_load,
)
from .baselines import nightly_hrv, nightly_rhr, rolling_baseline
from .recovery import recovery_score
from .sleep import sleep_score

log = logging.getLogger(__name__)


# Keywords identifying a wrist-worn-device step source (Pixel Watch via
# Fitbit / Google Health, Wear OS wearable apps, Samsung wearable).
# When multiple sources cover a day, the watch wins — its count
# matches what the user sees on the wrist, and the phone pedometer
# ("android" source) tends to over-count when the phone moves in a
# pocket while walking.
#
# Includes "googlehealth" and "googlefit" for the May 2026 Fitbit →
# Google Health rebrand. HC source attribution post-rebrand still
# carries `com.fitbit.FitbitMobile` per Google's "no action required"
# messaging, but new HC step counter (June 2026 SPN switch) may emit
# a generic `com.google.android.apps.healthdata` source — keyword
# match catches that too.
_WATCH_SOURCE_KEYWORDS = (
    "wearable", "fit.wearable", "fitbit", "watch", "wear",
    "googlehealth", "googlefit", "healthdata",
)


def _is_watch_source(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _WATCH_SOURCE_KEYWORDS)


# A stored steps_total within this many steps of a fresh recount is treated
# as current. Zero tolerance would rebuild the whole daily_summary row on
# every read while the user is out walking; a generous one would let a
# materially wrong number stand. The errors this guards against ran to
# thousands of steps, so the exact figure is not delicate.
STEPS_STALE_TOLERANCE = 100


def steps_total_is_stale(stored: int | None, canonical: int | None) -> bool:
    """Is a stored `daily_summary.steps_total` behind a fresh recount?

    The one rule, shared by the single-day check and the batched range
    scan, so the two cannot answer differently for the same day.

    A canonical of None (no usable source) or 0 never marks the row stale:
    there is nothing to repair it WITH, and treating it as stale would
    rebuild the same row on every read forever.
    """
    if not canonical:
        return False
    return stored is None or abs(stored - canonical) > STEPS_STALE_TOLERANCE


def _pick_steps_source(totals: list[tuple[str, int]]) -> str | None:
    """The one source to trust, given each source's total for a window.

    Split out of `pick_canonical_steps_source` so the per-day scan in
    `canonical_steps_by_day` cannot drift from the single-day path.

    The ORDER of `totals` must not decide the answer, and it used to: the
    watch branch was a `next(...)` over an unordered GROUP BY, so on the
    days where both `com.fitbit.FitbitMobile` and Google Health write —
    50 of the last 100, disagreeing by ~5,000 steps on average — the
    canonical count was whichever row postgres happened to return first.
    Besides being arbitrary, that makes any stored-vs-recount staleness
    test flip-flop forever: each recompute can legitimately produce a
    different number and so look stale again immediately.
    """
    if not totals:
        return None
    watch = [t for t in totals if _is_watch_source(t[0])]
    pool = watch or totals
    # Largest total wins, source name breaks an exact tie. Largest was
    # always the rule for the no-watch case; applying it inside the watch
    # pool too matters during the Fitbit -> Google Health rebrand, where
    # both packages write and the fuller one is the live writer rather
    # than a partial duplicate left behind mid-migration.
    return min(pool, key=lambda x: (-x[1], x[0]))[0]


async def pick_canonical_steps_source(
    db: AsyncSession, start: datetime, end: datetime,
) -> str | None:
    """Pick the single source we trust for steps in [start, end].

    Mirrors the live logic in /summary/today so the persisted
    daily_summary row matches what the dashboard renders. Returns
    None when no usable rows exist (caller falls back to 0)."""
    rows = (await db.execute(
        select(
            models.Steps.source,
            func.coalesce(func.sum(models.Steps.count), 0).label("total"),
        )
        .where(models.Steps.time >= start)
        .where(models.Steps.time <= end)
        .where(models.Steps.source != "unknown")
        .group_by(models.Steps.source)
    )).all()
    return _pick_steps_source([(s, int(t)) for s, t in rows if s])


async def canonical_steps_total(
    db: AsyncSession, start: datetime, end: datetime,
) -> int | None:
    """Steps in [start, end] exactly as `daily_summary.steps_total` stores it.

    One canonical source, per-minute MAX inside it. Shared by the write
    (`compute_daily_summary`) and by the staleness check that decides
    whether that write is out of date — two copies of this arithmetic
    would disagree and the row would be judged stale forever.

    None means no usable source covered the window; 0 means a source was
    there and recorded nothing, which is a fact about the day rather than
    an absence of data.
    """
    canonical = await pick_canonical_steps_source(db, start, end)
    if canonical is None:
        return None
    minute_col = func.date_trunc("minute", models.Steps.time)
    per_min_subq = (
        select(func.max(models.Steps.count).label("mx"))
        .where(models.Steps.time >= start)
        .where(models.Steps.time <= end)
        .where(models.Steps.source == canonical)
        .group_by(minute_col)
        .subquery()
    )
    total = (await db.execute(
        select(func.coalesce(func.sum(per_min_subq.c.mx), 0))
    )).scalar()
    return int(total or 0)


async def canonical_steps_by_day(
    db: AsyncSession, start: datetime, end: datetime, tzname: str,
) -> dict[date, int]:
    """`canonical_steps_total` for every LOCAL day in the window, in one query.

    The batched staleness scan in /summary/range needs the canonical count
    for up to a year of days at once; asking day by day would be the
    per-day round-trip the rest of that scan exists to avoid. Days with no
    usable source are simply absent from the mapping.
    """
    local_day = cast(func.timezone(tzname, models.Steps.time), Date)
    minute_col = func.date_trunc("minute", models.Steps.time)
    per_min = (
        select(
            local_day.label("day"),
            models.Steps.source.label("source"),
            func.max(models.Steps.count).label("mx"),
        )
        .where(models.Steps.time >= start)
        .where(models.Steps.time <= end)
        .where(models.Steps.source != "unknown")
        .group_by(local_day, models.Steps.source, minute_col)
        .subquery()
    )
    rows = (await db.execute(
        select(per_min.c.day, per_min.c.source, func.sum(per_min.c.mx))
        .group_by(per_min.c.day, per_min.c.source)
    )).all()
    per_day: dict[date, list[tuple[str, int]]] = {}
    for d, src, total in rows:
        if d is None or not src:
            continue
        per_day.setdefault(d, []).append((src, int(total or 0)))
    out: dict[date, int] = {}
    for d, totals in per_day.items():
        chosen = _pick_steps_source(totals)
        if chosen is None:
            continue
        out[d] = next(t for s, t in totals if s == chosen)
    return out

# An RHR jump above the rolling baseline by this many bpm fires an alert.
RHR_DRIFT_BPM = 5.0

# Phase 3 alert thresholds.
BP_SYS_STAGE1 = 130.0  # AHA stage-1 hypertension threshold (rolling 7d mean)
BP_DIA_STAGE1 = 80.0
BP_SYS_STAGE2 = 140.0
BP_DIA_STAGE2 = 90.0
WEIGHT_RAPID_PCT = 2.0  # rolling 7d delta vs the prior week
SKIN_TEMP_ANOMALY_DELTA_C = 0.5  # 3d mean above 28d mean


def _local_tz():
    """The user's configured timezone, falling back to UTC if unresolvable."""
    try:
        from zoneinfo import ZoneInfo
        from ..config import settings as _settings
        return ZoneInfo(_settings.tz) if _settings.tz != "UTC" else timezone.utc
    except Exception:
        return timezone.utc


async def compute_daily_summary(target_date: date | None = None) -> None:
    # The default target is the user's LOCAL today, not the UTC one. The CT
    # runs TZ=UTC while the user is Central, so from 7pm local a UTC-derived
    # date is TOMORROW -- and the one caller that relies on the default
    # (`main.py`'s startup job) was writing an empty row for a day that had
    # not begun, which then sat in front of every reader as though the day
    # were simply stepless.
    target = target_date or datetime.now(_local_tz()).date()
    log.info("computing daily_summary for %s", target)

    async with SessionLocal() as db:
        rhr = await nightly_rhr(db, target)
        rhr_baseline = await rolling_baseline(db, target, metric="rhr")
        hrv = await nightly_hrv(db, target)
        recovery = await recovery_score(db, target)
        sleep_pts, sleep_duration = await sleep_score(db, target)

        # Steps total for the date — local-tz day, deduped per minute.
        # See summary.py for rationale on both the TZ fix and the
        # per-minute MAX (multi-source HC ingest dedupe).
        _local = _local_tz()
        day_start = datetime.combine(target, time.min, tzinfo=_local)
        day_end = datetime.combine(target, time.max, tzinfo=_local)
        # A SINGLE canonical source (watch when present), summed as
        # per-minute MAX within it. Crossing sources here over-counts
        # because the phone pedometer and the watch rarely fire on the
        # same minute boundary — what looks like per-minute MAX
        # de-duping turns into "add both totals together". The staleness
        # checks in api/summary.py recount through the same helper, so a
        # repaired row lands on the number they were comparing against.
        steps_total = await canonical_steps_total(db, day_start, day_end)

        # Body metrics — last reading on this day wins (daily weigh-in pattern).
        body_row = await db.execute(
            select(models.BodyMetric.weight_kg, models.BodyMetric.body_fat_pct)
            .where(models.BodyMetric.time >= day_start)
            .where(models.BodyMetric.time <= day_end)
            .order_by(models.BodyMetric.time.desc())
            .limit(1)
        )
        body = body_row.first()
        weight_kg = body[0] if body else None
        body_fat_pct = body[1] if body else None

        # Blood pressure — average of all readings in the day (often only 1).
        bp_row = await db.execute(
            select(
                func.avg(models.BloodPressure.systolic),
                func.avg(models.BloodPressure.diastolic),
            )
            .where(models.BloodPressure.time >= day_start)
            .where(models.BloodPressure.time <= day_end)
        )
        bp_sys, bp_dia = bp_row.first() or (None, None)
        bp_systolic_avg = float(bp_sys) if bp_sys is not None else None
        bp_diastolic_avg = float(bp_dia) if bp_dia is not None else None

        # Skin-temp delta — daily average (overnight wrist sensor reading).
        temp_val = (await db.execute(
            select(func.avg(models.SkinTemp.celsius_delta))
            .where(models.SkinTemp.time >= day_start)
            .where(models.SkinTemp.time <= day_end)
        )).scalar()
        skin_temp_delta_avg = float(temp_val) if temp_val is not None else None

        # Fasting hours overlapping this day. Sum of each session's
        # overlap with [day_start, day_end). Active fasts (ended_at NULL)
        # contribute their elapsed portion to now(). Computed via a
        # raw SQL EXTRACT on the GREATEST/LEAST overlap so postgres can
        # sum without round-tripping all sessions through Python.
        fast_rows = await db.execute(
            select(models.FastingSession.started_at, models.FastingSession.ended_at)
            .where(models.FastingSession.started_at < day_end)
            .where(
                (models.FastingSession.ended_at.is_(None))
                | (models.FastingSession.ended_at >= day_start)
            )
        )
        now_utc = datetime.now(timezone.utc)
        fasting_seconds = 0.0
        for start, end in fast_rows.all():
            end_clamped = end or now_utc
            ov_start = max(start, day_start)
            ov_end = min(end_clamped, day_end)
            if ov_end > ov_start:
                fasting_seconds += (ov_end - ov_start).total_seconds()
        fasting_hours = round(fasting_seconds / 3600.0, 3) or None

        # === Advanced derived metrics ===
        readiness = await readiness_score(
            db, target, hrv=hrv, rhr=rhr,
            sleep_score=sleep_pts, sleep_duration_s=sleep_duration,
        )
        tss = await daily_training_stress(db, target)
        ctl, atl, tsb = await update_training_load(db, target, tss)
        sc = await sleep_consistency_score(db, target)
        # Pull profile sleep target (default 8h) for sleep debt calc.
        prof = await db.get(models.UserProfile, 1)
        sleep_target_h = float(prof.sleep_target_h) if prof and prof.sleep_target_h else 8.0
        sd = await sleep_debt_hours(db, target, sleep_target_h)

        values = dict(
            date=target,
            resting_hr=rhr,
            hrv_avg=hrv,
            recovery_score=recovery,
            sleep_duration_s=sleep_duration,
            sleep_score=sleep_pts,
            steps_total=steps_total,
            weight_kg=weight_kg,
            body_fat_pct=body_fat_pct,
            bp_systolic_avg=bp_systolic_avg,
            bp_diastolic_avg=bp_diastolic_avg,
            skin_temp_delta_avg=skin_temp_delta_avg,
            readiness_score=readiness,
            training_stress_score=tss,
            ctl=ctl, atl=atl, tsb=tsb,
            sleep_consistency_score=sc,
            sleep_debt_h=sd,
            fasting_hours=fasting_hours,
        )
        stmt = insert(models.DailySummary).values(**values).on_conflict_do_update(
            index_elements=["date"],
            set_={k: v for k, v in values.items() if k != "date"},
        )
        await db.execute(stmt)

        # RHR drift alert. Dedup per target date: compute_daily_summary now
        # runs lazily on every /summary read, so without this guard a day with
        # drift would mint a fresh rhr_drift alert on each recompute (and a
        # concurrent double-compute would double-insert). Other alert kinds
        # already suppress via _alert_recently_fired; this is the per-date
        # equivalent keyed on the payload date.
        if rhr is not None and rhr_baseline is not None:
            delta = rhr - rhr_baseline
            if delta >= RHR_DRIFT_BPM:
                already = (await db.execute(
                    select(func.count())
                    .select_from(models.Alert)
                    .where(models.Alert.kind == "rhr_drift")
                    # payload is a generic JSON column (not PG JSONB), so
                    # `.astext` isn't available — use the ->> operator, which
                    # extracts JSON text on both json and jsonb. `.astext`
                    # here silently failed the whole daily-summary recompute
                    # on any day with an RHR drift.
                    .where(models.Alert.payload.op("->>")("date") == target.isoformat())
                )).scalar() or 0
                if not already:
                    db.add(models.Alert(
                        ts=datetime.now(timezone.utc),
                        kind="rhr_drift",
                        payload={
                            "date": target.isoformat(),
                            "rhr": rhr,
                            "baseline": rhr_baseline,
                            "delta_bpm": delta,
                        },
                    ))
                    log.warning(
                        "RHR drift alert for %s: %.1f bpm above baseline %.1f",
                        target, delta, rhr_baseline,
                    )

        # Phase 3 alerts (BP / weight trend / skin temp anomaly).
        await _emit_health_alerts(db, target)

        # Illness early-warning composite (3+ of {RHR↑, HRV↓, skin temp↑, recovery↓}).
        warning = await illness_warning_signals(
            db, target, rhr=rhr, hrv=hrv, recovery=recovery,
            skin_temp=skin_temp_delta_avg,
        )
        if warning is not None:
            recent = await _alert_recently_fired(
                db, "illness_warning", datetime.now(timezone.utc) - timedelta(days=5),
            )
            if not recent:
                db.add(models.Alert(
                    ts=datetime.now(timezone.utc),
                    kind="illness_warning",
                    payload=warning,
                ))
                log.warning("Illness warning fired for %s: %s", target, warning["signals"])

        await db.commit()
        log.info(
            "daily_summary written: rhr=%s hrv=%s recovery=%s sleep=%ss/%s steps=%s",
            rhr, hrv, recovery, sleep_duration, sleep_pts, steps_total,
        )


async def _rolling_mean(
    db: AsyncSession, column, target: date, window_days: int,
) -> float | None:
    """Average of `column` over the [target-window+1, target] inclusive window."""
    since = target - timedelta(days=window_days - 1)
    stmt = (
        select(func.avg(column))
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= target)
        .where(column.is_not(None))
    )
    result = await db.execute(stmt)
    val = result.scalar()
    return float(val) if val is not None else None


async def _alert_recently_fired(
    db: AsyncSession, kind: str, since: datetime,
) -> bool:
    stmt = (
        select(func.count())
        .select_from(models.Alert)
        .where(models.Alert.kind == kind)
        .where(models.Alert.ts >= since)
    )
    return ((await db.execute(stmt)).scalar() or 0) > 0


async def _emit_health_alerts(db: AsyncSession, target: date) -> None:
    """BP / weight / skin-temp alerts based on rolling daily_summary windows.

    Each kind suppresses duplicates by checking whether the same kind has
    fired recently — a noisy hypertensive week shouldn't generate seven
    alerts.
    """
    now = datetime.now(timezone.utc)

    # --- BP rolling 7-day average ---
    bp_sys_7d = await _rolling_mean(db, models.DailySummary.bp_systolic_avg, target, 7)
    bp_dia_7d = await _rolling_mean(db, models.DailySummary.bp_diastolic_avg, target, 7)
    if bp_sys_7d is not None or bp_dia_7d is not None:
        stage = None
        if (bp_sys_7d and bp_sys_7d >= BP_SYS_STAGE2) or (bp_dia_7d and bp_dia_7d >= BP_DIA_STAGE2):
            stage = 2
        elif (bp_sys_7d and bp_sys_7d >= BP_SYS_STAGE1) or (bp_dia_7d and bp_dia_7d >= BP_DIA_STAGE1):
            stage = 1
        if stage is not None:
            kind = f"bp_elevated_stage{stage}"
            # Suppress: don't re-fire the same stage within 5 days.
            recent = await _alert_recently_fired(db, kind, now - timedelta(days=5))
            if not recent:
                db.add(models.Alert(ts=now, kind=kind, payload={
                    "date": target.isoformat(),
                    "sys_7d_avg": bp_sys_7d,
                    "dia_7d_avg": bp_dia_7d,
                    "stage": stage,
                }))
                log.warning(
                    "BP stage-%d alert for %s: 7d avg %s/%s",
                    stage, target, bp_sys_7d, bp_dia_7d,
                )

    # --- Weight rapid change (this-week 7d MA vs last-week 7d MA) ---
    w_now = await _rolling_mean(db, models.DailySummary.weight_kg, target, 7)
    w_prev = await _rolling_mean(
        db, models.DailySummary.weight_kg, target - timedelta(days=7), 7,
    )
    if w_now and w_prev and w_prev > 0:
        pct = (w_now - w_prev) / w_prev * 100.0
        if abs(pct) >= WEIGHT_RAPID_PCT:
            recent = await _alert_recently_fired(
                db, "weight_rapid_change", now - timedelta(days=7),
            )
            if not recent:
                db.add(models.Alert(ts=now, kind="weight_rapid_change", payload={
                    "date": target.isoformat(),
                    "weight_now_kg": w_now,
                    "weight_prev_week_kg": w_prev,
                    "pct_change": pct,
                }))
                log.warning(
                    "Weight rapid change for %s: %.2f → %.2f kg (%.1f%%)",
                    target, w_prev, w_now, pct,
                )

    # --- Skin-temp anomaly (3d mean above 28d mean) ---
    st_3d = await _rolling_mean(db, models.DailySummary.skin_temp_delta_avg, target, 3)
    st_28d = await _rolling_mean(db, models.DailySummary.skin_temp_delta_avg, target, 28)
    if st_3d is not None and st_28d is not None:
        excess = st_3d - st_28d
        if excess >= SKIN_TEMP_ANOMALY_DELTA_C:
            recent = await _alert_recently_fired(
                db, "skin_temp_anomaly", now - timedelta(days=4),
            )
            if not recent:
                db.add(models.Alert(ts=now, kind="skin_temp_anomaly", payload={
                    "date": target.isoformat(),
                    "delta_3d_avg_c": st_3d,
                    "delta_28d_avg_c": st_28d,
                    "excess_c": excess,
                }))
                log.warning(
                    "Skin-temp anomaly for %s: 3d=%.2f vs 28d=%.2f (+%.2f °C)",
                    target, st_3d, st_28d, excess,
                )
