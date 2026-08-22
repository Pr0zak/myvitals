import logging
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import polyline as _polyline_lib

from ..analytics import cardio, consistency, geo
from ..auth import require_any, require_query
from ..config import settings
from ..db import models
from ..db.session import get_session
from ..integrations import activity_sink
from ..integrations import strava
from ..integrations import strava_web

router = APIRouter()


def _local_tz() -> Any:
    """The user's timezone, falling back to UTC when it will not resolve.

    Same block as ``api/summary.py:_local_tz``. Activities are stored with
    UTC timestamps, so any calendar-day question about them — which day was
    this session on, is today part of a streak — has to be asked in the
    user's zone or it answers for the wrong day every evening.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(settings.tz) if settings.tz != "UTC" else timezone.utc
    except Exception:
        return timezone.utc


def _local_date(ts: datetime, tz: Any) -> Any:
    """The LOCAL calendar date of a stored timestamp.

    ``ts.date()`` gives the UTC date, which for a 20:00 Central session is
    the *following* day. Doing that consistently shifts a whole training
    history forward by one and manufactures gaps in streaks.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(tz).date()


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


class ActivityEditIn(BaseModel):
    """PATCH body for manual (source=manual) Activity edits. All fields
    optional — only set keys are applied. Server validates and re-runs
    the HR-sample scan when start_at or duration_minutes changes so the
    avg/max HR stay anchored to the user's window."""
    name: str | None = Field(default=None, max_length=255)
    type: str | None = Field(default=None, max_length=64)
    duration_minutes: float | None = Field(default=None, gt=0, le=24 * 60)
    start_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=400)


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
    #: Retained under its original name so an older APK keeps working;
    #: it is the same number as `consistency.current_streak_days`.
    streak_days: int
    period_pct_vs_prev: dict[str, float]
    #: CONS-1. Measured over full history in the user's local timezone,
    #: not over the selected window in UTC — see analytics/consistency.py
    #: for the three ways the previous inline version got this wrong.
    consistency: dict[str, Any] | None = None


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
    """Manual Strava pull — bypasses the 30-min self-throttle inside
    sync_recent. The scheduled 1-hourly poll uses the throttle; this
    endpoint exists so the user can hit "Sync now" and get an
    immediate refresh."""
    after_ts = int(datetime.now(timezone.utc).timestamp()) - days * 86400
    count = await strava.sync_recent(after_ts=after_ts, force=True)
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

    # CONS-1: streaks are a property of the user's whole history, not of
    # the window they happen to be looking at, and both the activity dates
    # and "today" have to be resolved in the user's timezone. Computing
    # them from `rows` (already filtered to `days`) truncated any streak
    # that began before the window edge; anchoring on the UTC date
    # reported zero for five hours every evening.
    local_tz = _local_tz()
    today_local = datetime.now(local_tz).date()
    all_days_rows = (await db.execute(
        select(models.Activity.start_at)
    )).scalars().all()
    active_days = {_local_date(t, local_tz) for t in all_days_rows}
    streaks = consistency.compute_streaks(active_days, today_local)
    streak = streaks.current_days

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
        consistency={
            "current_streak_days": streaks.current_days,
            "longest_streak_days": streaks.longest_days,
            "current_streak_start": (
                streaks.current_start.isoformat() if streaks.current_start else None
            ),
            "longest_streak_start": (
                streaks.longest_start.isoformat() if streaks.longest_start else None
            ),
            "longest_streak_end": (
                streaks.longest_end.isoformat() if streaks.longest_end else None
            ),
            "last_active": (
                streaks.last_active.isoformat() if streaks.last_active else None
            ),
            "today_pending": streaks.today_pending,
            # Fixed trailing windows, deliberately independent of `days` —
            # a frequency that moves when you change the date picker is
            # describing the picker, not the training.
            "sessions_per_week_actual": consistency.sessions_per_week(
                active_days, today_local, 28,
            ),
            "sessions_last_7d": consistency.count_in_window(
                active_days, today_local, 7,
            ),
            "sessions_last_28d": consistency.count_in_window(
                active_days, today_local, 28,
            ),
            "frequency_window_days": 28,
        },
        period_pct_vs_prev={
            "n": pct(n, pn), "distance": pct(total_distance, pd),
            "duration": pct(total_duration, pdur),
            "elevation": pct(total_elev, pelev),
            "kcal": pct(total_kcal, pkcal),
        },
    )


