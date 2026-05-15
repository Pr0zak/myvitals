"""Device-status read endpoints + HA config CRUD — fronts the
device_status hypertable populated by the HA WebSocket consumer
and exposes the singleton ha_config row to Settings.

Auth via the existing query/ingest token plumbing (same as /query/*)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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


class HaConfigOut(BaseModel):
    url: str | None
    token_masked: str | None    # never echo the token plaintext
    realtime_enabled: bool
    device_id: str
    updated_at: str | None
    configured: bool             # both url + token present


class HaConfigIn(BaseModel):
    url: str | None = None
    token: str | None = None    # if omitted, keep existing; pass "" to clear
    realtime_enabled: bool | None = None
    device_id: str | None = None


def _mask(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "•" * len(token)
    return token[:3] + "•••" + token[-4:]


@router.get("/ha-config", response_model=HaConfigOut)
async def get_ha_config(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await db.get(models.HaConfig, 1)
    if row is None:
        return {
            "url": None, "token_masked": None, "realtime_enabled": False,
            "device_id": "pixel_watch_3", "updated_at": None, "configured": False,
        }
    return {
        "url": row.url,
        "token_masked": _mask(row.token),
        "realtime_enabled": row.realtime_enabled,
        "device_id": row.device_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "configured": bool(row.url and row.token),
    }


@router.put("/ha-config", response_model=HaConfigOut)
async def put_ha_config(
    body: HaConfigIn, db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    existing = await db.get(models.HaConfig, 1)
    if existing is None:
        existing = models.HaConfig(
            id=1, realtime_enabled=False, device_id="pixel_watch_3",
            updated_at=datetime.now(timezone.utc),
        )
        db.add(existing)
    if body.url is not None:
        existing.url = body.url.strip() or None
    if body.token is not None:
        # Empty string explicitly clears; None means "keep current".
        existing.token = body.token if body.token.strip() else None
    if body.realtime_enabled is not None:
        existing.realtime_enabled = body.realtime_enabled
    if body.device_id is not None and body.device_id.strip():
        existing.device_id = body.device_id.strip()
    existing.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(existing)
    # HA-9: nudge the in-process consumer to re-read config so a toggle
    # or token update takes effect without a backend restart.
    from ..integrations.ha_realtime import request_restart as _ha_restart
    _ha_restart()
    return {
        "url": existing.url,
        "token_masked": _mask(existing.token),
        "realtime_enabled": existing.realtime_enabled,
        "device_id": existing.device_id,
        "updated_at": existing.updated_at.isoformat(),
        "configured": bool(existing.url and existing.token),
    }


@router.get("/device-status/latest", response_model=DeviceStatusOut)
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


class DeviceStatusPoint(BaseModel):
    time: str
    battery_pct: int | None
    is_charging: bool | None
    activity_state: str | None
    is_worn: bool | None
    online: bool | None


@router.get("/device-status/series")
async def device_status_series(
    device_id: str = Query("pixel_watch_3"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Time-series device_status rows for the /watch dashboard charts.

    Returns the raw row sequence (already dense — the HA consumer copies
    forward unchanged fields), plus aggregates the frontend would compute
    anyway: total on-body time vs off-body, average battery across the
    window, and the most-recent activity_state per discrete state.
    """
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    if since is None:
        since = now - _td(hours=24)
    if until is None:
        until = now
    rows = (await db.execute(
        select(models.DeviceStatus)
        .where(models.DeviceStatus.device_id == device_id)
        .where(models.DeviceStatus.time >= since)
        .where(models.DeviceStatus.time <= until)
        .order_by(models.DeviceStatus.time.asc())
    )).scalars().all()
    points = [
        {
            "time": r.time.isoformat(),
            "battery_pct": r.battery_pct,
            "is_charging": r.is_charging,
            "activity_state": r.activity_state,
            "is_worn": r.is_worn,
            "online": r.online,
        }
        for r in rows
    ]
    # Compute on-body % by integrating is_worn between adjacent rows.
    on_s = 0.0
    off_s = 0.0
    unknown_s = 0.0
    for i in range(len(rows) - 1):
        dt = (rows[i + 1].time - rows[i].time).total_seconds()
        if rows[i].is_worn is True:
            on_s += dt
        elif rows[i].is_worn is False:
            off_s += dt
        else:
            unknown_s += dt
    total = on_s + off_s + unknown_s
    on_pct = (on_s / total * 100.0) if total > 0 else None
    return {
        "device_id": device_id,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "count": len(points),
        "points": points,
        "on_body_pct": on_pct,
        "on_body_seconds": on_s,
        "off_body_seconds": off_s,
        "unknown_seconds": unknown_s,
    }
