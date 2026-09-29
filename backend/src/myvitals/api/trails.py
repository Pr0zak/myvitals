"""Trail status endpoints — list, subscribe, refresh, alerts.

Pulls from the trails / trail_status_snapshots / trail_subscriptions /
trail_alerts tables populated by integrations/rainoutline.py.

SA-C4: a `/{trail_id}/history` route used to live here, returning raw
snapshots for a window. It had zero callers on either client (no Vue view,
no Compose screen, and the one API-client wrapper for it had no callers
either — `frontend/src/api/client.ts` before this fix) and zero hits in
production logs, so it was removed rather than kept as a foundation for a
history feature nothing had asked for yet. If a status-reliability surface
gets built later, see the SA-C4 correction in docs/sa-findings.json for
what a defensible version needs: distinct source statements, time-weighted
by how long each stood, excluding `unknown`, refusing below N statements
or on a stale feed — not raw-snapshot percentages.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import polyline as polyline_lib
from fastapi import APIRouter, Depends, HTTPException, Query
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


def _activity_track(act: models.Activity) -> list[tuple[float, float]]:
    """Every decodable point of the activity's route, full polyline first,
    the simplified one as a fallback. Empty when there is no GPS."""
    for enc in (act.polyline, act.polyline_simple):
        if not enc:
            continue
        try:
            pts = polyline_lib.decode(enc)
        except Exception:  # noqa: BLE001
            continue
        if pts:
            return pts
    return []


# Wider than the 2 km auto-link radius on purpose: a suggestion is only a
# shortcut in a picker the user still taps, so a ride that parked a little
# further out should still surface its trail first.
SUGGEST_MAX_KM = 10.0
SUGGEST_LIMIT = 3


def rank_trails_near_track(
    track: list[tuple[float, float]], trails: list[models.Trail],
    max_km: float = SUGGEST_MAX_KM, limit: int = SUGGEST_LIMIT,
) -> list[tuple[models.Trail, float]]:
    """Trails whose pin lies within `max_km` of ANY point of the track,
    nearest first. Closest approach rather than the start point, so a ride
    that began at home and rode out to the trail still finds it."""
    if not track:
        return []
    # A long ride can be thousands of points; the closest approach to a pin
    # is not sensitive to every one of them.
    step = max(1, len(track) // 500)
    sample = track[::step] + [track[-1]]
    ranked: list[tuple[models.Trail, float]] = []
    for t in trails:
        if t.latitude is None or t.longitude is None:
            continue
        d = min(haversine_km(lat, lon, t.latitude, t.longitude) for lat, lon in sample)
        if d <= max_km:
            ranked.append((t, d))
    ranked.sort(key=lambda x: x[1])
    return ranked[:limit]


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
# Status-board (RainoutLine DNIS) config — single-row table
# ------------------------------------------------------------------

class TrailStatusConfigBody(BaseModel):
    dnis: str | None = None


@router.get("/config")
async def get_trail_status_config(
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cfg = await db.get(models.TrailStatusConfig, 1)
    return {
        "dnis": cfg.dnis if cfg else None,
        "configured": bool(cfg and cfg.dnis),
        "updated_at": cfg.updated_at if cfg else None,
    }


@router.post("/config")
async def save_trail_status_config(
    body: TrailStatusConfigBody,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    raw = (body.dnis or "").strip()
    # Allow blank to clear
    cleaned: str | None = None
    if raw:
        digits = "".join(c for c in raw if c.isdigit())
        if len(digits) != 10:
            raise HTTPException(400, "DNIS must be 10 digits")
        cleaned = digits
    cfg = await db.get(models.TrailStatusConfig, 1)
    if cfg is None:
        cfg = models.TrailStatusConfig(
            id=1, dnis=cleaned, updated_at=datetime.now(timezone.utc),
        )
        db.add(cfg)
    else:
        cfg.dnis = cleaned
        cfg.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"dnis": cfg.dnis, "configured": bool(cfg.dnis)}


# ------------------------------------------------------------------
# List + detail
# ------------------------------------------------------------------

@router.get("")
async def list_trails(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Every status-board trail with its most recent snapshot + subscription
    state, plus `other_trails`: OSM trails an activity has been linked to
    (migration 0070). Those are kept out of `trails` because they have no
    status, and every consumer of that list — the board, the status counts,
    the open/closed filters — reads it as a list of trails WITH one."""
    trails = (await db.execute(
        select(models.Trail).where(models.Trail.dnis.is_not(None))
        .order_by(models.Trail.name)
    )).scalars().all()
    other = await _other_trails(db)
    if not trails:
        return {"count": 0, "trails": [], "other_trails": other, **status_summary([])}

    # DNIS — composes a top-of-page link to RainoutLine's full status
    # board. (Per-trail permalinks are still emitted in case the UI
    # ever wants them, but the dashboard shows a single shortcut.)
    cfg = await db.get(models.TrailStatusConfig, 1)
    dnis = cfg.dnis if cfg and cfg.dnis else None
    dnis_url = (
        f"https://rainoutline.com/search/dnis/{dnis}/updated" if dnis else None
    )

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
            "rainout_url": (
                f"https://rainoutline.com/search/extension/{dnis}/{t.extension}"
                if dnis else None
            ),
        })
    return {
        "count": len(out), "trails": out, "dnis_url": dnis_url,
        "other_trails": other,
        **status_summary(out),
    }


