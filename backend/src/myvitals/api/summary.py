from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session
from ..config import settings
from ..schemas import TodaySummary

router = APIRouter(dependencies=[Depends(require_any)])


@router.get("/today", response_model=TodaySummary)
async def today(db: AsyncSession = Depends(get_session)) -> TodaySummary:
    """
    Returns the saved daily_summary row for today if the analytics job
    has run; otherwise computes a best-effort live snapshot.
    """
    # Resolve "today" in the user's configured TZ rather than UTC.
    # With TZ=UTC, on Central time the UTC day starts at 7pm CDT the
    # previous evening, so 5 hours of yesterday's steps were leaking
    # into today's count.
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        local_tz = timezone.utc
    now_local = datetime.now(local_tz)
    today_local = now_local.date()
    midnight_local = datetime.combine(today_local, datetime.min.time(), tzinfo=local_tz)
    end = datetime.now(timezone.utc)

    # 1. Try the persisted summary first.
    result = await db.execute(
        select(models.DailySummary).where(models.DailySummary.date == today_local)
    )
    saved = result.scalar_one_or_none()

    # 2. Compute live values as a fallback / supplement.
    # Per-minute MAX dedupes cases where multiple HC sources (watch +
    # phone pedometer + Google Fit aggregator) all report overlapping
    # steps in the same minute. Without source tagging this is the best
    # we can do at query time.
    # Prefer a single canonical step source (Wear / Pixel Watch package)
    # if present; otherwise fall back to per-minute MAX dedup across all
    # sources.
    sources_q = await db.execute(
        select(models.Steps.source).distinct()
        .where(models.Steps.time >= midnight_local)
        .where(models.Steps.time <= end)
    )
    sources = [s for s, in sources_q.all()]
    canonical = next(
        (s for s in sources if "wearable" in (s or "").lower() or "fit.wearable" in (s or "").lower()),
        None,
    )
    if canonical:
        single = await db.execute(
            select(func.coalesce(func.sum(models.Steps.count), 0))
            .where(models.Steps.source == canonical)
            .where(models.Steps.time >= midnight_local)
            .where(models.Steps.time <= end)
        )
        steps_total = int(single.scalar() or 0)
    else:
        minute_col = func.date_trunc("minute", models.Steps.time)
        per_min_subq = (
            select(func.max(models.Steps.count).label("mx"))
            .where(models.Steps.time >= midnight_local)
            .where(models.Steps.time <= end)
            .group_by(minute_col)
            .subquery()
        )
        steps_result = await db.execute(
            select(func.coalesce(func.sum(per_min_subq.c.mx), 0))
        )
        steps_total = int(steps_result.scalar() or 0)

    last_sync_result = await db.execute(select(func.max(models.HeartRate.time)))
    last_sync = last_sync_result.scalar()

    # Today's row may exist (e.g., backfill ran mid-day) but be sparse —
    # the Pixel Watch hasn't yet synced today's RHR/HRV/sleep. Pull the
    # most recent row that has a recovery_score and use ITS values for
    # any field today's row leaves null. Steps/last_sync still reflect
    # today's live counts.
    fallback = (await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.recovery_score.is_not(None))
        .order_by(models.DailySummary.date.desc())
        .limit(1)
    )).scalar_one_or_none()

    def pick(field: str):
        v = getattr(saved, field, None) if saved else None
        if v is None and fallback is not None:
            return getattr(fallback, field, None)
        return v

    if saved or fallback:
        return TodaySummary(
            date=(saved.date if saved else (fallback.date if fallback else today_local)),
            resting_hr=pick("resting_hr"),
            hrv_avg=pick("hrv_avg"),
            recovery_score=pick("recovery_score"),
            sleep_duration_s=pick("sleep_duration_s"),
            sleep_score=pick("sleep_score"),
            # Steps always use today's live count — never fall back to
            # yesterday's row, that would show stale step counts as "today's".
            steps_total=steps_total,
            weight_kg=pick("weight_kg"),
            body_fat_pct=pick("body_fat_pct"),
            bp_systolic_avg=pick("bp_systolic_avg"),
            bp_diastolic_avg=pick("bp_diastolic_avg"),
            skin_temp_delta_avg=pick("skin_temp_delta_avg"),
            readiness_score=pick("readiness_score"),
            training_stress_score=pick("training_stress_score"),
            ctl=pick("ctl"), atl=pick("atl"), tsb=pick("tsb"),
            sleep_consistency_score=pick("sleep_consistency_score"),
            sleep_debt_h=pick("sleep_debt_h"),
            last_sync=last_sync,
        )

    # No saved summaries at all — return live counts only.
    return TodaySummary(
        date=today_local,
        steps_total=steps_total,
        last_sync=last_sync,
    )


@router.get("/range", response_model=list[TodaySummary])
async def summary_range(
    since: date = Query(...),
    until: date | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[TodaySummary]:
    """Daily summaries between two dates (inclusive)."""
    end = until or datetime.now(timezone.utc).date()
    result = await db.execute(
        select(models.DailySummary)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= end)
        .order_by(models.DailySummary.date)
    )
    rows = result.scalars().all()
    return [
        TodaySummary(
            date=r.date,
            resting_hr=r.resting_hr,
            hrv_avg=r.hrv_avg,
            recovery_score=r.recovery_score,
            sleep_duration_s=r.sleep_duration_s,
            sleep_score=r.sleep_score,
            steps_total=r.steps_total,
            weight_kg=r.weight_kg,
            body_fat_pct=r.body_fat_pct,
            bp_systolic_avg=r.bp_systolic_avg,
            bp_diastolic_avg=r.bp_diastolic_avg,
            skin_temp_delta_avg=r.skin_temp_delta_avg,
            readiness_score=r.readiness_score,
            training_stress_score=r.training_stress_score,
            ctl=r.ctl, atl=r.atl, tsb=r.tsb,
            sleep_consistency_score=r.sleep_consistency_score,
            sleep_debt_h=r.sleep_debt_h,
        )
        for r in rows
    ]
