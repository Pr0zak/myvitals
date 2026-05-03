"""Nightly analytics job: writes a daily_summary row + emits alerts on RHR drift."""
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..db import models
from ..db.session import SessionLocal
from .baselines import nightly_hrv, nightly_rhr, rolling_baseline
from .recovery import recovery_score

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

        # Sleep duration: sum stage durations from last night's window.
        sleep_start = datetime.combine(
            target - timedelta(days=1), time(hour=20), tzinfo=timezone.utc
        )
        sleep_end = datetime.combine(target, time(hour=12), tzinfo=timezone.utc)
        sleep_result = await db.execute(
            select(func.coalesce(func.sum(models.SleepStage.duration_s), 0))
            .where(models.SleepStage.time >= sleep_start)
            .where(models.SleepStage.time <= sleep_end)
            .where(models.SleepStage.stage != "awake")
        )
        sleep_duration = int(sleep_result.scalar() or 0) or None

        # Steps total for the date (UTC day, simple v1).
        day_start = datetime.combine(target, time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(target, time.max, tzinfo=timezone.utc)
        steps_result = await db.execute(
            select(func.coalesce(func.sum(models.Steps.count), 0))
            .where(models.Steps.time >= day_start)
            .where(models.Steps.time <= day_end)
        )
        steps_total = int(steps_result.scalar() or 0) or None

        stmt = insert(models.DailySummary).values(
            date=target,
            resting_hr=rhr,
            hrv_avg=hrv,
            recovery_score=recovery,
            sleep_duration_s=sleep_duration,
            steps_total=steps_total,
        ).on_conflict_do_update(
            index_elements=["date"],
            set_={
                "resting_hr": rhr,
                "hrv_avg": hrv,
                "recovery_score": recovery,
                "sleep_duration_s": sleep_duration,
                "steps_total": steps_total,
            },
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
            "daily_summary written: rhr=%s hrv=%s recovery=%s sleep=%ss steps=%s",
            rhr, hrv, recovery, sleep_duration, steps_total,
        )