class MapTrackOut(BaseModel):
    source: str
    source_id: str
    type: str
    name: str | None
    start_at: datetime
    duration_s: int
    distance_m: float | None
    trail_id: int | None = None
    trail_name: str | None = None
    # RDP-simplified, NOT the stored full-fidelity track. Fetch the
    # activity detail endpoint when you need the real thing.
    polyline: str


class ActivityMapOut(BaseModel):
    tracks: list[MapTrackOut]
    # [south, west, north, east] over every returned track — the "fit all"
    # extent. Null when nothing matched.
    bounds: list[float] | None = None
    # Bounds of the cluster the user actually trains in. Clients should
    # OPEN on this; fitting `bounds` means one holiday ride two states
    # away shrinks the home cluster to a dot. Computed server-side so web
    # and phone open on the same view.
    primary_bounds: list[float] | None = None
    returned: int
    # Point counts before/after simplification — surfaced so the payload
    # cost stays visible rather than silently ballooning.
    source_points: int
    simplified_points: int


@router.get("/activities/zones", dependencies=[Depends(require_any)])
async def get_cardio_zones(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Rolling time-in-zone across recent cardio, with zone boundaries.

    Wraps analytics/cardio.py:cardio_summary, which was previously reachable
    only from the AI coach payload builder -- so the coach could tell the
    user their week was 62% Z2 while no screen in either client could show
    them the same breakdown.

    Lives on the activities router rather than the analytics one because
    that router is query-token-only, and the phone authenticates with the
    ingest token.
    """
    summary = await cardio.cardio_summary(db, days=days)
    max_hr, source, age = await cardio.resolve_max_hr(db)
    summary["max_hr_source"] = source
    summary["age_used"] = age
    summary["bounds"] = cardio.zone_bounds(max_hr)
    summary["zone_labels"] = cardio.ZONE_LABELS
    return summary


@router.get("/activities/map", response_model=ActivityMapOut,
            dependencies=[Depends(require_any)])
async def activities_map(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    type: str | None = Query(None),
    trail_id: int | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    epsilon: float = Query(geo.DEFAULT_EPSILON_DEG, ge=0.0, le=0.01),
    max_points: int = Query(geo.DEFAULT_MAX_POINTS, ge=2, le=5000),
    db: AsyncSession = Depends(get_session),
) -> ActivityMapOut:
    """Every GPS-tracked activity as simplified polylines, for an
    all-activities overview map.

    The stored tracks total ~3.4 MB across ~560 activities, which is not
    something to hand a phone in one response. Each is simplified before
    it goes out (see `analytics/geo.py`); at the default epsilon that is
    roughly a 10x reduction with no visible change at overview zoom.

    `require_any` — the phone reads this, and it only carries the ingest
    token.
    """
    stmt = (
        select(models.Activity)
        .where(models.Activity.polyline.isnot(None))
        .where(models.Activity.polyline != "")
        .order_by(models.Activity.start_at.desc())
        .limit(limit)
    )
    if since:
        stmt = stmt.where(models.Activity.start_at >= since)
    if until:
        stmt = stmt.where(models.Activity.start_at <= until)
    if type:
        stmt = stmt.where(models.Activity.type == type)
    if trail_id is not None:
        stmt = stmt.where(models.Activity.trail_id == trail_id)
    rows = (await db.execute(stmt)).scalars().all()

    trail_names: dict[int, str] = {}
    trail_ids = {a.trail_id for a in rows if a.trail_id is not None}
    if trail_ids:
        trail_names = {
            t.id: t.name
            for t in (await db.execute(
                select(models.Trail).where(models.Trail.id.in_(trail_ids))
            )).scalars().all()
        }

    # Use the cached simplification when the caller accepts the stored
    # settings; custom epsilon / max_points always recompute and are never
    # written back, so one exploratory request can't poison the cache.
    use_cache = (
        epsilon == geo.DEFAULT_EPSILON_DEG and max_points == geo.DEFAULT_MAX_POINTS
    )

    tracks: list[MapTrackOut] = []
    decoded_tracks: list[list[tuple[float, float]]] = []
    south = west = north = east = None
    src_pts = simp_pts = 0
    filled = 0
    for a in rows:
        cached = a.polyline_simple if use_cache else None
        if cached:
            encoded, n_src = cached, 0
        else:
            encoded, n_src, _ = geo.simplify_encoded(
                a.polyline, epsilon=epsilon, max_points=max_points,
            )
            if use_cache and encoded:
                # Lazy backfill: pay the simplification cost once per
                # activity, ever. A newly synced activity costs one
                # track's worth on the next map load rather than a 15 s
                # full rebuild.
                a.polyline_simple = encoded
                filled += 1
        # A track that won't decode is skipped rather than sent empty —
        # an empty polyline renders as an invisible zero-length line and
        # would still drag fitBounds toward [0,0].
        if not encoded:
            continue
        pts = _polyline_lib.decode(encoded)
        decoded_tracks.append(pts)
        src_pts += n_src
        simp_pts += len(pts)
        b = geo.bounds_of(pts)
        if b is not None:
            south = b[0] if south is None else min(south, b[0])
            west = b[1] if west is None else min(west, b[1])
            north = b[2] if north is None else max(north, b[2])
            east = b[3] if east is None else max(east, b[3])
        tracks.append(MapTrackOut(
            source=a.source, source_id=a.source_id, type=a.type, name=a.name,
            start_at=a.start_at, duration_s=a.duration_s,
            distance_m=a.distance_m, trail_id=a.trail_id,
            trail_name=trail_names.get(a.trail_id) if a.trail_id else None,
            polyline=encoded,
        ))

    if filled:
        await db.commit()
    log.info(
        "activities/map: %d tracks, %d points (%d newly simplified from %d)",
        len(tracks), simp_pts, filled, src_pts,
    )
    bounds = None if south is None else [south, west, north, east]

    prof = await db.get(models.UserProfile, 1)
    home = (
        (prof.home_latitude, prof.home_longitude)
        if prof and prof.home_latitude is not None
        and prof.home_longitude is not None
        else None
    )
    return ActivityMapOut(
        tracks=tracks, bounds=bounds,
        primary_bounds=geo.primary_bounds(decoded_tracks, home=home),
        returned=len(tracks),
        source_points=src_pts, simplified_points=simp_pts,
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


@router.get("/activities/{source}/{source_id}/zones",
            dependencies=[Depends(require_any)])
async def get_activity_zones(
    source: str,
    source_id: str,
    buckets: int = Query(50, ge=0, le=200),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Time-in-zone for one activity, computed server-side.

    analytics/cardio.py has had a correct, time-weighted implementation of
    this since the cardio coach shipped, but it was only ever reachable from
    integrations/claude.py -- it had no HTTP surface. So both clients grew
    their own, and both got it wrong in different ways: they counted HR
    *samples* per zone rather than seconds (which skews any session where the
    watch sampled irregularly), and the web's zone-breakdown card divided by
    the activity's own peak HR instead of the user's maximum, so every ride
    reported time in the top zones no matter how easy it was.

    Set buckets=0 to skip the time series when only the totals are needed.
    """
    a = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "activity not found")
    return await cardio.activity_zone_detail(db, a, buckets=buckets)


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


