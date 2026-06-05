import logging
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any, require_query
from ..db import models
from ..db.session import get_session
from ..integrations import strava
from ..integrations import strava_web

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

class StravaCookieStatus(BaseModel):
    configured: bool
    athlete_id: int | None = None
    athlete_name: str | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
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
            dependencies=[Depends(require_query)])
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
        configured=row.remember_token is not None,
        athlete_id=row.athlete_id_cached,
        athlete_name=row.athlete_name_cached,
        last_sync_at=row.last_sync_at,
        last_error=row.last_error,
        auto_login_available=strava_web.auto_login_available(),
        auto_login_enabled=row.auto_login_enabled,
        email=row.email,
        last_auto_login_at=row.last_auto_login_at,
    )


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
    have_creds = bool(body.email and body.password)
    have_cookie = bool(body.remember_token)

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
    if not row.remember_token:
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
        return stubs

    try:
        stubs = await _list_with_auto_relogin()
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
            upserted_ids.append(stub.id)
        except Exception as e:  # noqa: BLE001
            log.warning("upsert %s failed: %s", stub.id, e)
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
    since = row.last_sync_at if row else None
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
