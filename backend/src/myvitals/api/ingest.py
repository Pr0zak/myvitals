import logging
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_ingest
from ..db import models
from ..db.session import get_session
from ..integrations import activity_sink

router = APIRouter(dependencies=[Depends(require_ingest)])
log = logging.getLogger(__name__)

# Postgres caps a single statement at 32767 bind parameters. Each row in our
# widest insert (workouts, 7 cols) takes 7 params, so 4000 rows stays comfortably
# under the limit for all tables.
_CHUNK = 4000


def _chunked(items: list[Any], size: int = _CHUNK) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _dedupe_on_conflict_key(
    rows: list[dict[str, Any]],
    conflict_cols: list[str],
    table_name: str,
    keep_last: bool,
) -> list[dict[str, Any]]:
    """Collapse rows that share a conflict key, before they reach Postgres.

    Postgres refuses an ``ON CONFLICT DO UPDATE`` whose statement would touch
    the same row twice -- "cannot affect row a second time" -- so one batch
    carrying two rows with a single conflict key fails outright. The phone
    replays a failed batch out of its Room buffer indefinitely, which turns
    that one bad batch into a permanent ingest outage rather than a dropped
    upload. This is not hypothetical: Strava and the Fitbit/Google Health app
    each wrote the same cycling session at the same instant, and because
    `workouts` conflicts on `time` alone, every sync after it failed for
    seventeen hours while WorkManager backed the retries off to hourly.

    Which of the tied rows survives is deliberately whatever Postgres would
    already have done had the pair arrived in separate statements: with
    DO UPDATE the later row overwrites the earlier one, with DO NOTHING the
    first row stands and the rest are skipped. The job here is to stop the
    crash, not to change who wins -- that question belongs to whichever
    table's key is too narrow to hold both readings, and is a schema
    decision, not an ingest one.

    A collapse is logged rather than performed quietly. Discarding a reading
    the user's device genuinely recorded is exactly the kind of thing that
    should leave a trace, and the count is the signal that some table's
    conflict key cannot represent two writers.
    """
    if not rows:
        return rows

    seen: dict[tuple[Any, ...], int] = {}
    out: list[dict[str, Any]] = []
    collapsed = 0
    for row in rows:
        key = tuple(row.get(c) for c in conflict_cols)
        prior = seen.get(key)
        if prior is None:
            seen[key] = len(out)
            out.append(row)
            continue
        collapsed += 1
        if keep_last:
            out[prior] = row

    if collapsed:
        log.warning(
            "ingest: collapsed %d duplicate row(s) on %s(%s) within one batch; "
            "kept the %s of each tie",
            collapsed, table_name, ", ".join(conflict_cols),
            "last" if keep_last else "first",
        )
    return out


async def _bulk_upsert(
    db: AsyncSession,
    table: type,
    rows: Iterable[dict[str, Any]],
    conflict_cols: list[str],
    update_cols: list[str] | None = None,
) -> None:
    """Insert in CHUNK-sized batches.

    Default behaviour: on (conflict_cols) collision, do nothing — vitals
    samples at a given timestamp are immutable.

    If ``update_cols`` is provided, conflicting rows have those columns
    overwritten with the incoming values. Used for tables where ingest can
    legitimately update existing rows (e.g. workouts gained source/title
    columns post-hoc; we want re-syncs to populate them on existing rows).
    """
    deduped = _dedupe_on_conflict_key(
        list(rows), conflict_cols, table.__tablename__, keep_last=bool(update_cols),
    )
    for chunk in _chunked(deduped):
        stmt = insert(table).values(chunk)
        if update_cols:
            excluded = {c: stmt.excluded[c] for c in update_cols}
            stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=excluded)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)
        await db.execute(stmt)


class HeartRateSample(BaseModel):
    time: datetime
    bpm: float
    source: str = "watch"


class HrvSample(BaseModel):
    time: datetime
    rmssd_ms: float


class StepsSample(BaseModel):
    time: datetime
    count: int
    # Health Connect's dataOrigin.packageName (e.g.
    # "com.google.android.apps.fitness", "com.google.android.wearable.app").
    # Defaults to "unknown" so older phone builds without source-tagging
    # still ingest.
    source: str = "unknown"


class SleepStageSample(BaseModel):
    time: datetime
    stage: str
    duration_s: int


class WorkoutSample(BaseModel):
    time: datetime
    type: str
    duration_s: int
    kcal: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    source: str | None = None
    title: str | None = None


class BodyMetricSample(BaseModel):
    time: datetime
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    bmi: float | None = None
    lean_mass_kg: float | None = None
    #: The pipe, not the app. See the model.
    source: str = "manual"
    #: The Android package that authored the record, when known. Optional
    #: so an older phone build keeps posting successfully.
    origin: str | None = None


class SkinTempSample(BaseModel):
    time: datetime
    celsius_delta: float


class SleepSessionSample(BaseModel):
    start: datetime
    end: datetime
    source: str = "watch"
    title: str | None = None


