from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..schemas import AnnotationCreate, AnnotationOut, AnnotationUpdate

router = APIRouter(dependencies=[Depends(require_query)])


@router.post("/log", response_model=AnnotationOut, status_code=201)
async def create_annotation(
    body: AnnotationCreate,
    db: AsyncSession = Depends(get_session),
) -> AnnotationOut:
    row = models.Annotation(
        ts=body.ts or datetime.now(timezone.utc),
        type=body.type,
        payload=body.payload,
        note=body.note,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return AnnotationOut(
        id=row.id, ts=row.ts, type=row.type, payload=row.payload, note=row.note
    )


@router.get("/log", response_model=list[AnnotationOut])
async def list_annotations(
    since: datetime | None = Query(None),
    type: str | None = Query(None, description="filter by annotation type"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
) -> list[AnnotationOut]:
    cutoff = since or (datetime.now(timezone.utc) - timedelta(days=7))
    stmt = (
        select(models.Annotation)
        .where(models.Annotation.ts >= cutoff)
        .order_by(models.Annotation.ts.desc())
        .limit(limit)
    )
    if type:
        stmt = stmt.where(models.Annotation.type == type)

    result = await db.execute(stmt)
    return [
        AnnotationOut(id=r.id, ts=r.ts, type=r.type, payload=r.payload, note=r.note)
        for r in result.scalars().all()
    ]


@router.patch("/log/{annotation_id}", response_model=AnnotationOut)
async def update_annotation(
    annotation_id: int,
    body: AnnotationUpdate,
    db: AsyncSession = Depends(get_session),
) -> AnnotationOut:
    row = await db.get(models.Annotation, annotation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="annotation not found")
    data = body.model_dump(exclude_unset=True)
    if "ts" in data and data["ts"] is not None:
        row.ts = data["ts"]
    if "payload" in data and data["payload"] is not None:
        row.payload = data["payload"]
    if "note" in data:
        row.note = data["note"]
    await db.commit()
    await db.refresh(row)
    return AnnotationOut(id=row.id, ts=row.ts, type=row.type, payload=row.payload, note=row.note)


@router.delete("/log/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: int,
    db: AsyncSession = Depends(get_session),
) -> None:
    row = await db.get(models.Annotation, annotation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="annotation not found")
    await db.delete(row)
    await db.commit()
