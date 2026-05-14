"""Device-status read endpoints — fronts the device_status hypertable
populated by the HA WebSocket consumer.

Auth via the existing query/ingest token plumbing (same as /query/*)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session

router = APIRouter(dependencies=[Depends(require_any)])


class DeviceStatusOut(BaseModel):
    device_id: str
    time: str
    battery_pct: int | None
    battery_state: str | None
    is_charging: bool | None
    activity_state: str | None
    is_worn: bool | None
    online: bool | None


@router.get("/api/device-status/latest", response_model=DeviceStatusOut)
async def latest_device_status(
    device_id: str = Query("pixel_watch_3"),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = (await db.execute(
        select(models.DeviceStatus)
        .where(models.DeviceStatus.device_id == device_id)
        .order_by(models.DeviceStatus.time.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"no device_status rows for device_id={device_id!r}",
        )
    return {
        "device_id": row.device_id,
        "time": row.time.isoformat(),
        "battery_pct": row.battery_pct,
        "battery_state": row.battery_state,
        "is_charging": row.is_charging,
        "activity_state": row.activity_state,
        "is_worn": row.is_worn,
        "online": row.online,
    }