@router.patch("/activities/{source}/{source_id}",
              response_model=ActivityOut,
              dependencies=[Depends(require_any)])
async def edit_activity(
    source: str,
    source_id: str,
    body: ActivityEditIn,
    db: AsyncSession = Depends(get_session),
) -> ActivityOut:
    """Edit a manually-logged Activity row. Restricted to source=manual
    so re-syncs from Strava / Concept2 / Health Connect can't be quietly
    overwritten (they'd just bounce back to source values on the next
    sync, surprising the user). When the time window changes we re-scan
    HeartRate samples so avg_hr/max_hr stay anchored to reality."""
    if source != "manual":
        raise HTTPException(
            status_code=403,
            detail=f"only manual activities are editable, "
                   f"got source={source!r}",
        )
    a = (await db.execute(
        select(models.Activity)
        .where(models.Activity.source == source)
        .where(models.Activity.source_id == source_id)
    )).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "activity not found")

    data = body.model_dump(exclude_unset=True)
    if "name" in data: a.name = data["name"]
    if "type" in data: a.type = data["type"] or a.type
    if "notes" in data: a.notes = data["notes"]

    window_changed = False
    if "start_at" in data and data["start_at"] is not None:
        sa = data["start_at"]
        if sa.tzinfo is None:
            sa = sa.replace(tzinfo=timezone.utc)
        a.start_at = sa
        window_changed = True
    if "duration_minutes" in data and data["duration_minutes"] is not None:
        a.duration_s = int(data["duration_minutes"] * 60)
        window_changed = True

    if window_changed:
        end_at = a.start_at + timedelta(seconds=a.duration_s)
        hr_rows = (await db.execute(
            select(models.HeartRate.bpm)
            .where(models.HeartRate.time >= a.start_at)
            .where(models.HeartRate.time <= end_at)
        )).scalars().all()
        a.avg_hr = (sum(hr_rows) / len(hr_rows)) if hr_rows else None
        a.max_hr = max(hr_rows) if hr_rows else None

    await db.commit()
    await db.refresh(a)
    trail_name: str | None = None
    if a.trail_id is not None:
        t = await db.get(models.Trail, a.trail_id)
        if t is not None:
            trail_name = t.name
    return _activity_to_out(a, trail_name=trail_name)


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


