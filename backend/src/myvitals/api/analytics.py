"""Insights, correlation, manual analytics trigger."""
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.jobs import compute_daily_summary
from ..auth import require_query
from ..db import models
from ..db.session import get_session

router = APIRouter(dependencies=[Depends(require_query)])


# === Manual trigger of the daily summary job ===

@router.post("/analytics/run")
async def run_analytics(target_date: date | None = Query(None)) -> dict[str, str]:
    await compute_daily_summary(target_date)
    return {"status": "ok", "target_date": (target_date or datetime.now(timezone.utc).date()).isoformat()}


@router.get("/analytics/discoveries")
async def discoveries(
    days: int = Query(90, ge=14, le=730),
    min_r: float = Query(0.40, ge=0.1, le=1.0),
    min_n: int = Query(14, ge=5, le=365),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Scan all (X, Y) pairs of daily-summary metrics over the window;
    return any with |Pearson r| >= min_r and at least min_n overlap. Useful
    for surfacing surprising correlations the user wouldn't think to ask
    about manually.
    """
    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=days)
    cache: dict[str, dict[date, float]] = {}
    for m in _DAILY_SUMMARY_METRICS:
        cache[m] = await _daily_summary_metric(db, m, since, until)

    out: list[dict[str, Any]] = []
    keys = list(_DAILY_SUMMARY_METRICS)
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            xs_dict = cache[x]
            ys_dict = cache[y]
            common = sorted(set(xs_dict) & set(ys_dict))
            if len(common) < min_n:
                continue
            xs = [xs_dict[d] for d in common]
            ys = [ys_dict[d] for d in common]
            r = _pearson(xs, ys)
            if r is not None and abs(r) >= min_r:
                out.append({"x_metric": x, "y_metric": y, "n": len(common), "pearson_r": r})
    out.sort(key=lambda d: -abs(d["pearson_r"]))
    return out[:20]


@router.post("/analytics/hr-recovery-backfill")
async def backfill_hr_recovery() -> dict[str, int]:
    """Compute hr_recovery_60s/120s for every activity that doesn't have it
    yet. Reads HR samples around each activity end. Idempotent — already-
    populated rows are skipped."""
    from sqlalchemy import or_, update as _update
    from .. import db as _db
    from ..analytics.advanced import compute_hr_recovery_for_activity
    async with _db.session.SessionLocal() as s:
        rows = (await s.execute(
            select(models.Activity.source, models.Activity.source_id)
            .where(or_(
                models.Activity.hr_recovery_60s.is_(None),
                models.Activity.hr_recovery_120s.is_(None),
            ))
        )).all()
        n_done = 0
        for src, sid in rows:
            r60, r120 = await compute_hr_recovery_for_activity(s, src, sid)
            if r60 is None and r120 is None:
                continue
            await s.execute(
                _update(models.Activity)
                .where(models.Activity.source == src)
                .where(models.Activity.source_id == sid)
                .values(hr_recovery_60s=r60, hr_recovery_120s=r120)
            )
            n_done += 1
            if n_done % 50 == 0:
                await s.commit()
        await s.commit()
    return {"considered": len(rows), "computed": n_done}


@router.post("/analytics/backfill")
async def backfill_analytics(days: int = Query(7, ge=1, le=3650)) -> dict[str, int]:
    """Recompute daily_summary for the past `days` days. Useful when raw data
    arrives later than the original nightly job ran (e.g. backfilled from HC)."""
    today = datetime.now(timezone.utc).date()
    ok = 0
    for i in range(days):
        try:
            await compute_daily_summary(today - timedelta(days=i))
            ok += 1
        except Exception:
            pass
    return {"computed": ok, "days": days}


# === Correlation explorer ===

# Metrics we can correlate. Each maps to an async function that returns
# {date: value} for the given window.
SUPPORTED_METRICS = [
    "resting_hr", "hrv_avg", "recovery_score",
    "sleep_duration_s", "sleep_score", "steps_total",
    "weight_kg", "body_fat_pct",
    "bp_systolic_avg", "bp_diastolic_avg",
    "skin_temp_delta_avg",
    "readiness_score", "training_stress_score",
    "ctl", "atl", "tsb",
    "sleep_consistency_score", "sleep_debt_h",
    "activity_duration_s", "alcohol_count", "caffeine_mg",
    "mood_score",
]

# Metrics that map directly to a column in daily_summary.
_DAILY_SUMMARY_METRICS = {
    "resting_hr", "hrv_avg", "recovery_score",
    "sleep_duration_s", "sleep_score", "steps_total",
    "weight_kg", "body_fat_pct",
    "bp_systolic_avg", "bp_diastolic_avg",
    "skin_temp_delta_avg",
    "readiness_score", "training_stress_score",
    "ctl", "atl", "tsb",
    "sleep_consistency_score", "sleep_debt_h",
}


class CorrelationPoint(BaseModel):
    date: str  # the reference (Y) date as ISO
    x: float
    y: float


class CorrelationResult(BaseModel):
    x_metric: str
    y_metric: str
    lag_days: int
    n: int
    pearson_r: float | None
    points: list[CorrelationPoint]


async def _daily_summary_metric(
    db: AsyncSession, metric: str, since: date, until: date,
) -> dict[date, float]:
    col = getattr(models.DailySummary, metric, None)
    if col is None:
        return {}
    result = await db.execute(
        select(models.DailySummary.date, col)
        .where(models.DailySummary.date >= since)
        .where(models.DailySummary.date <= until)
    )
    return {d: v for d, v in result.all() if v is not None}


async def _activity_duration_per_day(
    db: AsyncSession, since: date, until: date,
) -> dict[date, float]:
    start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(until, datetime.max.time(), tzinfo=timezone.utc)
    result = await db.execute(
        select(
            func.date(models.Activity.start_at).label("d"),
            func.sum(models.Activity.duration_s),
        )
        .where(models.Activity.start_at >= start)
        .where(models.Activity.start_at <= end)
        .group_by("d")
    )
    return {row[0]: float(row[1]) for row in result.all()}


async def _annotation_per_day(
    db: AsyncSession, ann_type: str, payload_key: str | None, since: date, until: date,
) -> dict[date, float]:
    """Per-day count or summed payload value for a given annotation type."""
    start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(until, datetime.max.time(), tzinfo=timezone.utc)
    result = await db.execute(
        select(models.Annotation)
        .where(models.Annotation.ts >= start)
        .where(models.Annotation.ts <= end)
        .where(models.Annotation.type == ann_type)
    )
    out: dict[date, float] = {}
    for row in result.scalars().all():
        d = row.ts.date()
        if payload_key is not None:
            v = (row.payload or {}).get(payload_key)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        else:
            v = 1.0  # count
        out[d] = out.get(d, 0.0) + v
    return out


async def _series_for_metric(
    db: AsyncSession, metric: str, since: date, until: date,
) -> dict[date, float]:
    if metric in _DAILY_SUMMARY_METRICS:
        return await _daily_summary_metric(db, metric, since, until)
    if metric == "activity_duration_s":
        return await _activity_duration_per_day(db, since, until)
    if metric == "alcohol_count":
        return await _annotation_per_day(db, "alcohol", None, since, until)
    if metric == "caffeine_mg":
        return await _annotation_per_day(db, "caffeine", "mg", since, until)
    if metric == "mood_score":
        return await _annotation_per_day(db, "mood", "score", since, until)
    return {}


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    denom = (dx2 * dy2) ** 0.5
    return None if denom == 0 else num / denom


@router.get("/analytics/correlate", response_model=CorrelationResult)
async def correlate(
    x: str = Query(..., description="X metric (independent)"),
    y: str = Query(..., description="Y metric (dependent)"),
    lag: int = Query(0, ge=-30, le=30, description="X is read N days before Y (positive = X precedes Y)"),
    days: int = Query(90, ge=7, le=365),
    db: AsyncSession = Depends(get_session),
) -> CorrelationResult:
    if x not in SUPPORTED_METRICS or y not in SUPPORTED_METRICS:
        raise HTTPException(400, f"metric must be one of {SUPPORTED_METRICS}")

    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=days + abs(lag))

    x_series = await _series_for_metric(db, x, since, until)
    y_series = await _series_for_metric(db, y, since, until)

    points: list[CorrelationPoint] = []
    for d, yv in y_series.items():
        xv = x_series.get(d - timedelta(days=lag))
        if xv is None:
            continue
        points.append(CorrelationPoint(date=d.isoformat(), x=xv, y=yv))

    r = _pearson([p.x for p in points], [p.y for p in points])
    return CorrelationResult(
        x_metric=x, y_metric=y, lag_days=lag, n=len(points), pearson_r=r, points=points,
    )


# === Alerts ===

class AlertOut(BaseModel):
    id: int
    ts: datetime
    kind: str
    payload: dict[str, Any]
    acknowledged: bool


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    acknowledged: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
) -> list[AlertOut]:
    stmt = select(models.Alert).order_by(models.Alert.ts.desc()).limit(limit)
    if acknowledged is not None:
        stmt = stmt.where(models.Alert.acknowledged == acknowledged)
    result = await db.execute(stmt)
    return [
        AlertOut(id=a.id, ts=a.ts, kind=a.kind, payload=a.payload,
                 acknowledged=a.acknowledged)
        for a in result.scalars().all()
    ]


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: int, db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    alert = await db.get(models.Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found")
    alert.acknowledged = True
    await db.commit()
    return {"status": "ok"}
