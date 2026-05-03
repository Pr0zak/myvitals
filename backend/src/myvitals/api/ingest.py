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


class Batch(BaseModel):
    heartrate: list[HeartRateSample] = []
    hrv: list[HrvSample] = []
    steps: list[StepsSample] = []


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

    await db.commit()
    return counts
