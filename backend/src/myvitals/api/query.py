from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..schemas import (
    HeartRateSeries,
    HrvSeries,
    SleepNight,
    SleepStageBucket,
    StepsSeries,
    TimePoint,
)

router = APIRouter(dependencies=[Depends(require_query)])


def _resolve_range(
    since: datetime | None, until: datetime | None, default_window: timedelta
) -> tuple[datetime, datetime]:
    end = until or datetime.now(timezone.utc)
    start = since or (end - default_window)
    if start >= end:
        raise HTTPException(status_code=400, detail="`since` must be before `until`")
    return start, end


@router.get("/heartrate", response_model=HeartRateSeries)
async def get_heartrate(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> HeartRateSeries:
    start, end = _resolve_range(since, until, timedelta(hours=24))
    result = await db.execute(
        select(models.HeartRate.time, models.HeartRate.bpm)
        .where(models.HeartRate.time >= start)
        .where(models.HeartRate.time <= end)
        .order_by(models.HeartRate.time)
    )
    rows = result.all()
    points = [TimePoint(time=t, value=v) for t, v in rows]

    if not points:
        return HeartRateSeries(points=[])

    values = [p.value for p in points]
    return HeartRateSeries(
        points=points,
        avg=sum(values) / len(values),
        min_bpm=min(values),
        max_bpm=max(values),
    )


@router.get("/hrv", response_model=HrvSeries)
async def get_hrv(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> HrvSeries:
    start, end = _resolve_range(since, until, timedelta(days=7))
    result = await db.execute(
        select(models.Hrv.time, models.Hrv.rmssd_ms)
        .where(models.Hrv.time >= start)
        .where(models.Hrv.time <= end)
        .order_by(models.Hrv.time)
    )
    rows = result.all()
    points = [TimePoint(time=t, value=v) for t, v in rows]
    avg = sum(p.value for p in points) / len(points) if points else None
    return HrvSeries(points=points, avg=avg)


@router.get("/steps", response_model=StepsSeries)
async def get_steps(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> StepsSeries:
    start, end = _resolve_range(since, until, timedelta(hours=24))
    result = await db.execute(
        select(models.Steps.time, models.Steps.count)
        .where(models.Steps.time >= start)
        .where(models.Steps.time <= end)
        .order_by(models.Steps.time)
    )
    rows = result.all()
    points = [TimePoint(time=t, value=float(c)) for t, c in rows]
    total = sum(int(p.value) for p in points)
    return StepsSeries(points=points, total=total)


@router.get("/sleep/last", response_model=SleepNight | None)
async def get_last_sleep(
    db: AsyncSession = Depends(get_session),
) -> SleepNight | None:
    """Most recent contiguous sleep session (gap >2h breaks it)."""
    # Pull last 36h of stage rows; group into the most recent contiguous block.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    result = await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= cutoff)
        .order_by(models.SleepStage.time)
    )
    rows = result.all()
    if not rows:
        return None

    # Walk newest-first, accumulate while consecutive stages are within 2h.
    rows_sorted = sorted(rows, key=lambda r: r[0], reverse=True)
    session: list[tuple[datetime, str, int]] = [rows_sorted[0]]
    for prev, cur in zip(rows_sorted[:-1], rows_sorted[1:], strict=False):
        gap = prev[0] - cur[0]
        if gap > timedelta(hours=2):
            break
        session.append(cur)

    session.sort(key=lambda r: r[0])
    start_t = session[0][0]
    end_t = session[-1][0] + timedelta(seconds=session[-1][2])

    # Aggregate by stage
    by_stage: dict[str, int] = {}
    for _, stage, dur in session:
        by_stage[stage] = by_stage.get(stage, 0) + dur

    return SleepNight(
        date=start_t.date(),
        start=start_t,
        end=end_t,
        total_s=sum(by_stage.values()),
        stages=[SleepStageBucket(stage=k, duration_s=v) for k, v in by_stage.items()],
    )


@router.get("/sleep/raw")
async def get_sleep_raw(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Raw per-stage rows (un-grouped) — used to draw hypnograms."""
    start, end = _resolve_range(since, until, timedelta(hours=36))
    result = await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= start)
        .where(models.SleepStage.time <= end)
        .order_by(models.SleepStage.time)
    )
    return [
        {"time": t.isoformat(), "stage": s, "duration_s": d}
        for t, s, d in result.all()
    ]


@router.get("/sleep/range", response_model=list[SleepNight])
async def get_sleep_range(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[SleepNight]:
    """All sleep sessions (split by 2h gaps) in the time range, oldest first."""
    start, end = _resolve_range(since, until, timedelta(days=30))
    result = await db.execute(
        select(models.SleepStage.time, models.SleepStage.stage, models.SleepStage.duration_s)
        .where(models.SleepStage.time >= start)
        .where(models.SleepStage.time <= end)
        .order_by(models.SleepStage.time)
    )
    rows = result.all()
    if not rows:
        return []

    # Group rows into sessions: a 2-hour gap between consecutive stage starts breaks the night.
    sessions: list[list[tuple[datetime, str, int]]] = []
    current: list[tuple[datetime, str, int]] = []
    for ts, stage, dur in rows:
        if current and (ts - current[-1][0]) > timedelta(hours=2):
            sessions.append(current)
            current = []
        current.append((ts, stage, dur))
    if current:
        sessions.append(current)

    out: list[SleepNight] = []
    for session in sessions:
        start_t = session[0][0]
        end_t = session[-1][0] + timedelta(seconds=session[-1][2])
        by_stage: dict[str, int] = {}
        for _, stage, dur in session:
            by_stage[stage] = by_stage.get(stage, 0) + dur
        out.append(SleepNight(
            date=start_t.date(),
            start=start_t,
            end=end_t,
            total_s=sum(by_stage.values()),
            stages=[SleepStageBucket(stage=k, duration_s=v) for k, v in by_stage.items()],
        ))
    return out


@router.get("/weight")
async def get_weight(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Body-metric series: weight, body fat, BMI, lean mass."""
    start, end = _resolve_range(since, until, timedelta(days=90))
    result = await db.execute(
        select(
            models.BodyMetric.time, models.BodyMetric.weight_kg,
            models.BodyMetric.body_fat_pct, models.BodyMetric.bmi,
            models.BodyMetric.lean_mass_kg, models.BodyMetric.source,
        )
        .where(models.BodyMetric.time >= start)
        .where(models.BodyMetric.time <= end)
        .order_by(models.BodyMetric.time)
    )
    rows = result.all()
    points = [
        {"time": t.isoformat(), "weight_kg": w, "body_fat_pct": bf,
         "bmi": b, "lean_mass_kg": lm, "source": src}
        for t, w, bf, b, lm, src in rows
    ]
    weights = [r[1] for r in rows if r[1] is not None]
    return {
        "points": points,
        "latest_kg": weights[-1] if weights else None,
        "min_kg": min(weights) if weights else None,
        "max_kg": max(weights) if weights else None,
        "avg_kg": sum(weights) / len(weights) if weights else None,
    }


@router.get("/blood-pressure")
async def get_blood_pressure(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Blood-pressure cuff readings (OMRON Connect via HC, or manual entry)."""
    start, end = _resolve_range(since, until, timedelta(days=90))
    result = await db.execute(
        select(
            models.BloodPressure.time, models.BloodPressure.systolic,
            models.BloodPressure.diastolic, models.BloodPressure.pulse_bpm,
            models.BloodPressure.source, models.BloodPressure.notes,
        )
        .where(models.BloodPressure.time >= start)
        .where(models.BloodPressure.time <= end)
        .order_by(models.BloodPressure.time)
    )
    rows = result.all()
    points = [
        {"time": t.isoformat(), "systolic": s, "diastolic": d,
         "pulse_bpm": p, "source": src, "notes": n}
        for t, s, d, p, src, n in rows
    ]
    sys_vals = [r[1] for r in rows]
    dia_vals = [r[2] for r in rows]
    return {
        "points": points,
        "latest": points[-1] if points else None,
        "avg_sys": sum(sys_vals) / len(sys_vals) if sys_vals else None,
        "avg_dia": sum(dia_vals) / len(dia_vals) if dia_vals else None,
    }


# Manual-entry shortcut so the dashboard doesn't have to build a Bearer ingest path.
class BloodPressureIn(BaseModel):
    systolic: int
    diastolic: int
    pulse_bpm: int | None = None
    notes: str | None = None
    time: datetime | None = None


@router.post("/blood-pressure")
async def post_blood_pressure(
    body: BloodPressureIn,
    db: AsyncSession = Depends(get_session),
) -> dict:
    ts = body.time or datetime.now(timezone.utc)
    row = models.BloodPressure(
        time=ts, systolic=body.systolic, diastolic=body.diastolic,
        pulse_bpm=body.pulse_bpm, source="manual", notes=body.notes,
    )
    await db.merge(row)
    await db.commit()
    return {"status": "ok", "time": ts.isoformat()}


@router.get("/skin-temp")
async def get_skin_temp(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Skin temperature delta (°C from baseline) — overnight wrist sensor reading."""
    start, end = _resolve_range(since, until, timedelta(days=30))
    result = await db.execute(
        select(models.SkinTemp.time, models.SkinTemp.celsius_delta)
        .where(models.SkinTemp.time >= start)
        .where(models.SkinTemp.time <= end)
        .order_by(models.SkinTemp.time)
    )
    rows = result.all()
    return {
        "points": [{"time": t.isoformat(), "value": v} for t, v in rows],
    }


@router.get("/last-sync")
async def get_last_sync(db: AsyncSession = Depends(get_session)) -> dict[str, datetime | None]:
    """Most recent timestamp across all vitals tables — proxy for 'when did the watch last sync'."""
    tables = [models.HeartRate, models.Hrv, models.Spo2, models.Steps]
    latest: datetime | None = None
    for t in tables:
        result = await db.execute(select(func.max(t.time)))
        ts = result.scalar()
        if ts and (latest is None or ts > latest):
            latest = ts
    return {"last_sync": latest}
