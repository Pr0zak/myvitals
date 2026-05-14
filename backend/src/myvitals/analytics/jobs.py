"""Nightly analytics job: writes a daily_summary row + emits health alerts."""
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
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

# An RHR jump above the rolling baseline by this many bpm fires an alert.
RHR_DRIFT_BPM = 5.0

# Phase 3 alert thresholds.
BP_SYS_STAGE1 = 130.0  # AHA stage-1 hypertension threshold (rolling 7d mean)
BP_DIA_STAGE1 = 80.0
BP_SYS_STAGE2 = 140.0
BP_DIA_STAGE2 = 90.0
WEIGHT_RAPID_PCT = 2.0  # rolling 7d delta vs the prior week
SKIN_TEMP_ANOMALY_DELTA_C = 0.5  # 3d mean above 28d mean


async def compute_daily_summary(target_date: date | None = None) -> None:
    target = target_date or datetime.now(timezone.utc).date()
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
        try:
            from zoneinfo import ZoneInfo
            from ..config import settings as _settings
            _local = ZoneInfo(_settings.tz) if _settings.tz != "UTC" else timezone.utc
        except Exception:
            _local = timezone.utc
        day_start = datetime.combine(target, time.min, tzinfo=_local)
        day_end = datetime.combine(target, time.max, tzinfo=_local)
        minute_col = func.date_trunc("minute", models.Steps.time)
        per_min_subq = (
            select(func.max(models.Steps.count).label("mx"))
            .where(models.Steps.time >= day_start)
            .where(models.Steps.time <= day_end)
            .group_by(minute_col)
            .subquery()
        )
        steps_result = await db.execute(
            select(func.coalesce(func.sum(per_min_subq.c.mx), 0))
        )
        steps_total = int(steps_result.scalar() or 0) or None

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

        # RHR drift alert
        if rhr is not None and rhr_baseline is not None:
            delta = rhr - rhr_baseline
            if delta >= RHR_DRIFT_BPM:
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
