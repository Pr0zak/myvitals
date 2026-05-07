from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any, require_query
from ..db import models
from ..db.session import get_session
from ..integrations import strava

router = APIRouter()


class StravaStatus(BaseModel):
    connected: bool
    configured: bool
    config_source: str | None = None  # "db" | "env" | None
    athlete_id: int | None = None
    athlete_name: str | None = None
    expires_at: datetime | None = None
    last_sync_at: datetime | None = None
    scope: str | None = None


class StravaAppConfigOut(BaseModel):
    configured: bool
    source: str | None = None  # "db" | "env" | None
    client_id_masked: str | None = None
    callback_url: str | None = None


class StravaAppConfigIn(BaseModel):
    client_id: str
    client_secret: str
    callback_url: str | None = None


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
    notes: str | None = None
    tags: list[str] | None = None
    trail_id: int | None = None
    trail_name: str | None = None


class ActivityNotesIn(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None


class ActivityLinkTrailIn(BaseModel):
    trail_id: int | None = None


class ActivityStatsOut(BaseModel):
    period_label: str
    n_activities: int
    total_distance_m: float
    total_duration_s: int
    total_elevation_m: float
    total_kcal: float
    by_type: dict[str, int]
    streak_days: int
    period_pct_vs_prev: dict[str, float]


def _mask(s: str) -> str:
    if not s:
        return ""
    return f"…{s[-4:]}" if len(s) > 4 else s


# --- App config (dashboard-editable) ---

@router.get("/strava/config", response_model=StravaAppConfigOut, dependencies=[Depends(require_query)])
async def get_strava_config(db: AsyncSession = Depends(get_session)) -> StravaAppConfigOut:
    creds = await strava.get_app_credentials(db)
    if creds is None:
        return StravaAppConfigOut(configured=False)
    return StravaAppConfigOut(
        configured=True,
        source=creds.source,
        client_id_masked=_mask(creds.client_id),
        callback_url=creds.callback_url,
    )


@router.post("/strava/config", dependencies=[Depends(require_query)])
async def save_strava_config(
    body: StravaAppConfigIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if not body.client_id.strip() or not body.client_secret.strip():
        raise HTTPException(400, "client_id and client_secret are required")
    await strava.upsert_app_credentials(
        db, body.client_id, body.client_secret, body.callback_url
    )
    return {"status": "saved"}


@router.delete("/strava/config", dependencies=[Depends(require_query)])
async def clear_strava_config(db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    await strava.clear_app_credentials(db)
    return {"status": "cleared"}


# --- OAuth ---

@router.get("/auth/strava/login")
async def strava_login(db: AsyncSession = Depends(get_session)) -> RedirectResponse:
    creds = await strava.get_app_credentials(db)
    if creds is None:
        raise HTTPException(503, "Strava not configured. Save credentials at /settings first.")
    return RedirectResponse(url=strava.authorize_url(creds), status_code=302)


@router.get("/auth/strava/callback")
async def strava_callback(
    code: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if error or not code:
        raise HTTPException(400, f"Strava callback error: {error or 'no code'}")
    creds = await strava.get_app_credentials(db)
    if creds is None:
        raise HTTPException(503, "Strava not configured")
    payload = await strava.exchange_code(creds, code)
    await strava.store_initial_credentials(db, payload)
    return RedirectResponse(url="/settings", status_code=302)


# --- Status + manual control ---

@router.get("/strava/status", response_model=StravaStatus, dependencies=[Depends(require_query)])
async def strava_status(db: AsyncSession = Depends(get_session)) -> StravaStatus:
    app_creds = await strava.get_app_credentials(db)
    user_creds = await strava.get_credentials(db)
    return StravaStatus(
        configured=app_creds is not None,
        config_source=app_creds.source if app_creds else None,
        connected=user_creds is not None,
        athlete_id=user_creds.athlete_id if user_creds else None,
        athlete_name=user_creds.athlete_name if user_creds else None,
        expires_at=user_creds.expires_at if user_creds else None,
        last_sync_at=user_creds.last_sync_at if user_creds else None,
        scope=user_creds.scope if user_creds else None,
    )


@router.post("/strava/sync", dependencies=[Depends(require_query)])
async def strava_sync(
    days: int = Query(90, ge=1, le=3650),
) -> dict[str, int]:
    after_ts = int(datetime.now(timezone.utc).timestamp()) - days * 86400
    count = await strava.sync_recent(after_ts=after_ts)
    return {"upserted": count, "days": days}


@router.delete("/strava", dependencies=[Depends(require_query)])
async def strava_disconnect(db: AsyncSession = Depends(get_session)) -> dict[str, str]:
    user_creds = await strava.get_credentials(db)
    if user_creds is not None:
        await db.delete(user_creds)
        await db.commit()
    return {"status": "disconnected"}


# --- Read activities (any source) ---

def _activity_to_out(
    a: models.Activity, trail_name: str | None = None,
) -> ActivityOut:
    return ActivityOut(
        source=a.source, source_id=a.source_id, type=a.type, name=a.name,
        start_at=a.start_at, duration_s=a.duration_s,
        distance_m=a.distance_m, elevation_gain_m=a.elevation_gain_m,
        avg_hr=a.avg_hr, max_hr=a.max_hr,
        avg_power_w=a.avg_power_w, max_power_w=a.max_power_w,
        kcal=a.kcal, suffer_score=a.suffer_score, polyline=a.polyline,
        notes=a.notes, tags=a.tags,
        trail_id=a.trail_id, trail_name=trail_name,
    )


@router.get("/activities/stats", response_model=ActivityStatsOut,
            dependencies=[Depends(require_any)])
async def activities_stats(
    days: int = Query(30, ge=1, le=3650),
    db: AsyncSession = Depends(get_session),
) -> ActivityStatsOut:
    """Aggregate stats over the past `days` days, plus comparison vs prior period."""
    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)
    period_start = now - _td(days=days)
    prev_start = now - _td(days=2 * days)

    res = await db.execute(
        select(models.Activity)
        .where(models.Activity.start_at >= period_start)
        .where(models.Activity.start_at <= now)
    )
    rows = res.scalars().all()

    res_prev = await db.execute(
        select(
            func.count(models.Activity.source_id),
            func.coalesce(func.sum(models.Activity.distance_m), 0),
            func.coalesce(func.sum(models.Activity.duration_s), 0),
            func.coalesce(func.sum(models.Activity.elevation_gain_m), 0),
            func.coalesce(func.sum(models.Activity.kcal), 0),
        )
        .where(models.Activity.start_at >= prev_start)
        .where(models.Activity.start_at < period_start)
    )
    prev = res_prev.one()
    pn, pd, pdur, pelev, pkcal = (float(x) for x in prev)

    n = len(rows)
    total_distance = sum(a.distance_m or 0 for a in rows)
    total_duration = sum(a.duration_s for a in rows)
    total_elev = sum(a.elevation_gain_m or 0 for a in rows)
    total_kcal = sum(a.kcal or 0 for a in rows)

    by_type: dict[str, int] = {}
    for a in rows:
        by_type[a.type] = by_type.get(a.type, 0) + 1

    active_days = {a.start_at.date() for a in rows}
    streak = 0
    d = now.date()
    while d in active_days:
        streak += 1
        d -= _td(days=1)

    def pct(curr: float, prev_val: float) -> float:
        if prev_val == 0:
            return 0.0 if curr == 0 else 100.0
        return ((curr - prev_val) / prev_val) * 100

    if days >= 365 * 9:
        period_label = "All time"
    elif days >= 365:
        years = round(days / 365)
        period_label = f"Last {years}y" if years > 1 else "Last 1y"
    else:
        period_label = f"Last {days} days"
    return ActivityStatsOut(
        period_label=period_label,
        n_activities=n,
        total_distance_m=total_distance,
        total_duration_s=total_duration,
        total_elevation_m=total_elev,
        total_kcal=total_kcal,
        by_type=by_type,
        streak_days=streak,
        period_pct_vs_prev={
            "n": pct(n, pn), "distance": pct(total_distance, pd),
            "duration": pct(total_duration, pdur),
            "elevation": pct(total_elev, pelev),
            "kcal": pct(total_kcal, pkcal),
        },
    )


@router.get("/activities/{source}/{source_id}", response_model=ActivityOut,
            dependencies=[Depends(require_any)])
async def get_activity(
    source: str,
    source_id: str,
    db: AsyncSession = Depends(get_session),
) -> ActivityOut:
    result = await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )
    a = result.scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "activity not found")
    trail_name: str | None = None
    if a.trail_id is not None:
        t = await db.get(models.Trail, a.trail_id)
        if t is not None:
            trail_name = t.name
    return _activity_to_out(a, trail_name=trail_name)


@router.post("/activities/{source}/{source_id}/link-trail",
             dependencies=[Depends(require_any)])
async def link_activity_trail(
    source: str,
    source_id: str,
    body: ActivityLinkTrailIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Manually set or clear an activity's trail_id. Pass trail_id=null
    to unlink. Overrides the GPS-proximity auto-link."""
    a = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "activity not found")
    if body.trail_id is not None:
        t = await db.get(models.Trail, body.trail_id)
        if t is None:
            raise HTTPException(400, f"trail {body.trail_id} not found")
    a.trail_id = body.trail_id
    await db.commit()
    return {
        "source": a.source, "source_id": a.source_id,
        "trail_id": a.trail_id,
    }


@router.post("/activities/{source}/{source_id}/notes",
             dependencies=[Depends(require_any)])
async def update_activity_notes(
    source: str,
    source_id: str,
    body: ActivityNotesIn,
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    result = await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )
    a = result.scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "activity not found")
    a.notes = body.notes
    a.tags = body.tags or None
    await db.commit()
    return {"status": "saved"}


@router.get("/activities", response_model=list[ActivityOut], dependencies=[Depends(require_any)])
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
    return [_activity_to_out(a) for a in result.scalars().all()]
