"""Streaming historical imports from Fitbit / Garmin account-data ZIPs.

The upload is streamed to a temp file on disk so the full ZIP never has to
sit in RAM. The parser then yields per-entry batches that we flush to
Postgres immediately, committing every COMMIT_EVERY rows so a failure
mid-import doesn't lose all progress.
"""
from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Iterator
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

# Read upload from the network in 1 MiB chunks. Bigger means fewer write
# syscalls but more RAM held by the buffer; 1 MiB is the sweet spot.
_UPLOAD_CHUNK = 1 << 20

# Stream → (model, conflict-cols). Activities are special-cased below.
_STREAM_MAP: dict[str, tuple[type, list[str]]] = {
    "heartrate": (models.HeartRate, ["time"]),
    "hrv": (models.Hrv, ["time"]),
    "steps": (models.Steps, ["time"]),
    "sleep_stages": (models.SleepStage, ["time", "stage"]),
    "body_metrics": (models.BodyMetric, ["time"]),
    "skin_temp": (models.SkinTemp, ["time"]),
}

# Commit every N total rows so a long import doesn't sit in one giant txn.
_COMMIT_EVERY = 20_000


async def _save_upload_to_tmp(file: UploadFile) -> str:
    """Stream the upload to a NamedTemporaryFile and return the path."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", prefix="myvitals_import_")
    total = 0
    try:
        while True:
            chunk = await file.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            tmp.write(chunk)
            total += len(chunk)
        tmp.flush()
    finally:
        tmp.close()
    log.info("import upload saved: %s (%.1f MB)", tmp.name, total / (1 << 20))
    return tmp.name


async def _upsert_activities_chunk(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Upsert a single activities batch, preserving user-edited notes/tags."""
    if not rows:
        return
    stmt = insert(models.Activity).values(rows)
    update_cols = {
        c.name: c for c in stmt.excluded
        if c.name not in ("source", "source_id", "notes", "tags")
    }
    stmt = stmt.on_conflict_do_update(index_elements=["source", "source_id"], set_=update_cols)
    await db.execute(stmt)


async def _stream_ingest(
    db: AsyncSession,
    parser: Iterator[tuple[str, list[dict[str, Any]]]],
) -> dict[str, int]:
    """Drive the parser generator, flushing each batch as it arrives."""
    counts: dict[str, int] = defaultdict(int)
    rows_since_commit = 0
    for stream, samples in parser:
        if not samples:
            continue
        if stream == "activities":
            await _upsert_activities_chunk(db, samples)
        else:
            entry = _STREAM_MAP.get(stream)
            if not entry:
                log.warning("unknown stream %r — dropping %d rows", stream, len(samples))
                continue
            await _bulk_upsert(db, entry[0], samples, entry[1])
        counts[stream] += len(samples)
        rows_since_commit += len(samples)
        if rows_since_commit >= _COMMIT_EVERY:
            await db.commit()
            rows_since_commit = 0
            log.info("partial commit: %s", dict(counts))
    await db.commit()
    return dict(counts)


@router.post("/fitbit")
async def import_fitbit(
    file: UploadFile = File(...),
    weight_unit: str = Query("kg", pattern="^(kg|lb)$"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tmp_path = await _save_upload_to_tmp(file)
    try:
        try:
            zf = zipfile.ZipFile(tmp_path)
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=400, detail=f"not a valid zip: {e}") from e
        try:
            counts = await _stream_ingest(
                db, imp_int.parse_fitbit_zip(zf, weight_unit=weight_unit),
            )
        finally:
            zf.close()
        return {
            "source": "fitbit", "filename": file.filename,
            "size_bytes": os.path.getsize(tmp_path),
            "weight_unit": weight_unit, "imported": counts,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/garmin")
async def import_garmin(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    tmp_path = await _save_upload_to_tmp(file)
    try:
        try:
            zf = zipfile.ZipFile(tmp_path)
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=400, detail=f"not a valid zip: {e}") from e
        try:
            counts = await _stream_ingest(db, imp_int.parse_garmin_zip(zf))
        finally:
            zf.close()
        return {
            "source": "garmin", "filename": file.filename,
            "size_bytes": os.path.getsize(tmp_path),
            "imported": counts,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