@router.post("/activities/promote-health-connect",
             dependencies=[Depends(require_any)])
async def promote_health_connect(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Backfill the activities feed from Health Connect sessions (HC-1).

    New sessions are promoted automatically on ingest. This exists for the
    history that predates that, and is idempotent — a second run promotes
    nothing, because a session already in the feed under the
    `healthconnect` source is upserted rather than duplicated, and one
    covered by a richer provider is skipped on the overlap test.
    """
    result = await activity_sink.promote_health_connect_workouts(db)
    await db.commit()
    return result


@router.get("/activities", response_model=list[ActivityOut], dependencies=[Depends(require_any)])
async def list_activities(
    since: datetime | None = Query(None),
    type: str | None = Query(None),
    # Single-user app — bumped cap from 500 → 5000 so the YTD/YoY card
    # on the Activities page can pull 18 months of history in one call
    # without truncating. Anything larger would still cap server-side.
    limit: int = Query(50, ge=1, le=5000),
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


# ─────────────────────────────────────────────────────────────────
# Cookie-session ingest (SCS family) — replaces OAuth path that
# Strava is paywalling on 2026-06-30 for Standard Tier developers.
# ─────────────────────────────────────────────────────────────────

#: Consecutive failures before the scheduled poll stops trying.
#: Shared with tasks/scheduled.py so the API and the scheduler
#: cannot disagree about when polling has stopped.
STRAVA_POLL_MAX_FAILURES = 5


class StravaCookieStatus(BaseModel):
    configured: bool
    athlete_id: int | None = None
    athlete_name: str | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
    # True when the last sync attempt failed and needs the user to act
    # (dead cookie / broken auto-login). Drives the "reconnect Strava"
    # banner on the web + phone Activities screens. last_error is
    # cleared on every successful run, so a non-null value reliably
    # means "sync is broken, go fix it in Settings".
    needs_reconnect: bool = False
    # Scheduled poll (migration 0055). Off by default — this reaches a
    # third party on a timer with a credential that cannot self-heal.
    poll_enabled: bool = False
    poll_interval_min: int = 360
    poll_consecutive_failures: int = 0
    # True once the hard stop has tripped, so the UI can say "polling
    # stopped" rather than leaving the user to infer it from silence.
    poll_stopped: bool = False
    # SCS-6: surfaced so the UI knows whether to show the email +
    # password form. False when STRAVA_CREDS_KEY isn't set in .env.
    auto_login_available: bool = False
    auto_login_enabled: bool = False
    email: str | None = None
    last_auto_login_at: datetime | None = None


class StravaCookieIn(BaseModel):
    # Either cookie fields OR email+password is required. Cookies stay
    # optional so the user can paste just creds and have us auto-login.
    remember_token: str | None = None
    sid_cookie: str | None = None
    # A whole cookie-export blob (Cookie-Editor / EditThisCookie JSON,
    # Netscape cookies.txt, or a header string). Parsed server-side into
    # remember_token / sid_cookie so the user pastes one thing instead of
    # hunting each value in DevTools.
    cookie_blob: str | None = None
    email: str | None = None
    password: str | None = None
    auto_login_enabled: bool = True


class StravaCookieSyncOut(BaseModel):
    upserted: int
    activity_ids: list[int] = []
    error: str | None = None


def _mask(s: str | None) -> str | None:
    if not s:
        return None
    return s[:4] + "…" + s[-4:] if len(s) > 12 else "…"


@router.get("/strava/cookie", response_model=StravaCookieStatus,
            dependencies=[Depends(require_any)])
async def get_cookie_status(
    db: AsyncSession = Depends(get_session),
) -> StravaCookieStatus:
    row = await strava_web.get_cookie_creds(db)
    if row is None:
        return StravaCookieStatus(
            configured=False,
            auto_login_available=strava_web.auto_login_available(),
        )
    return StravaCookieStatus(
        configured=bool(row.remember_token or row.sid_cookie),
        athlete_id=row.athlete_id_cached,
        athlete_name=row.athlete_name_cached,
        last_sync_at=row.last_sync_at,
        last_error=row.last_error,
        needs_reconnect=bool(row.last_error),
        auto_login_available=strava_web.auto_login_available(),
        auto_login_enabled=row.auto_login_enabled,
        email=row.email,
        last_auto_login_at=row.last_auto_login_at,
        poll_enabled=row.poll_enabled,
        poll_interval_min=row.poll_interval_min,
        poll_consecutive_failures=row.poll_consecutive_failures,
        poll_stopped=row.poll_consecutive_failures >= STRAVA_POLL_MAX_FAILURES,
    )


class StravaPollIn(BaseModel):
    enabled: bool | None = None
    interval_min: int | None = None


@router.put("/strava/cookie/poll", response_model=StravaCookieStatus,
            dependencies=[Depends(require_query)])
async def set_cookie_poll(
    body: StravaPollIn,
    db: AsyncSession = Depends(get_session),
) -> StravaCookieStatus:
    """Enable, disable or re-pace the scheduled Strava poll.

    Enabling also clears the failure counter. That is the reconnect
    gesture: after a dead cookie trips the hard stop, the user pastes a
    fresh cookie and turns the poll back on, and it must start trying
    again rather than staying stopped because of failures that belonged
    to the previous credential.
    """
    row = await strava_web.get_cookie_creds(db)
    if row is None:
        raise HTTPException(404, "no Strava cookie configured")
    if body.interval_min is not None:
        # Floor of 15 minutes. Strava is not a live feed — a ride appears
        # minutes to hours after it ends — and a tighter cadence spends
        # request budget against a third party for no new data.
        row.poll_interval_min = max(15, min(24 * 60, int(body.interval_min)))
    if body.enabled is not None:
        row.poll_enabled = bool(body.enabled)
        if body.enabled:
            row.poll_consecutive_failures = 0
    await db.commit()
    await db.refresh(row)
    return await get_cookie_status(db=db)


@router.put("/strava/cookie", response_model=StravaCookieStatus,
            dependencies=[Depends(require_query)])
async def set_cookie(
    body: StravaCookieIn,
    db: AsyncSession = Depends(get_session),
) -> StravaCookieStatus:
    """Persist either a pasted cookie or stored email+password (or both).

    - If email + password given: encrypts password with Fernet key,
      runs a Playwright auto-login *now* to validate the credentials
      and capture an initial cookie. Returns 400 on captcha / wrong
      creds / Playwright failure.
    - If only cookie given: validates with check_cookie() and persists.
    - If both given: runs auto-login first (captures fresh cookie) and
      stores credentials for the next refresh.
    """
    now = datetime.now(timezone.utc)
    row = await strava_web.get_cookie_creds(db)
    # Lenient paste: pull tokens out of a full cookie-export blob so the
    # user doesn't have to match each value to a field. Explicit fields
    # still win if both are somehow provided.
    if body.cookie_blob:
        b_remember, b_sid = strava_web.parse_cookie_blob(body.cookie_blob)
        if not body.remember_token and b_remember:
            body.remember_token = b_remember
        if not body.sid_cookie and b_sid:
            body.sid_cookie = b_sid
    have_creds = bool(body.email and body.password)
    # SCS-8: either cookie alone is enough — OTC accounts only get
    # _strava4_session, never a long-lived remember_token.
    have_cookie = bool(body.remember_token or body.sid_cookie)
    log.info(
        "PUT /strava/cookie have_creds=%s have_cookie=%s remember_len=%d sid_len=%d",
        have_creds, have_cookie,
        len(body.remember_token or ""),
        len(body.sid_cookie or ""),
    )

    if not have_creds and not have_cookie:
        raise HTTPException(400, detail="provide either cookie or email+password")

    new_remember: str | None = body.remember_token
    new_sid: str | None = body.sid_cookie
    athlete_id: int | None = None
    athlete_name: str | None = None
    new_password_enc: str | None = None

    new_key_b64: str | None = None
    if have_creds:
        login = await strava_web.auto_login(body.email, body.password)
        if not login.ok:
            raise HTTPException(400, detail=f"auto-login failed: {login.error}")
        new_remember = login.remember_token
        new_sid = login.sid_cookie
        athlete_id = login.athlete_id
        athlete_name = login.athlete_name
        # Resolve the key: existing row's > env var > newly minted.
        from ..config import settings as _s
        existing_key = row.creds_key_b64 if row else None
        key_b64 = _s.strava_creds_key or existing_key or strava_web.generate_key_b64()
        if not existing_key and not _s.strava_creds_key:
            new_key_b64 = key_b64  # we minted it; persist below
        new_password_enc = strava_web.encrypt_password(body.password, key_b64)

    if have_cookie and not have_creds:
        chk = await strava_web.check_cookie(body.remember_token, body.sid_cookie)
        if not chk.ok:
            log.warning("cookie check failed: %s", chk.error)
            raise HTTPException(400, detail=f"cookie check failed: {chk.error}")
        athlete_id = chk.athlete_id
        athlete_name = chk.athlete_name

    if row is None:
        row = models.StravaCookieCreds(
            id=1,
            remember_token=new_remember,
            sid_cookie=new_sid,
            athlete_id_cached=athlete_id,
            athlete_name_cached=athlete_name,
            email=body.email,
            password_encrypted=new_password_enc,
            creds_key_b64=new_key_b64,
            auto_login_enabled=body.auto_login_enabled and bool(new_password_enc),
            last_auto_login_at=now if have_creds else None,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        if new_remember:
            row.remember_token = new_remember
        if new_sid:
            row.sid_cookie = new_sid
        row.athlete_id_cached = athlete_id or row.athlete_id_cached
        row.athlete_name_cached = athlete_name or row.athlete_name_cached
        if body.email:
            row.email = body.email
        if new_password_enc:
            row.password_encrypted = new_password_enc
        if new_key_b64:
            row.creds_key_b64 = new_key_b64
        row.auto_login_enabled = body.auto_login_enabled and bool(row.password_encrypted)
        if have_creds:
            row.last_auto_login_at = now
        row.last_error = None
        row.updated_at = now
    await db.commit()

    return StravaCookieStatus(
        configured=True,
        athlete_id=row.athlete_id_cached,
        athlete_name=row.athlete_name_cached,
        last_sync_at=row.last_sync_at,
        last_error=None,
        auto_login_available=strava_web.auto_login_available(),
        auto_login_enabled=row.auto_login_enabled,
        email=row.email,
        last_auto_login_at=row.last_auto_login_at,
    )


async def _refresh_cookie_via_auto_login(
    db: AsyncSession,
    row: "models.StravaCookieCreds",
) -> bool:
    """Re-run auto-login using the stored email+password. Returns True
    on success (row updated, db commit not yet performed — caller commits)."""
    if not row.auto_login_enabled or not row.email or not row.password_encrypted:
        return False
    key_b64 = strava_web._resolve_key(row.creds_key_b64)
    if not key_b64:
        row.last_error = "no encryption key (re-save email + password from Settings)"
        return False
    try:
        plain = strava_web.decrypt_password(row.password_encrypted, key_b64)
    except Exception as e:  # noqa: BLE001
        log.warning("password decrypt failed (key rotated?): %s", e)
        row.last_error = "password decrypt failed (re-save password from Settings)"
        return False
    login = await strava_web.auto_login(row.email, plain)
    if not login.ok:
        row.last_error = f"auto-login failed: {login.error}"
        return False
    row.remember_token = login.remember_token
    if login.sid_cookie:
        row.sid_cookie = login.sid_cookie
    if login.athlete_id:
        row.athlete_id_cached = login.athlete_id
    if login.athlete_name:
        row.athlete_name_cached = login.athlete_name
    row.last_auto_login_at = datetime.now(timezone.utc)
    row.last_error = None
    return True


@router.post("/strava/cookie/refresh", response_model=StravaCookieStatus,
             dependencies=[Depends(require_query)])
async def refresh_cookie(db: AsyncSession = Depends(get_session)) -> StravaCookieStatus:
    """Manually re-run auto-login using stored credentials. Useful when
    you suspect a cookie is stale ahead of the next 401."""
    row = await strava_web.get_cookie_creds(db)
    if row is None:
        raise HTTPException(404, detail="no creds row")
    ok = await _refresh_cookie_via_auto_login(db, row)
    await db.commit()
    if not ok:
        raise HTTPException(400, detail=row.last_error or "auto-login not configured")
    return StravaCookieStatus(
        configured=True,
        athlete_id=row.athlete_id_cached,
        athlete_name=row.athlete_name_cached,
        last_sync_at=row.last_sync_at,
        last_error=None,
        auto_login_available=strava_web.auto_login_available(),
        auto_login_enabled=row.auto_login_enabled,
        email=row.email,
        last_auto_login_at=row.last_auto_login_at,
    )


@router.delete("/strava/cookie", status_code=204,
               dependencies=[Depends(require_query)])
async def delete_cookie(db: AsyncSession = Depends(get_session)) -> None:
    row = await strava_web.get_cookie_creds(db)
    if row is not None:
        await db.delete(row)
        await db.commit()


async def _run_cookie_sync(
    db: AsyncSession,
    *,
    since: datetime | None,
    max_activities: int | None = None,
) -> StravaCookieSyncOut:
    """Shared body for both /cookie-sync and /cookie-bulk."""
    row = await strava_web.get_cookie_creds(db)
    if row is None:
        return StravaCookieSyncOut(upserted=0, error="no cookie configured")
    if not (row.remember_token or row.sid_cookie):
        # Row exists with creds but never logged in — try once now.
        if not await _refresh_cookie_via_auto_login(db, row):
            await db.commit()
            return StravaCookieSyncOut(
                upserted=0,
                error=row.last_error or "no cookie and auto-login disabled",
            )
        await db.commit()

    async def _list_with_auto_relogin():
        """Call list_recent_activities; if the cookie is dead, run
        auto-login once and retry. Returns stubs or raises."""
        stubs = await strava_web.list_recent_activities(
            row.remember_token, row.sid_cookie, since=since,
        )
        if stubs or since is None:
            return stubs
        # Empty result on an incremental sync with a fresh-looking
        # last_sync is suspicious — could be a silent cookie expiry
        # (Strava returns empty JSON when unauthorized). Verify with
        # a quick check_cookie() and re-login if it's dead.
        chk = await strava_web.check_cookie(row.remember_token, row.sid_cookie)
        if chk.ok:
            return stubs
        log.info("cookie stale (%s) — attempting auto-login refresh", chk.error)
        if await _refresh_cookie_via_auto_login(db, row):
            await db.commit()
            return await strava_web.list_recent_activities(
                row.remember_token, row.sid_cookie, since=since,
            )
        # Cookie is dead and auto-login can't recover it (disabled, or the
        # stored password / 2FA no longer works). Surface it loudly instead
        # of returning [] — a silent 0-activity run is exactly what hid a
        # 6-week Strava outage (the ride never landed, but the UI stayed
        # green). _refresh_cookie_via_auto_login may have set a specific
        # reason on row.last_error; fall back to a plain reconnect prompt.
        if row.auto_login_enabled:
            raise strava_web.CookieExpired(
                row.last_error
                or "Strava auto-login failed — re-save your Strava password "
                   "in Settings → Strava."
            )
        raise strava_web.CookieExpired(
            "Strava session expired — reconnect in Settings → Strava "
            "(paste a fresh cookie, or enable auto-login)."
        )

    try:
        stubs = await _list_with_auto_relogin()
    except strava_web.CookieExpired as e:
        row.last_error = str(e)[:400]
        await db.commit()
        return StravaCookieSyncOut(upserted=0, error=row.last_error)
    except Exception as e:  # noqa: BLE001
        row.last_error = f"list error: {e}"[:400]
        await db.commit()
        return StravaCookieSyncOut(upserted=0, error=row.last_error)
    if max_activities is not None:
        stubs = stubs[:max_activities]

    upserted_ids: list[int] = []
    for stub in stubs:
        try:
            blob = await strava_web.download_activity_original(
                row.remember_token, row.sid_cookie, stub.id,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("download %s failed: %s", stub.id, e)
            continue
        parsed = strava_web.parse_fit_bytes(blob)
        try:
            await strava_web.upsert_activity_from_fit(db, stub, parsed)
            # Commit per activity so one bad FIT doesn't roll back the
            # rides that already landed in this run.
            await db.commit()
            upserted_ids.append(stub.id)
        except Exception as e:  # noqa: BLE001
            log.warning("upsert %s failed: %s", stub.id, e)
            # A failed statement aborts the whole session — without a
            # rollback every later statement (next upserts, the
            # last_sync_at bump) dies with InFailedSQLTransaction.
            await db.rollback()
            continue

    row.last_sync_at = datetime.now(timezone.utc)
    row.last_error = None
    await db.commit()
    return StravaCookieSyncOut(upserted=len(upserted_ids), activity_ids=upserted_ids)


@router.post("/strava/cookie-sync", response_model=StravaCookieSyncOut,
             dependencies=[Depends(require_any)])
async def cookie_sync(
    db: AsyncSession = Depends(get_session),
) -> StravaCookieSyncOut:
    """Pull new activities since the last sync. Phone-friendly (require_any
    accepts ingest token) so the phone's Activities sync button works."""
    row = await strava_web.get_cookie_creds(db)
    # Watermark = newest strava activity already in the DB, not the time
    # the last sync ran. A ride that reaches Strava after a sync has
    # already bumped last_sync_at past its start time would otherwise be
    # skipped forever. Upsert is idempotent (PK source+source_id), so a
    # conservative watermark only costs a re-download.
    latest = (await db.execute(
        select(func.max(models.Activity.start_at))
        .where(models.Activity.source == "strava")
    )).scalar()
    since = latest or (row.last_sync_at if row else None)
    return await _run_cookie_sync(db, since=since)


@router.post("/strava/cookie-bulk", response_model=StravaCookieSyncOut,
             dependencies=[Depends(require_query)])
async def cookie_bulk(
    since_days: int = Query(30, ge=1, le=3650),
    limit: int | None = Query(None, ge=1, le=1000),
    db: AsyncSession = Depends(get_session),
) -> StravaCookieSyncOut:
    """Bulk import N days of history. Bounded by `limit` (defaults to
    no limit; pass 100-ish during testing). require_query so only
    the dashboard can fire it — bulk import is not phone-friendly."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    return await _run_cookie_sync(db, since=since, max_activities=limit)