async def _other_trails(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(models.Trail).where(models.Trail.dnis.is_(None))
        .order_by(models.Trail.name)
    )).scalars().all()
    if not rows:
        return []
    counts = {
        tid: (n, last) for tid, n, last in (await db.execute(
            select(models.Activity.trail_id, func.count(models.Activity.source_id),
                   func.max(models.Activity.start_at))
            .where(models.Activity.trail_id.in_([t.id for t in rows]))
            .group_by(models.Activity.trail_id)
        )).all()
    }
    return [
        {"id": t.id, "name": t.name, "city": t.city, "state": t.state,
         "osm_trail_id": t.osm_trail_id,
         "visits_total": counts.get(t.id, (0, None))[0],
         "last_visit_at": counts.get(t.id, (0, None))[1]}
        for t in rows
    ]


@router.post("/trailmap/refresh")
async def trailmap_refresh(
    force: bool = False,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pull OSM trails from the trailmap state packs now (it also runs
    daily). force=true re-imports packs that are already current."""
    from ..integrations.trailmap import refresh
    try:
        return await refresh(db, force=force)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"trailmap fetch failed: {e}") from e


@router.get("/trailmap/status")
async def trailmap_status(db: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Which state packs are imported, how many trails each, and when built."""
    rows = (await db.execute(
        select(models.OsmTrail.state, func.count(models.OsmTrail.id),
               func.max(models.OsmTrail.pack_built))
        .group_by(models.OsmTrail.state)
    )).all()
    return {"states": [{"state": s, "trails": n, "built": b} for s, n, b in rows]}


@router.get("/daily")
async def trails_daily(
    since: date = Query(...),
    until: date | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Per local day: trails open at 07:00, and closures / reopenings that day.

    One row per day in [since, until] (until defaults to, and is clamped to,
    today; at most 400 days per call): `{date, in_progress, open_at_0700,
    delayed_at_0700, known_at_0700, total, closures, reopenings}` — all
    counts of trails. `unknown` / `pending` are excluded from `known_at_0700`
    (unknown is not closed). See analytics/trail_days.py for the rules.
    """
    from ..analytics import trail_days
    from ..localtime import bounded_day_range, local_today, local_tz

    try:
        since, end = bounded_day_range(since, until, trail_days.MAX_RANGE_DAYS)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return await trail_days.trail_days(db, since, end, local_tz(), local_today())


def status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """UI-5 — the Trails hero's numbers, counted once here.

    `status_counts` buckets every trail into open / delayed / closed /
    other ("other" is anything RainoutLine reports that is none of the
    three, plus a trail with no snapshot yet — unknown is not closed).
    `synced_at` is the newest snapshot fetch across all trails: when the
    board was last read, which is what "synced 4m ago" claims.
    """
    counts = {"open": 0, "delayed": 0, "closed": 0, "other": 0}
    synced: datetime | None = None
    for r in rows:
        st = r.get("status")
        counts[st if st in ("open", "delayed", "closed") else "other"] += 1
        f = r.get("fetched_at")
        if f is not None and (synced is None or f > synced):
            synced = f
    return {"status_counts": counts, "synced_at": synced}


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


@router.post("/{trail_id}/fetch-osm-paths")
async def fetch_osm_paths(
    trail_id: int, radius_m: float = 500,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pull trail geometry from OpenStreetMap via Overpass for this
    trail's pin. Caches the GeoJSON in trails.osm_paths_geojson so
    we're not hitting Overpass repeatedly. Free, no API key."""
    from ..integrations.osm import cache_paths_for_trail
    try:
        return await cache_paths_for_trail(trail_id, radius_m=radius_m)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"overpass failed: {e}") from e


@router.get("/{trail_id}/osm-paths")
async def get_osm_paths(
    trail_id: int,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the cached OSM path GeoJSON for a trail (404 if never
    fetched). Used by the frontend map overlay."""
    t = await db.get(models.Trail, trail_id)
    if t is None:
        raise HTTPException(status_code=404, detail="trail not found")
    if t.osm_paths_geojson is None:
        raise HTTPException(
            status_code=404,
            detail="no cached OSM paths — POST /fetch-osm-paths first",
        )
    return {
        "trail_id": trail_id, "name": t.name,
        "fetched_at": t.osm_paths_fetched_at,
        "geojson": t.osm_paths_geojson,
    }


@router.post("/fetch-all-osm-paths")
async def fetch_all_osm_paths(
    radius_m: float = 500,
    relink: bool = False,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Bulk pull OSM paths for every pinned trail. Skips trails that
    already have cached paths unless relink=true. Sleeps ~1 s between
    queries to be a polite Overpass citizen."""
    import asyncio
    from ..integrations.osm import cache_paths_for_trail

    trails_with_pins = (await db.execute(
        select(models.Trail).where(models.Trail.latitude.is_not(None))
    )).scalars().all()
    fetched = 0
    skipped = 0
    failed = 0
    for t in trails_with_pins:
        if t.osm_paths_geojson is not None and not relink:
            skipped += 1
            continue
        try:
            await cache_paths_for_trail(t.id, radius_m=radius_m)
            fetched += 1
            await asyncio.sleep(1.2)   # polite wait between Overpass calls
        except Exception:  # noqa: BLE001
            failed += 1
    return {
        "fetched": fetched, "skipped": skipped, "failed": failed,
        "total_with_pins": len(trails_with_pins),
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
    base = Path(__file__).resolve().parent.parent / "data"
    p = base / "trail_locations.json"
    if not p.exists():
        # Fresh checkouts get only the .example stub. Treat as empty seed.
        p = base / "trail_locations.json.example"
        if not p.exists():
            raise HTTPException(
                status_code=404,
                detail="trail_locations.json not found in data/",
            )
    data: dict[str, Any] = json.loads(p.read_text() or "{}")
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
