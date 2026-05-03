from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_query
from ..db import models
from ..db.session import get_session
from ..integrations import strava

router = APIRouter()


class StravaStatus(BaseModel):
    connected: bool
    configured: bool
    athlete_id: int | None = None
    athlete_name: str | None = None
    expires_at: datetime | None = None
    last_sync_at: datetime | None = None
    scope: str | None = None


class ActivityOut(BaseModel):
    source: str
    source_id: str
    type: str
    name: str | None
    start_at: datetime
    duration_s: int
    distance_m: float | None
    elevation_gain_m: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_power_w: float | None
    max_power_w: float | None
    kcal: float | None
    suffer_score: float | None
    polyline: str | None


# --- OAuth ---

@router.get("/auth/strava/login")
async def strava_login() -> RedirectResponse:
    """Bounce the browser to Strava's authorize page."""
    if not strava.is_configured():
        raise HTTPException(503, "Strava not configured (set STRAVA_CLIENT_ID / SECRET)")
    return RedirectResponse(url=strava.authorize_url(), status_code=302)


@router.get("/auth/strava/callback")
async def strava_callback(
    code: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Strava redirects here after the user approves; exchange code for tokens."""
    if error or not code:
        raise HTTPException(400, f"Strava callback error: {error or 'no code'}")
    payload = await strava.exchange_code(code)
    await strava.store_initial_credentials(db, payload)
    # Bounce back to the dashboard's settings page.
    return RedirectResponse(url="/settings", status_code=302)


# --- Status + manual control ---

@router.get("/strava/status", response_model=StravaStatus, dependencies=[Depends(require_query)])
async def strava_status(db: AsyncSession = Depends(get_session)) -> StravaStatus:
    creds = await strava.get_credentials(db)
    return StravaStatus(
        configured=strava.is_configured(),
        connected=creds is not None,
        athlete_id=creds.athlete_id if creds else None,
        athlete_name=creds.athlete_name if creds else None,
        expires_at=creds.expires_at if creds else None,
        last_sync_at=creds.last_sync_at if creds else None,
        scope=creds.scope if creds else None,
    )


@router.post("/strava/sync", dependencies=[Depends(require_query)])
async def strava_sync(
    days: int = Query(90, ge=1, le=3650),
) -> dict[str, int]:
    """Force-pull activities from `days` ago. Default 90."""
    after_ts = int(datetime.now(timezone.utc).timestamp()) - days * 86400
    count = await strava.sync_recent(after_ts=after_ts)
    return {"upserted": count, "days": days}


@router.delete("/strava", dependencies=[Depends(require_query)])
async def strava_disconnect(db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Wipe stored Strava credentials. Activities stay."""
    creds = await strava.get_credentials(db)
    if creds is not None:
        await db.delete(creds)
        await db.commit()
    return {"status": "disconnected"}


# --- Read activities (any source) ---

@router.get("/activities", response_model=list[ActivityOut], dependencies=[Depends(require_query)])
async def list_activities(
    since: datetime | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
) -> list[ActivityOut]:
    stmt = (
        select(models.Activity)
        .order_by(models.Activity.start_at.desc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(models.Activity.start_at >= since)
    if type:
        stmt = stmt.where(models.Activity.type == type)
    result = await db.execute(stmt)
    return [
        ActivityOut(
            source=a.source, source_id=a.source_id, type=a.type, name=a.name,
            start_at=a.start_at, duration_s=a.duration_s,
            distance_m=a.distance_m, elevation_gain_m=a.elevation_gain_m,
            avg_hr=a.avg_hr, max_hr=a.max_hr,
            avg_power_w=a.avg_power_w, max_power_w=a.max_power_w,
            kcal=a.kcal, suffer_score=a.suffer_score, polyline=a.polyline,
        )
        for a in result.scalars().all()
    ]
