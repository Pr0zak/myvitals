"""Trail status endpoints — list, history, subscribe, refresh, alerts.

Pulls from the trails / trail_status_snapshots / trail_subscriptions /
trail_alerts tables populated by integrations/rainoutline.py.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import polyline as polyline_lib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_any
from ..db import models
from ..db.session import get_session


# ------------------------------------------------------------------
# Geo helpers
# ------------------------------------------------------------------

_EARTH_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two GPS points in kilometers."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def _activity_start_point(act: models.Activity) -> tuple[float, float] | None:
    """Decode the first polyline coord (best proxy for the trailhead).
    Returns None when the activity has no usable GPS."""
    if not act.polyline:
        return None
    try:
        pts = polyline_lib.decode(act.polyline)
    except Exception:  # noqa: BLE001
        return None
    return pts[0] if pts else None


async def _link_activity_to_trail(
    db: AsyncSession, act: models.Activity, trails_with_coords: list[models.Trail],
    max_km: float = 2.0,
) -> int | None:
    """Set act.trail_id to the nearest trail (within max_km) and return it.
    Returns None if no trail in range. Caller commits."""
    pt = _activity_start_point(act)
    if pt is None:
        return None
    lat, lon = pt
    best: tuple[int, float] | None = None
    for t in trails_with_coords:
        if t.latitude is None or t.longitude is None:
            continue
        d = haversine_km(lat, lon, t.latitude, t.longitude)
        if d <= max_km and (best is None or d < best[1]):
            best = (t.id, d)
    if best is not None and act.trail_id != best[0]:
        act.trail_id = best[0]
    return best[0] if best else None

router = APIRouter(prefix="/trails", dependencies=[Depends(require_any)])


# ------------------------------------------------------------------
# List + detail
# ------------------------------------------------------------------

@router.get("")
async def list_trails(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Every trail with its most recent snapshot + subscription state."""
    trails = (await db.execute(
        select(models.Trail).order_by(models.Trail.name)
    )).scalars().all()
    if not trails:
        return {"count": 0, "trails": []}

    # Most recent snapshot per trail in a single round-trip via DISTINCT ON.
    # SQLAlchemy 2.x: use a subquery + window function or rely on PG's
    # DISTINCT ON (PostgreSQL-specific). Stick to a simple per-trail query
    # for clarity; trail count is ~30, perf is fine.
    out: list[dict[str, Any]] = []
    sub_ids = set((await db.execute(
        select(models.TrailSubscription.trail_id)
    )).scalars().all())
    sub_notify = {
        tid: notify for tid, notify in (await db.execute(
            select(models.TrailSubscription.trail_id, models.TrailSubscription.notify_on)
        )).all()
    }

    # All-time count + last-visit max per trail
    all_rows = (await db.execute(
        select(
            models.Activity.trail_id,
            func.count(models.Activity.source_id).label("n"),
            func.max(models.Activity.start_at).label("last"),
        )
        .where(models.Activity.trail_id.is_not(None))
        .group_by(models.Activity.trail_id)
    )).all()
    all_by_trail = {tid: (n, last) for tid, n, last in all_rows}

    # 30-day count for the recent-activity badge
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    rec_rows = (await db.execute(
        select(
            models.Activity.trail_id,
            func.count(models.Activity.source_id).label("n"),
        )
        .where(models.Activity.trail_id.is_not(None))
        .where(models.Activity.start_at >= cutoff_30)
        .group_by(models.Activity.trail_id)
    )).all()
    visits_30d_by_trail = {tid: n for tid, n in rec_rows}

    for t in trails:
        latest = (await db.execute(
            select(models.TrailStatusSnapshot)
            .where(models.TrailStatusSnapshot.trail_id == t.id)
            .order_by(models.TrailStatusSnapshot.fetched_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        v_total, v_last = all_by_trail.get(t.id, (0, None))
        v_30d = visits_30d_by_trail.get(t.id, 0)
        out.append({
            "id": t.id,
            "extension": t.extension,
            "name": t.name,
            "slug": t.slug,
            "last_seen_at": t.last_seen_at,
            "latitude": t.latitude,
            "longitude": t.longitude,
            "city": t.city,
            "state": t.state,
            "subscribed": t.id in sub_ids,
            "notify_on": sub_notify.get(t.id),
            "status": latest.status if latest else None,
            "comment": latest.comment if latest else None,
            "source_ts": latest.source_ts if latest else None,
            "fetched_at": latest.fetched_at if latest else None,
            "visits_30d": v_30d,
            "visits_total": v_total,
            "last_visit_at": v_last,
        })
    return {"count": len(out), "trails": out}


# ------------------------------------------------------------------
# Activity ↔ trail linking
# ------------------------------------------------------------------

@router.post("/link-activities")
async def link_activities(
    max_km: float = 2.0,
    relink: bool = False,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Walk every Strava-imported activity that has a polyline and try to
    link it to the nearest trail within `max_km` (default 2 km). By
    default skips activities that already have a trail_id; pass
    relink=true to recompute all of them.

    Useful after seeding new trail coordinates or running a one-shot
    Strava backfill — every activity gets pinned to the right trail.
    """
    trails_with_coords = (await db.execute(
        select(models.Trail).where(models.Trail.latitude.is_not(None))
    )).scalars().all()
    if not trails_with_coords:
        raise HTTPException(status_code=409, detail="no trails have coordinates yet")

    activities = (await db.execute(
        select(models.Activity).where(models.Activity.polyline.is_not(None))
    )).scalars().all()
    linked = 0
    skipped_already = 0
    no_match = 0
    no_gps = 0
    for act in activities:
        if act.trail_id is not None and not relink:
            skipped_already += 1
            continue
        pt = _activity_start_point(act)
        if pt is None:
            no_gps += 1
            continue
        result = await _link_activity_to_trail(db, act, trails_with_coords, max_km=max_km)
        if result is not None:
            linked += 1
        else:
            no_match += 1
    await db.commit()
    return {
        "scanned": len(activities), "linked": linked,
        "already_linked_skipped": skipped_already,
        "no_match_within_km": no_match, "no_gps": no_gps,
        "max_km": max_km,
    }


@router.get("/{trail_id}/visits")
async def trail_visits(
    trail_id: int, days: int = 365,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Activities linked to this trail in the last `days` days, newest first."""
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(models.Activity)
        .where(models.Activity.trail_id == trail_id)
        .where(models.Activity.start_at >= since)
        .order_by(models.Activity.start_at.desc())
        .limit(200)
    )).scalars().all()
    return {
        "trail_id": trail_id, "name": t.name, "count": len(rows),
        "visits": [
            {
                "source": a.source, "source_id": a.source_id,
                "type": a.type, "name": a.name,
                "start_at": a.start_at, "duration_s": a.duration_s,
                "distance_m": a.distance_m, "avg_hr": a.avg_hr,
                "kcal": a.kcal,
            }
            for a in rows
        ],
    }


# ------------------------------------------------------------------
# Location seeding (one-shot, idempotent)
# ------------------------------------------------------------------

@router.post("/seed-locations")
async def seed_locations(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Read backend/src/myvitals/data/trail_locations.json and update
    each known trail's lat/lon/city/state. Idempotent — only updates
    rows whose lat/lon are currently null OR differ from the file."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "data" / "trail_locations.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="trail_locations.json not found in data/")
    data: dict[str, Any] = json.loads(p.read_text())
    trails = (await db.execute(select(models.Trail))).scalars().all()
    updated = 0
    skipped = 0
    for t in trails:
        loc = data.get(t.name)
        if loc is None:
            skipped += 1
            continue
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if lat is None or lon is None:
            skipped += 1
            continue
        if t.latitude == lat and t.longitude == lon:
            continue
        t.latitude = lat
        t.longitude = lon
        t.city = loc.get("city")
        t.state = loc.get("state")
        updated += 1
    await db.commit()
    return {"updated": updated, "skipped": skipped, "total_in_db": len(trails)}


@router.get("/{trail_id}/history")
async def trail_history(
    trail_id: int, days: int = 30,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """All snapshots for a trail in the last `days` days, oldest first."""
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(models.TrailStatusSnapshot)
        .where(models.TrailStatusSnapshot.trail_id == trail_id)
        .where(models.TrailStatusSnapshot.fetched_at >= since)
        .order_by(models.TrailStatusSnapshot.fetched_at)
    )).scalars().all()
    return {
        "trail_id": trail_id, "name": t.name,
        "snapshots": [
            {
                "fetched_at": s.fetched_at, "status": s.status,
                "comment": s.comment, "source_ts": s.source_ts,
            }
            for s in rows
        ],
    }


# ------------------------------------------------------------------
# Subscriptions
# ------------------------------------------------------------------

class SubscribeBody(BaseModel):
    notify_on: str = "any"   # any | open_only | close_only


class TrailLocationBody(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    city: str | None = None
    state: str | None = None


@router.get("/resolve-link")
async def resolve_link(url: str) -> dict[str, str]:
    """Server-side HEAD-redirect resolver. Browsers can't follow
    cross-origin redirects on goo.gl / maps.app.goo.gl (CORS strips
    the Location header), so the frontend posts the short URL here
    and we return the expanded form.

    Restricted to known short-link hosts to avoid being a generic
    SSRF vector."""
    import httpx
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {
        "maps.app.goo.gl", "goo.gl", "g.co", "g.page",
        "www.google.com", "google.com",
    }:
        raise HTTPException(status_code=400, detail=f"host not allowed: {host}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as c:
        try:
            r = await c.head(url)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"fetch failed: {e}") from e
    return {"resolved_url": str(r.url)}


@router.put("/{trail_id}/location")
async def put_trail_location(
    trail_id: int, body: TrailLocationBody,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Manually edit a trail's coordinates. Useful for the two trails
    the auto-curator couldn't pin (Lewis & Clark, Prairie Creek), or
    when the autosourced point is wrong."""
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    if body.latitude is not None and not (-90.0 <= body.latitude <= 90.0):
        raise HTTPException(status_code=400, detail="latitude out of range")
    if body.longitude is not None and not (-180.0 <= body.longitude <= 180.0):
        raise HTTPException(status_code=400, detail="longitude out of range")
    t.latitude = body.latitude
    t.longitude = body.longitude
    if body.city is not None: t.city = body.city
    if body.state is not None: t.state = body.state
    await db.commit()
    return {
        "id": t.id, "name": t.name,
        "latitude": t.latitude, "longitude": t.longitude,
        "city": t.city, "state": t.state,
    }


@router.post("/{trail_id}/subscribe")
async def subscribe(
    trail_id: int, body: SubscribeBody,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if body.notify_on not in {"any", "open_only", "close_only"}:
        raise HTTPException(status_code=400, detail="notify_on must be any|open_only|close_only")
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    sub = await db.get(models.TrailSubscription, trail_id)
    if sub is None:
        sub = models.TrailSubscription(
            trail_id=trail_id,
            subscribed_at=datetime.now(timezone.utc),
            notify_on=body.notify_on,
        )
        db.add(sub)
    else:
        sub.notify_on = body.notify_on
    await db.commit()
    return {"trail_id": trail_id, "subscribed": True, "notify_on": sub.notify_on}


@router.delete("/{trail_id}/subscribe", status_code=204)
async def unsubscribe(
    trail_id: int, db: AsyncSession = Depends(get_session),
) -> None:
    sub = await db.get(models.TrailSubscription, trail_id)
    if sub is not None:
        await db.delete(sub)
        await db.commit()


# ------------------------------------------------------------------
# Refresh + alerts
# ------------------------------------------------------------------

@router.post("/refresh")
async def refresh_now(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Pull-to-refresh: triggers an out-of-band poll. Same code as the
    scheduler runs on its 15-min cadence."""
    from ..integrations.rainoutline import poll_and_persist
    return await poll_and_persist()


@router.get("/alerts")
async def list_alerts(
    unacked_only: bool = False, limit: int = 50,
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Recent trail-status flips for subscribed trails."""
    stmt = select(models.TrailAlert).order_by(models.TrailAlert.created_at.desc()).limit(limit)
    if unacked_only:
        stmt = stmt.where(models.TrailAlert.acked_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []
    # Hydrate trail name in one query
    trail_ids = list({r.trail_id for r in rows})
    trails_by_id = {
        t.id: t for t in (await db.execute(
            select(models.Trail).where(models.Trail.id.in_(trail_ids))
        )).scalars().all()
    }
    return [
        {
            "id": r.id,
            "trail_id": r.trail_id,
            "trail_name": trails_by_id[r.trail_id].name if r.trail_id in trails_by_id else None,
            "from_status": r.from_status,
            "to_status": r.to_status,
            "source_ts": r.source_ts,
            "created_at": r.created_at,
            "phone_notified_at": r.phone_notified_at,
            "acked_at": r.acked_at,
        }
        for r in rows
    ]


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(
    alert_id: int, db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    a = await db.get(models.TrailAlert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alert not found")
    a.acked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "acked"}


@router.post("/alerts/mark-notified")
async def mark_notified(
    body: dict[str, list[int]],
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Phone calls this after posting system notifications so we don't
    re-notify the same alert. Body: {ids: [1, 2, 3]}."""
    ids = body.get("ids") or []
    now = datetime.now(timezone.utc)
    n = 0
    for aid in ids:
        a = await db.get(models.TrailAlert, aid)
        if a is not None and a.phone_notified_at is None:
            a.phone_notified_at = now
            n += 1
    await db.commit()
    return {"marked": n}
