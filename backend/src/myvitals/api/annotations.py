from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..schemas import AnnotationCreate, AnnotationOut, AnnotationUpdate

router = APIRouter(dependencies=[Depends(require_query)])


# Backward-compatibility shims: /log/* → /journal/* via 308 redirects.
# Cached frontend bundles or any out-of-tree client still hitting /log
# get redirected to the renamed endpoint instead of a 404. Remove after
# one release once we're sure nothing's still calling /log.
_legacy = APIRouter(dependencies=[Depends(require_query)])


@_legacy.api_route("/log", methods=["GET", "POST"], include_in_schema=False)
async def _log_root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/journal", status_code=308)


@_legacy.api_route(
    "/log/{annotation_id}", methods=["PATCH", "DELETE"], include_in_schema=False,
)
async def _log_item_redirect(annotation_id: int) -> RedirectResponse:
    return RedirectResponse(url=f"/journal/{annotation_id}", status_code=308)


router.include_router(_legacy)


@router.post("/journal", response_model=AnnotationOut, status_code=201)
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


@router.get("/journal", response_model=list[AnnotationOut])
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


@router.patch("/journal/{annotation_id}", response_model=AnnotationOut)
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


@router.delete("/journal/{annotation_id}", status_code=204)
async def delete_annotation(
    annotation_id: int,
    db: AsyncSession = Depends(get_session),
) -> None:
    row = await db.get(models.Annotation, annotation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="annotation not found")
    await db.delete(row)
    await db.commit()
