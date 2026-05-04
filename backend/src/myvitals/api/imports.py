"""Historical imports from Fitbit / Garmin account-data ZIP exports."""
from __future__ import annotations

import io
import logging
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..integrations import imports as imp_int
from .ingest import _bulk_upsert

log = logging.getLogger(__name__)
router = APIRouter(prefix="/import", dependencies=[Depends(require_query)])


async def _upsert_activities(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    n = 0
    # Activities use upsert (replace existing) so re-imports refresh fields.
    # Chunk to stay under Postgres' 32k bind-param limit (Activity has ~16 cols).
    CHUNK = 1500
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i : i + CHUNK]
        stmt = insert(models.Activity).values(chunk)
        # Preserve user-edited notes/tags across re-imports
        update_cols = {c.name: c for c in stmt.excluded
                       if c.name not in ("source", "source_id", "notes", "tags")}
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "source_id"], set_=update_cols,
        )
        await db.execute(stmt)
        n += len(chunk)
    return n


async def _ingest_streams(
    db: AsyncSession, streams: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if streams.get("heartrate"):
        await _bulk_upsert(db, models.HeartRate, streams["heartrate"], ["time"])
        counts["heartrate"] = len(streams["heartrate"])
    if streams.get("steps"):
        await _bulk_upsert(db, models.Steps, streams["steps"], ["time"])
        counts["steps"] = len(streams["steps"])
    if streams.get("hrv"):
        await _bulk_upsert(db, models.Hrv, streams["hrv"], ["time"])
        counts["hrv"] = len(streams["hrv"])
    if streams.get("sleep_stages"):
        await _bulk_upsert(
            db, models.SleepStage, streams["sleep_stages"], ["time", "stage"],
        )
        counts["sleep_stages"] = len(streams["sleep_stages"])
    if streams.get("body_metrics"):
        await _bulk_upsert(db, models.BodyMetric, streams["body_metrics"], ["time"])
        counts["body_metrics"] = len(streams["body_metrics"])
    if streams.get("skin_temp"):
        await _bulk_upsert(db, models.SkinTemp, streams["skin_temp"], ["time"])
        counts["skin_temp"] = len(streams["skin_temp"])
    if streams.get("activities"):
        counts["activities"] = await _upsert_activities(db, streams["activities"])
    await db.commit()
    return counts


def _open_zip(payload: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail=f"not a valid zip: {e}") from e


@router.post("/fitbit")
async def import_fitbit(
    file: UploadFile = File(...),
    weight_unit: str = Query("kg", pattern="^(kg|lb)$"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await file.read()
    log.info("fitbit import: received %d bytes (%s) weight_unit=%s",
             len(payload), file.filename, weight_unit)
    zf = _open_zip(payload)
    streams = imp_int.parse_fitbit_zip(zf, weight_unit=weight_unit)
    counts = await _ingest_streams(db, streams)
    return {
        "source": "fitbit", "filename": file.filename, "size_bytes": len(payload),
        "weight_unit": weight_unit, "imported": counts,
    }


@router.post("/garmin")
async def import_garmin(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await file.read()
    log.info("garmin import: received %d bytes (%s)", len(payload), file.filename)
    zf = _open_zip(payload)
    streams = imp_int.parse_garmin_zip(zf)
    counts = await _ingest_streams(db, streams)
    return {"source": "garmin", "filename": file.filename, "size_bytes": len(payload), "imported": counts}
