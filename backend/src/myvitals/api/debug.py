from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_ingest, require_query
from ..db import models
from ..db.session import get_session

router = APIRouter()


class LogIn(BaseModel):
    ts: datetime
    level: str = Field(..., description="VERBOSE | DEBUG | INFO | WARN | ERROR")
    tag: str | None = None
    message: str
    stack: str | None = None


class LogBatch(BaseModel):
    source: str = Field("phone", description="phone | server | other")
    entries: list[LogIn]


class LogOut(BaseModel):
    id: int
    ts: datetime
    source: str
    level: str
    tag: str | None
    message: str
    stack: str | None


@router.post("/debug/logs", status_code=202, dependencies=[Depends(require_ingest)])
async def post_logs(
    batch: LogBatch,
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    if not batch.entries:
        return {"received": 0}

    now = datetime.now(timezone.utc)
    rows = [
        models.AppLog(
            ts=e.ts,
            source=batch.source,
            level=e.level.upper(),
            tag=e.tag,
            message=e.message,
            stack=e.stack,
            received_at=now,
        )
        for e in batch.entries
    ]
    db.add_all(rows)
    await db.commit()
    return {"received": len(rows)}


@router.get("/debug/logs", response_model=list[LogOut], dependencies=[Depends(require_query)])
async def list_logs(
    since: datetime | None = Query(None),
    source: str | None = Query(None, description="filter: phone | server"),
    level: str | None = Query(None, description="min level: DEBUG/INFO/WARN/ERROR"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> list[LogOut]:
    cutoff = since or (datetime.now(timezone.utc) - timedelta(hours=24))
    stmt = (
        select(models.AppLog)
        .where(models.AppLog.ts >= cutoff)
        .order_by(models.AppLog.ts.desc())
        .limit(limit)
    )
    if source:
        stmt = stmt.where(models.AppLog.source == source)
    if level:
        # Simple severity ordering: WARN >= INFO >= DEBUG. Match this exact level + above.
        order = ["VERBOSE", "DEBUG", "INFO", "WARN", "ERROR"]
        try:
            min_idx = order.index(level.upper())
            stmt = stmt.where(models.AppLog.level.in_(order[min_idx:]))
        except ValueError:
            pass

    result = await db.execute(stmt)
    return [
        LogOut(
            id=r.id, ts=r.ts, source=r.source, level=r.level,
            tag=r.tag, message=r.message, stack=r.stack,
        )
        for r in result.scalars().all()
    ]
