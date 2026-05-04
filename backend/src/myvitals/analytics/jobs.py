"""Nightly analytics job: writes a daily_summary row + emits alerts on RHR drift."""
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..db import models
from ..db.session import SessionLocal
from .baselines import nightly_hrv, nightly_rhr, rolling_baseline
from .recovery import recovery_score
from .sleep import sleep_score

log = logging.getLogger(__name__)

# An RHR jump above the rolling baseline by this many bpm fires an alert.
RHR_DRIFT_BPM = 5.0


async def compute_daily_summary(target_date: date | None = None) -> None:
    target = target_date or datetime.now(timezone.utc).date()
    log.info("computing daily_summary for %s", target)

    async with SessionLocal() as db:
        rhr = await nightly_rhr(db, target)
        rhr_baseline = await rolling_baseline(db, target, metric="rhr")
        hrv = await nightly_hrv(db, target)
        recovery = await recovery_score(db, target)
        sleep_pts, sleep_duration = await sleep_score(db, target)

        # Steps total for the date (UTC day, simple v1).
        day_start = datetime.combine(target, time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(target, time.max, tzinfo=timezone.utc)
        steps_result = await db.execute(
            select(func.coalesce(func.sum(models.Steps.count), 0))
            .where(models.Steps.time >= day_start)
            .where(models.Steps.time <= day_end)
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

        await db.commit()
        log.info(
            "daily_summary written: rhr=%s hrv=%s recovery=%s sleep=%ss/%s steps=%s",
            rhr, hrv, recovery, sleep_duration, sleep_pts, steps_total,
        )
