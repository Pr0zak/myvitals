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
from ..integrations import strength_import as strimp
from .ingest import _bulk_upsert

log = logging.getLogger(__name__)
router = APIRouter(prefix="/import", dependencies=[Depends(require_query)])

_UPLOAD_CHUNK = 1 << 20

_STREAM_MAP: dict[str, tuple[type, list[str]]] = {
    "heartrate": (models.HeartRate, ["time"]),
    "hrv": (models.Hrv, ["time"]),
    "steps": (models.Steps, ["time"]),
    "sleep_stages": (models.SleepStage, ["time", "stage"]),
    "sleep_sessions": (models.SleepSession, ["start_at"]),
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
    # This is the one Activity writer that does NOT go through
    # integrations/activity_sink.py, deliberately. A historical import is
    # thousands of rows, and the sink is row-at-a-time because it runs the
    # ingest side-effects (cardio-day completion, trail auto-linking) per
    # activity — neither of which you want fired retroactively for a
    # three-year backfill, and both of which would make the import crawl.
    #
    # What it does share is the sink's column allowlist, so "which columns
    # may a provider write" is decided in exactly one place. On top of that
    # this path also excludes `polyline`, because activity tracks are
    # attached separately by the FIT/GPS job and including the column here
    # wiped every restored map on the next import — that is what erased the
    # Garmin tracks before.
    #
    # The one rule it cannot honour is the sink's skip-None: a single bulk
    # statement covers many rows, so there is no per-row notion of "this
    # provider had nothing to say about that field". Import parsers must
    # therefore emit complete rows.
    from ..integrations.activity_sink import PROVIDER_COLUMNS

    writable = set(PROVIDER_COLUMNS) - {"polyline"}
    update_cols = {c.name: c for c in stmt.excluded if c.name in writable}
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


def _parse_date_param(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("/fitbit")
async def import_fitbit(
    file: UploadFile = File(...),
    weight_unit: str = Query("kg", pattern="^(kg|lb)$"),
    activities_only: bool = Query(False, description="Import only exercise records, skip vitals"),
    since: str | None = Query(None, description="ISO date; only import exercises on/after this"),
    until: str | None = Query(None, description="ISO date; only import exercises strictly before this"),
    types: str | None = Query(None, description="Comma-separated substrings; keep only matching activity types (e.g. bik,cycl)"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    since_dt = _parse_date_param(since)
    until_dt = _parse_date_param(until)
    type_subs = [t.strip().lower() for t in types.split(",") if t.strip()] if types else None
    return await _run_import(
        "fitbit", file, db,
        lambda zf: imp_int.parse_fitbit_zip(
            zf, weight_unit=weight_unit, activities_only=activities_only,
            since=since_dt, until=until_dt, type_substrings=type_subs,
        ),
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


# --- Fitbit GPS tracks (background job) ------------------------------

async def _process_fitbit_tracks_job(tmp_path: str, job_id: int) -> None:
    """Attach GPS polylines to fitbit activities from a Takeout's
    gps_location_*.csv track files. Fitbit + gps timestamps are both UTC, so
    each activity's [start, start+duration] window selects its points; the
    polyline is written only (never wiped) so it survives future imports."""
    import bisect
    import polyline as polyline_lib

    counts: dict[str, int] = {"gps_points": 0, "activities_scanned": 0, "matched": 0}
    try:
        with zipfile.ZipFile(tmp_path) as zf:
            pts = imp_int.parse_fitbit_gps_tracks(zf)
        counts["gps_points"] = len(pts)
        eps = [p[0] for p in pts]
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(models.Activity.source_id, models.Activity.start_at,
                       models.Activity.duration_s)
                .where(models.Activity.source == "fitbit")
            )).all()
            for sid, start_at, dur in rows:
                counts["activities_scanned"] += 1
                ep = int(start_at.timestamp())
                dur = dur or 0
                lo = bisect.bisect_left(eps, ep - 60)
                hi = bisect.bisect_right(eps, ep + max(dur, 300) + 60)
                seg = pts[lo:hi]
                if len(seg) < 10:
                    continue
                poly = polyline_lib.encode(
                    [(la, lon) for _, la, lon in seg], precision=5)
                await db.execute(
                    update(models.Activity)
                    .where(models.Activity.source == "fitbit")
                    .where(models.Activity.source_id == sid)
                    .values(polyline=poly)
                )
                counts["matched"] += 1
            await db.commit()
        await _finish_job(job_id, "done", counts)
    except Exception:
        tb = traceback.format_exc()
        log.exception("fitbit tracks job %d failed", job_id)
        await _finish_job(job_id, "failed", counts, error=tb)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/fitbit/tracks", status_code=202)
async def import_fitbit_tracks(file: UploadFile = File(...)) -> dict[str, Any]:
    """Attach GPS maps to fitbit activities from a Fitbit/Google Takeout's
    gps_location_*.csv files (the exercise JSON is summary-only). Background
    job — poll /import/jobs/<id>."""
    tmp_path = await _save_upload_to_tmp(file)
    size = os.path.getsize(tmp_path)
    job_id = await _create_job(
        kind="fitbit_gps_tracks", filename=file.filename, size_bytes=size,
    )
    asyncio.create_task(_process_fitbit_tracks_job(tmp_path, job_id))
    return {
        "job_id": job_id, "status": "queued",
        "filename": file.filename, "size_bytes": size,
        "message": f"Processing in background — poll /import/jobs/{job_id}",
    }


# --- Strength-log import (Strong / Hevy / FitNotes CSV) — IMPORT-1 ----

@router.post("/strength")
async def import_strength_log(
    file: UploadFile = File(...),
    source: str | None = Query(default=None),
    strong_unit: str = Query(default="kg"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Import a Strong / Hevy / FitNotes CSV export as historical strength
    workouts. Web-only (require_query). Synchronous — these exports are small
    single CSVs. Idempotent: re-importing the same export skips sessions
    already present, matched by a deterministic per-session seed.

    `source` may be given explicitly ("strong"/"hevy"/"fitnotes") or is sniffed
    from the header. `strong_unit` (kg|lb) resolves Strong's unitless weight
    column; Hevy is always kg and FitNotes is self-describing per row."""
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:  # strength CSVs are small; guard the RAM buffer
        raise HTTPException(413, "File too large (max 25 MB for a strength CSV).")
    text = raw.decode("utf-8", errors="replace").lstrip("﻿")
    if not text.strip():
        raise HTTPException(422, "Empty file.")
    _, header = strimp._sniff(text)
    src = ((source or "").strip().lower() or strimp.detect_source(header) or "")
    if src not in ("strong", "hevy", "fitnotes"):
        raise HTTPException(
            422, "Unrecognized export. Supported: Strong, Hevy, or FitNotes CSV. "
                 "(Apple Health exports carry no per-set data — export from "
                 "Strong or Hevy instead.)")
    unit = "kg" if strong_unit.lower().startswith("kg") else "lb"
    try:
        rows = strimp.parse_rows(text, src, strong_unit=unit)
        sessions = strimp.group_sessions(rows, src)
    except (csv.Error, ValueError) as e:
        raise HTTPException(422, f"Could not parse the CSV: {e}") from e
    if not sessions:
        raise HTTPException(422, "No logged sets found in the file.")

    job_id = await _create_job(f"strength_{src}", file.filename, len(raw))
    counts = {"workouts": 0, "sets": 0, "skipped_duplicates": 0,
              "unmatched_exercises": 0}
    unmatched: set[str] = set()
    try:
        for sess in sessions:
            dup = (await db.execute(
                select(models.StrengthWorkout.id)
                .where(models.StrengthWorkout.seed == sess["seed"])
            )).first()
            if dup:
                counts["skipped_duplicates"] += 1
                continue
            when = sess["when"]
            w = models.StrengthWorkout(
                date=sess["date"],
                # Date generated_at to the session itself (not now) so an
                # imported historical workout never wins /today's "newest
                # generated_at" selection and shadows the real generated plan.
                generated_at=(when or datetime.now(timezone.utc)),
                split_focus="imported",
                status="completed",
                seed=sess["seed"],
                started_at=when,
                completed_at=when,
                notes=(sess["workout"] if sess["workout"] != "Imported" else None),
            )
            db.add(w)
            await db.flush()
            for oi, ex in enumerate(sess["exercises"]):
                working = [s for s in ex["sets"]
                           if s["set_type"] != "warmup" and s["reps"]]
                rep_pool = [s["reps"] for s in (working or ex["sets"]) if s["reps"]]
                w_pool = [s["weight_lb"] for s in ex["sets"] if s["weight_lb"]]
                if not ex["matched"]:
                    unmatched.add(ex["exercise"])
                wex = models.StrengthWorkoutExercise(
                    workout_id=w.id,
                    exercise_id=ex["exercise_id"],
                    order_index=oi,
                    superset_id=(str(ex["superset"])[:16] if ex.get("superset")
                                 else None),
                    target_sets=len(working) or len(ex["sets"]),
                    target_reps_low=min(rep_pool) if rep_pool else 0,
                    target_reps_high=max(rep_pool) if rep_pool else 0,
                    target_weight_lb=max(w_pool) if w_pool else None,
                    notes=(None if ex["matched"]
                           else f"imported: {ex['exercise']}"[:500]),
                )
                db.add(wex)
                await db.flush()
                for s in ex["sets"]:
                    db.add(models.StrengthSet(
                        workout_exercise_id=wex.id,
                        set_number=s["set_number"],
                        target_weight_lb=s["weight_lb"],
                        target_reps=s["reps"] or 0,
                        actual_weight_lb=s["weight_lb"],
                        actual_reps=s["reps"],
                        rating=s.get("rating"),
                        set_type=s["set_type"],
                        logged_at=s.get("when"),
                    ))
                    counts["sets"] += 1
            counts["workouts"] += 1
        await db.commit()
        counts["unmatched_exercises"] = len(unmatched)
        await _finish_job(job_id, "done", counts)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        await _finish_job(job_id, "error", counts, error=str(e)[:500])
        raise HTTPException(500, f"Import failed: {e}") from e
    return {"source": src, **counts, "unmatched_names": sorted(unmatched)[:50]}


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
