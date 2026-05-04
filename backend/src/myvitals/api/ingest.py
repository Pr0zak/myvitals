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

router = APIRouter(dependencies=[Depends(require_ingest)])

# Postgres caps a single statement at 32767 bind parameters. Each row in our
# widest insert (workouts, 7 cols) takes 7 params, so 4000 rows stays comfortably
# under the limit for all tables.
_CHUNK = 4000


def _chunked(items: list[Any], size: int = _CHUNK) -> Iterator[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _bulk_upsert(
    db: AsyncSession,
    table: type,
    rows: Iterable[dict[str, Any]],
    conflict_cols: list[str],
) -> None:
    """Insert in CHUNK-sized batches; on duplicate (conflict_cols) do nothing."""
    for chunk in _chunked(list(rows)):
        stmt = insert(table).values(chunk).on_conflict_do_nothing(
            index_elements=conflict_cols
        )
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


class Batch(BaseModel):
    heartrate: list[HeartRateSample] = []
    hrv: list[HrvSample] = []
    steps: list[StepsSample] = []
    sleep_stages: list[SleepStageSample] = []
    workouts: list[WorkoutSample] = []


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
                           (s.model_dump() for s in batch.steps), ["time"])
        counts["steps"] = len(batch.steps)

    if batch.sleep_stages:
        await _bulk_upsert(db, models.SleepStage,
                           (s.model_dump() for s in batch.sleep_stages), ["time", "stage"])
        counts["sleep_stages"] = len(batch.sleep_stages)

    if batch.workouts:
        await _bulk_upsert(db, models.Workout,
                           (w.model_dump() for w in batch.workouts), ["time"])
        counts["workouts"] = len(batch.workouts)

    await db.commit()
    return counts
