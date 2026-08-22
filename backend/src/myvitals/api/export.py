"""CSV / JSON export endpoints for raw tables."""
import csv
import io
import json
from collections.abc import AsyncIterator
from typing import Any
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
    "workouts": (models.Workout, ["time", "type", "duration_s", "kcal", "avg_hr", "max_hr", "source", "title"]),
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
    "body_metrics": (models.BodyMetric, [
        "time", "weight_kg", "body_fat_pct", "bmi", "lean_mass_kg", "source",
    ]),
    "skin_temp": (models.SkinTemp, ["time", "celsius_delta"]),
    "blood_pressure": (models.BloodPressure, [
        "time", "systolic", "diastolic", "pulse_bpm", "source", "notes",
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
    # LOCAL now, not UTC. Below, a `date`-keyed table takes `.date()` off
    # this instant — and a UTC instant yields TOMORROW's date after 7pm
    # Central, so the export silently ran one day past the intended end.
    #
    # Split across two statements, which is why the AST guard in
    # test_local_day_boundary.py never caught it: that matcher only
    # recognises the single chained `datetime.now(timezone.utc).date()`
    # form. Adding export.py to DAY_FACING_MODULES before this fix would
    # have passed green over a live bug.
    from .summary import _local_tz  # local import: summary imports models too

    end = until or datetime.now(_local_tz())
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

    # Genuinely streamed, in batches, from a server-side cursor.
    #
    # This used to do `result.scalars().all()` and then build the entire
    # output as one string before wrapping it in `iter([...])` — a
    # StreamingResponse that streams a single pre-built blob. It was
    # double-buffered: every ORM row in memory, then the whole serialised
    # body in memory again.
    #
    # `vitals_heartrate` holds ~23.6M rows and the container has no
    # mem_limit on an 8 GB CT, so a wide range was an OOM kill of the
    # backend rather than a slow download. That is also why the date range
    # could never safely be made user-selectable: the feature was blocked
    # on this.
    if fmt == "json":
        return StreamingResponse(
            _stream_json(model, cols, stmt),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="myvitals-{table}.json"'},
        )
    return StreamingResponse(
        _stream_csv(cols, stmt),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="myvitals-{table}.csv"'},
    )


#: Rows pulled from the cursor per round trip. Large enough that the
#: per-batch overhead is negligible, small enough that a batch of the
#: widest row is a rounding error against container memory.
_STREAM_BATCH = 2000


def _cell(row: Any, col: str) -> str:
    v = getattr(row, col)
    return "" if v is None else str(v)


async def _stream_csv(cols: list[str], stmt: Any) -> AsyncIterator[str]:
    """Yield a CSV header then batches of rows.

    Opens its OWN session rather than using the request-scoped one. A
    StreamingResponse body is consumed after the endpoint function has
    returned, so the dependency-injected session may already be closed by
    the time the first row is pulled — the failure looks like a truncated
    download rather than an error.
    """
    from ..db.session import SessionLocal

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    yield buf.getvalue()

    async with SessionLocal() as own_db:
        result = await own_db.stream_scalars(
            stmt.execution_options(yield_per=_STREAM_BATCH),
        )
        async for batch in result.partitions(_STREAM_BATCH):
            buf.seek(0)
            buf.truncate(0)
            for row in batch:
                writer.writerow([_cell(row, c) for c in cols])
            yield buf.getvalue()


async def _stream_json(
    model: Any, cols: list[str], stmt: Any,
) -> AsyncIterator[str]:
    """Yield a JSON array incrementally.

    Assembled by hand rather than with json.dumps over the whole list,
    for the same reason as the CSV path — the point is never to hold the
    full result in memory. Each ROW is still serialised by json.dumps, so
    escaping stays correct.
    """
    from ..db.session import SessionLocal

    yield "["
    first = True
    async with SessionLocal() as own_db:
        result = await own_db.stream_scalars(
            stmt.execution_options(yield_per=_STREAM_BATCH),
        )
        async for batch in result.partitions(_STREAM_BATCH):
            chunk = []
            for row in batch:
                obj = {c: getattr(row, c) for c in cols}
                chunk.append(("" if first else ",") + json.dumps(obj, default=str))
                first = False
            yield "".join(chunk)
    yield "]"
