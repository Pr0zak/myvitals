"""Streaming historical imports from Fitbit / Garmin account-data ZIPs.

The upload is streamed to a temp file on disk so the full ZIP never has to
sit in RAM. The parser then yields per-entry batches that we flush to
Postgres immediately, committing every COMMIT_EVERY rows so a failure
mid-import doesn't lose all progress.

Each import creates a row in the import_jobs table that's updated as
progress is made, so the UI can poll /import/jobs to see live status.
The progress writes use a separate session so they're visible from
outside the long ingest transaction.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import traceback
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import SessionLocal, get_session
from ..integrations import fit_tracks
from ..integrations import imports as imp_int
from .ingest import _bulk_upsert

log = logging.getLogger(__name__)
router = APIRouter(prefix="/import", dependencies=[Depends(require_query)])

_UPLOAD_CHUNK = 1 << 20

_STREAM_MAP: dict[str, tuple[type, list[str]]] = {
    "heartrate": (models.HeartRate, ["time"]),
    "hrv": (models.Hrv, ["time"]),
    "steps": (models.Steps, ["time"]),
    "sleep_stages": (models.SleepStage, ["time", "stage"]),
    "body_metrics": (models.BodyMetric, ["time"]),
    "skin_temp": (models.SkinTemp, ["time"]),
}

_COMMIT_EVERY = 20_000
# Update the visible job-progress row every N rows. Writes from a separate
# session so the running ingest's open transaction doesn't hide them.
_PROGRESS_EVERY = 5_000


async def _save_upload_to_tmp(file: UploadFile) -> str:
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


async def _create_job(kind: str, filename: str | None, size_bytes: int | None) -> int:
    async with SessionLocal() as s:
        job = models.ImportJob(
            kind=kind, filename=filename, size_bytes=size_bytes,
            status="running", started_at=datetime.now(timezone.utc),
            counts={},
        )
        s.add(job)
        await s.commit()
        return job.id


async def _update_job_counts(job_id: int, counts: dict[str, int]) -> None:
    async with SessionLocal() as s:
        job = await s.get(models.ImportJob, job_id)
        if job:
            job.counts = dict(counts)
            await s.commit()


async def _finish_job(
    job_id: int, status: str, counts: dict[str, int], error: str | None = None,
) -> None:
    async with SessionLocal() as s:
        job = await s.get(models.ImportJob, job_id)
        if job:
            job.status = status
            job.counts = dict(counts)
            job.error = error
            job.finished_at = datetime.now(timezone.utc)
            await s.commit()


async def _upsert_activities_chunk(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
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
    job_id: int | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    rows_since_commit = 0
    rows_since_progress = 0
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
        rows_since_progress += len(samples)
        if rows_since_commit >= _COMMIT_EVERY:
            await db.commit()
            rows_since_commit = 0
            log.info("partial commit: %s", dict(counts))
        if job_id is not None and rows_since_progress >= _PROGRESS_EVERY:
            await _update_job_counts(job_id, counts)
            rows_since_progress = 0
    await db.commit()
    if job_id is not None:
        await _update_job_counts(job_id, counts)
    return dict(counts)


async def _run_import(
    kind: str, file: UploadFile, db: AsyncSession,
    parser_factory,
) -> dict[str, Any]:
    """Wraps the upload→parse→ingest flow with job tracking + cleanup."""
    tmp_path = await _save_upload_to_tmp(file)
    size = os.path.getsize(tmp_path)
    job_id = await _create_job(kind=kind, filename=file.filename, size_bytes=size)
    counts: dict[str, int] = {}
    try:
        try:
            zf = zipfile.ZipFile(tmp_path)
        except zipfile.BadZipFile as e:
            await _finish_job(job_id, "failed", {}, error=str(e))
            raise HTTPException(status_code=400, detail=f"not a valid zip: {e}") from e
        try:
            counts = await _stream_ingest(db, parser_factory(zf), job_id=job_id)
        finally:
            zf.close()
        await _finish_job(job_id, "done", counts)
        return {
            "job_id": job_id, "filename": file.filename,
            "size_bytes": size, "imported": counts,
        }
    except HTTPException:
        raise
    except Exception:
        tb = traceback.format_exc()
        log.exception("import %s job %d failed", kind, job_id)
        await _finish_job(job_id, "failed", counts, error=tb)
        raise HTTPException(status_code=500, detail=f"import failed: see /import/jobs/{job_id}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/fitbit")
async def import_fitbit(
    file: UploadFile = File(...),
    weight_unit: str = Query("kg", pattern="^(kg|lb)$"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _run_import(
        "fitbit", file, db,
        lambda zf: imp_int.parse_fitbit_zip(zf, weight_unit=weight_unit),
    ) | {"weight_unit": weight_unit, "source": "fitbit"}


@router.post("/garmin")
async def import_garmin(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _run_import(
        "garmin", file, db, imp_int.parse_garmin_zip,
    ) | {"source": "garmin"}


# --- Garmin FIT tracks (background job) ------------------------------

# How often to commit DB updates and refresh the visible job-progress row
# while walking the inner FIT zip. 100 files per checkpoint keeps each
# transaction fast and the UI ticking once every couple of seconds.
_FIT_CHECKPOINT_EVERY = 100


async def _process_one_fit(
    db: AsyncSession,
    zf: zipfile.ZipFile,
    name: str,
    counts: dict[str, int],
    activity_index: list[tuple[float, str]],
    activity_epochs: list[float],
) -> None:
    """Parse one FIT file: attach polyline to its activity row (matched by
    start_time, since Garmin FIT filenames use uploadId not activityId)
    and bulk-upsert any per-second HR samples into vitals_heartrate."""
    import bisect
    from datetime import timezone as _tz

    counts["processed"] += 1
    try:
        with zf.open(name) as f:
            data = f.read()
        track = await asyncio.to_thread(fit_tracks.parse_fit_track, data)
    except Exception as e:
        log.warning("FIT parse %s: %s", name, e)
        counts["skipped"] += 1
        return

    has_polyline = bool(track.get("polyline"))
    hr_samples = track.get("hr_samples") or []

    # 1. Bulk-upsert per-second HR samples — these flow in regardless of
    # whether the FIT had GPS (strength training, indoor cardio, etc.
    # have HR but no track). PK is `time` so existing Fitbit samples win
    # on collision; quiet years where Fitbit had no coverage get filled.
    if hr_samples:
        rows = [
            {
                "time": (ts.replace(tzinfo=_tz.utc) if ts.tzinfo is None else ts),
                "bpm": float(bpm),
                "source": "garmin",
            }
            for ts, bpm in hr_samples
        ]
        await _bulk_upsert(db, models.HeartRate, rows, ["time"])
        counts["hr_samples"] = counts.get("hr_samples", 0) + len(rows)

    # 2. Polyline → activities row, time-matched to nearest start_at within ±60s.
    if not has_polyline:
        return
    counts["with_track"] += 1

    start = track.get("start_time")
    if start is None:
        counts["unmatched_no_time"] = counts.get("unmatched_no_time", 0) + 1
        return
    target_epoch = (
        start.replace(tzinfo=_tz.utc).timestamp() if start.tzinfo is None
        else start.timestamp()
    )
    idx = bisect.bisect_left(activity_epochs, target_epoch)
    candidates: list[tuple[float, str]] = []
    if idx < len(activity_index):
        candidates.append(activity_index[idx])
    if idx > 0:
        candidates.append(activity_index[idx - 1])
    best = min(candidates, key=lambda x: abs(x[0] - target_epoch), default=None)
    if best is None or abs(best[0] - target_epoch) > 60:
        counts["unmatched"] = counts.get("unmatched", 0) + 1
        return

    r = await db.execute(
        update(models.Activity)
        .where(models.Activity.source == "garmin")
        .where(models.Activity.source_id == best[1])
        .values(polyline=track["polyline"])
    )
    if r.rowcount:
        counts["matched"] += 1


async def _walk_zip(
    db: AsyncSession, zf: zipfile.ZipFile, job_id: int, counts: dict[str, int],
) -> None:
    """Process one ZIP: parse any FIT files at the top level, and recurse
    into any nested *.zip whose path looks like Garmin's uploaded-files
    archive. Commits + refreshes the visible job-progress row every
    _FIT_CHECKPOINT_EVERY files."""
    import io as _io

    # Build a sorted (epoch, source_id) index of all garmin activities so
    # each FIT file can match by start_time in O(log n).
    rows = (await db.execute(
        select(models.Activity.source_id, models.Activity.start_at)
        .where(models.Activity.source == "garmin")
    )).all()
    activity_index: list[tuple[float, str]] = sorted(
        ((r[1].timestamp(), r[0]) for r in rows), key=lambda x: x[0],
    )
    activity_epochs = [e for e, _ in activity_index]
    log.info("FIT tracks: %d garmin activities indexed for time-matching", len(activity_index))

    fits = [n for n in zf.namelist() if n.lower().endswith(".fit")]
    nested = [
        n for n in zf.namelist()
        if n.lower().endswith(".zip")
        and ("uploadedfiles" in n.lower() or "uploaded-files" in n.lower())
    ]

    since_ckpt = 0
    for name in fits:
        await _process_one_fit(db, zf, name, counts, activity_index, activity_epochs)
        since_ckpt += 1
        if since_ckpt >= _FIT_CHECKPOINT_EVERY:
            await db.commit()
            await _update_job_counts(job_id, counts)
            since_ckpt = 0

    for nz in nested:
        log.info("FIT tracks: recursing into nested %s", nz)
        with zf.open(nz) as f:
            data = f.read()
        with zipfile.ZipFile(_io.BytesIO(data)) as inner:
            inner_fits = [n for n in inner.namelist() if n.lower().endswith(".fit")]
            for name in inner_fits:
                await _process_one_fit(db, inner, name, counts, activity_index, activity_epochs)
                since_ckpt += 1
                if since_ckpt >= _FIT_CHECKPOINT_EVERY:
                    await db.commit()
                    await _update_job_counts(job_id, counts)
                    since_ckpt = 0


async def _process_fit_tracks_job(tmp_path: str, job_id: int) -> None:
    """Background task: walk the upload (which can be either a flat zip
    of FIT files or the full Garmin archive containing nested
    UploadedFiles_*.zip), attach polylines to matching activities."""
    counts = {"processed": 0, "with_track": 0, "matched": 0, "skipped": 0}
    try:
        async with SessionLocal() as db:
            with zipfile.ZipFile(tmp_path) as zf:
                await _walk_zip(db, zf, job_id, counts)
            await db.commit()
        await _finish_job(job_id, "done", counts)
    except Exception:
        tb = traceback.format_exc()
        log.exception("FIT tracks job %d failed", job_id)
        await _finish_job(job_id, "failed", counts, error=tb)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/garmin/tracks", status_code=202)
async def import_garmin_tracks(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Process the inner UploadedFiles_*.zip from a Garmin export.

    21,000+ FIT files is a 15-30 minute job, so we save the upload, kick
    off a background task, and return immediately with a job_id the UI
    can poll on /import/jobs.
    """
    tmp_path = await _save_upload_to_tmp(file)
    size = os.path.getsize(tmp_path)
    job_id = await _create_job(
        kind="garmin_fit_tracks", filename=file.filename, size_bytes=size,
    )
    asyncio.create_task(_process_fit_tracks_job(tmp_path, job_id))
    return {
        "job_id": job_id, "status": "queued",
        "filename": file.filename, "size_bytes": size,
        "message": f"Processing in background — poll /import/jobs/{job_id}",
    }


# --- Job status -------------------------------------------------------

@router.get("/jobs")
async def list_jobs(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List recent import jobs, newest first."""
    rows = (await db.execute(
        select(models.ImportJob).order_by(models.ImportJob.started_at.desc()).limit(limit)
    )).scalars().all()
    return [_job_dict(j) for j in rows]


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: int, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await db.get(models.ImportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_dict(job)


def _job_dict(job: models.ImportJob) -> dict[str, Any]:
    elapsed_s: float | None = None
    end = job.finished_at or datetime.now(timezone.utc)
    if job.started_at:
        elapsed_s = (end - job.started_at).total_seconds()
    total_rows = sum(job.counts.values()) if job.counts else 0
    return {
        "id": job.id,
        "kind": job.kind,
        "filename": job.filename,
        "size_bytes": job.size_bytes,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "elapsed_s": elapsed_s,
        "counts": job.counts or {},
        "total_rows": total_rows,
        "error": job.error,
    }
