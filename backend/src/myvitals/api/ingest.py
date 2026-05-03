from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_ingest
from ..db import models
from ..db.session import get_session

router = APIRouter(dependencies=[Depends(require_ingest)])


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
        stmt = insert(models.HeartRate).values(
            [s.model_dump() for s in batch.heartrate]
        ).on_conflict_do_nothing(index_elements=["time"])
        await db.execute(stmt)
        counts["heartrate"] = len(batch.heartrate)

    if batch.hrv:
        stmt = insert(models.Hrv).values(
            [s.model_dump() for s in batch.hrv]
        ).on_conflict_do_nothing(index_elements=["time"])
        await db.execute(stmt)
        counts["hrv"] = len(batch.hrv)

    if batch.steps:
        stmt = insert(models.Steps).values(
            [s.model_dump() for s in batch.steps]
        ).on_conflict_do_nothing(index_elements=["time"])
        await db.execute(stmt)
        counts["steps"] = len(batch.steps)

    if batch.sleep_stages:
        stmt = insert(models.SleepStage).values(
            [s.model_dump() for s in batch.sleep_stages]
        ).on_conflict_do_nothing(index_elements=["time", "stage"])
        await db.execute(stmt)
        counts["sleep_stages"] = len(batch.sleep_stages)

    if batch.workouts:
        stmt = insert(models.Workout).values(
            [w.model_dump() for w in batch.workouts]
        ).on_conflict_do_nothing(index_elements=["time"])
        await db.execute(stmt)
        counts["workouts"] = len(batch.workouts)

    await db.commit()
    return counts
