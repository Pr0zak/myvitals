from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..schemas import TodaySummary

router = APIRouter(dependencies=[Depends(require_query)])


@router.get("/today", response_model=TodaySummary)
async def today(db: AsyncSession = Depends(get_session)) -> TodaySummary:
    """
    Returns the saved daily_summary row for today if the analytics job
    has run; otherwise computes a best-effort live snapshot.
    """
    today_local = datetime.now(timezone.utc).date()

    # 1. Try the persisted summary first.
    result = await db.execute(
        select(models.DailySummary).where(models.DailySummary.date == today_local)
    )
    saved = result.scalar_one_or_none()

    # 2. Compute live values as a fallback / supplement.
    midnight = datetime.combine(today_local, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)

    steps_result = await db.execute(
        select(func.coalesce(func.sum(models.Steps.count), 0))
        .where(models.Steps.time >= midnight)
        .where(models.Steps.time <= end)
    )
    steps_total = int(steps_result.scalar() or 0)

    last_sync_result = await db.execute(select(func.max(models.HeartRate.time)))
    last_sync = last_sync_result.scalar()

    if saved:
        return TodaySummary(
            date=saved.date,
            resting_hr=saved.resting_hr,
            hrv_avg=saved.hrv_avg,
            recovery_score=saved.recovery_score,
            sleep_duration_s=saved.sleep_duration_s,
            sleep_score=saved.sleep_score,
            steps_total=saved.steps_total or steps_total,
            last_sync=last_sync,
        )

    # No saved summary yet — return live counts only.
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
        )
        for r in rows
    ]