class BloodPressureSample(BaseModel):
    time: datetime
    systolic: int
    diastolic: int
    pulse_bpm: int | None = None
    source: str = "manual"
    notes: str | None = None


class Batch(BaseModel):
    heartrate: list[HeartRateSample] = []
    hrv: list[HrvSample] = []
    steps: list[StepsSample] = []
    sleep_stages: list[SleepStageSample] = []
    workouts: list[WorkoutSample] = []
    body_metrics: list[BodyMetricSample] = []
    skin_temp: list[SkinTempSample] = []
    blood_pressure: list[BloodPressureSample] = []
    sleep_sessions: list[SleepSessionSample] = []


@router.post("/batch")
async def ingest_batch(batch: Batch, db: AsyncSession = Depends(get_session)) -> dict[str, int]:
    counts: dict[str, int] = {}

    if batch.heartrate:
        await _bulk_upsert(db, models.HeartRate,
                           (s.model_dump() for s in batch.heartrate), ["time"])
        counts["heartrate"] = len(batch.heartrate)

    if batch.hrv:
        await _bulk_upsert(db, models.Hrv,
                           (s.model_dump() for s in batch.hrv), ["time"])
        counts["hrv"] = len(batch.hrv)

    if batch.steps:
        await _bulk_upsert(db, models.Steps,
                           (s.model_dump() for s in batch.steps),
                           ["time", "source"])
        counts["steps"] = len(batch.steps)

    if batch.sleep_stages:
        await _bulk_upsert(db, models.SleepStage,
                           (s.model_dump() for s in batch.sleep_stages), ["time", "stage"])
        counts["sleep_stages"] = len(batch.sleep_stages)

    if batch.workouts:
        await _bulk_upsert(
            db,
            models.Workout,
            (w.model_dump() for w in batch.workouts),
            ["time"],
            update_cols=["type", "duration_s", "kcal", "avg_hr", "max_hr", "source", "title"],
        )
        counts["workouts"] = len(batch.workouts)
        # HC-1: promote these into the activities feed. Health Connect
        # exercise sessions have always landed in `workouts`, which nothing
        # user-facing reads, so a session the watch recorded but Strava
        # never saw was invisible. Bounded to the batch window, and skips
        # anything a richer provider already covers.
        try:
            earliest = min(w.time for w in batch.workouts)
            promo = await activity_sink.promote_health_connect_workouts(
                db, since=earliest,
            )
            if promo["promoted"]:
                counts["activities_promoted"] = promo["promoted"]
                log.info(
                    "HC-1 promoted %d session(s) to activities (%d already covered)",
                    promo["promoted"], promo["skipped_overlap"],
                )
        except Exception as e:  # noqa: BLE001
            # Never fail an ingest over the promotion step — the raw
            # samples are the irreplaceable part and are already written.
            log.warning("HC-1 promotion failed: %s", e)

    if batch.body_metrics:
        await _bulk_upsert(db, models.BodyMetric,
                           (b.model_dump() for b in batch.body_metrics), ["time"])
        counts["body_metrics"] = len(batch.body_metrics)

    if batch.skin_temp:
        await _bulk_upsert(db, models.SkinTemp,
                           (s.model_dump() for s in batch.skin_temp), ["time"])
        counts["skin_temp"] = len(batch.skin_temp)

    if batch.blood_pressure:
        await _bulk_upsert(db, models.BloodPressure,
                           (b.model_dump() for b in batch.blood_pressure), ["time"])
        counts["blood_pressure"] = len(batch.blood_pressure)

    if batch.sleep_sessions:
        rows = [
            {"start_at": s.start, "end_at": s.end, "source": s.source, "title": s.title}
            for s in batch.sleep_sessions
        ]
        await _bulk_upsert(db, models.SleepSession, rows, ["start_at"])
        counts["sleep_sessions"] = len(rows)

    await db.commit()
    return counts


class Heartbeat(BaseModel):
    attempt_at: datetime
    success: bool
    permissions_lost: bool = False
    perms_granted: int | None = None
    perms_required: int | None = None
    perms_missing: list[str] | None = None
    last_success_at: datetime | None = None
    error_summary: str | None = None
    records_pulled: int | None = None
    app_version: str | None = None


@router.post("/heartbeat")
async def ingest_heartbeat(
    hb: Heartbeat, db: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    """Companion-app sync diagnostic ping. One row per doWork() invocation."""
    stmt = insert(models.SyncHeartbeat).values(
        attempt_at=hb.attempt_at,
        success=hb.success,
        permissions_lost=hb.permissions_lost,
        perms_granted=hb.perms_granted,
        perms_required=hb.perms_required,
        perms_missing=hb.perms_missing,
        last_success_at=hb.last_success_at,
        error_summary=(hb.error_summary or "")[:1900] or None,
        records_pulled=hb.records_pulled,
        app_version=hb.app_version,
    ).on_conflict_do_nothing(index_elements=["attempt_at"])
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}
