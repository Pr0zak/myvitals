"""CSV / JSON export endpoints for raw tables."""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session

router = APIRouter(dependencies=[Depends(require_query)])

TABLES = {
    "heartrate": (models.HeartRate, ["time", "bpm", "source"]),
    "hrv": (models.Hrv, ["time", "rmssd_ms"]),
    "steps": (models.Steps, ["time", "count"]),
    "sleep_stages": (models.SleepStage, ["time", "stage", "duration_s"]),
    "workouts": (models.Workout, ["time", "type", "duration_s", "kcal", "avg_hr", "max_hr"]),
    "annotations": (models.Annotation, ["id", "ts", "type", "payload", "note"]),
    "activities": (models.Activity, [
        "source", "source_id", "type", "name", "start_at", "duration_s",
        "distance_m", "elevation_gain_m", "avg_hr", "max_hr",
        "avg_power_w", "max_power_w", "kcal", "suffer_score", "polyline",
    ]),
    "daily_summary": (models.DailySummary, [
        "date", "resting_hr", "hrv_avg", "recovery_score",
        "sleep_duration_s", "sleep_score", "steps_total",
    ]),
}


@router.get("/export/{table}.{fmt}")
async def export_table(
    table: str,
    fmt: str,
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
):
    if table not in TABLES:
        raise HTTPException(400, f"table must be one of {list(TABLES.keys())}")
    if fmt not in {"csv", "json"}:
        raise HTTPException(400, "fmt must be csv or json")

    model, cols = TABLES[table]
    end = until or datetime.now(timezone.utc)
    start = since or (end - timedelta(days=90))

    # Pick the time column for filtering — every model has either `time`, `ts`, `start_at`, or `date`.
    time_col = next((getattr(model, c) for c in ["time", "ts", "start_at", "date"]
                     if hasattr(model, c)), None)
    stmt = select(model)
    if time_col is not None:
        # `if/else` has lower precedence than `>=` so the operand has to be
        # parenthesised, otherwise the whole comparison disappears.
        s = start.date() if time_col.key == "date" else start
        e = end.date() if time_col.key == "date" else end
        stmt = stmt.where(time_col >= s).where(time_col <= e)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    if fmt == "json":
        payload = [{c: getattr(r, c) for c in cols} for r in rows]
        return StreamingResponse(
            iter([json.dumps(payload, default=str)]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="myvitals-{table}.json"'},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for r in rows:
        writer.writerow([str(getattr(r, c)) if getattr(r, c) is not None else "" for c in cols])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="myvitals-{table}.csv"'},
    )
