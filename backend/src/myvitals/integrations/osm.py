"""OpenStreetMap Overpass API — pull trail geometry near a coordinate.

We query a small bounding box around a trail's pin and collect every
`way` tagged as walkable/bikeable singletrack: highway=path, track,
footway, cycleway. The returned GeoJSON FeatureCollection is cached
in `trails.osm_paths_geojson` so we hit Overpass at most once per
trail. (Trail networks change rarely.)

Overpass terms of service:
- No auth required, but they ask for a real User-Agent.
- Soft rate limit: a few seconds per query, ~1-2 sec wait if the
  load is high. We're hitting it at human pace, no problem.
- The /api/interpreter endpoint is the public one; falls back
  gracefully if the primary host is busy.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models, session as _session

log = logging.getLogger(__name__)

# Public mirrors. Try in order; first one that responds wins.
OVERPASS_HOSTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
)
USER_AGENT = "myvitals/0.7 (self-hosted personal health app)"


def _bbox_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Approx bounding box `(south, west, north, east)` for a radius
    in meters around the given point. Uses the simple equirectangular
    approximation — fine for sub-1km bboxes at moderate latitudes."""
    deg_lat = radius_m / 111_320.0
    deg_lon = radius_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
    return lat - deg_lat, lon - deg_lon, lat + deg_lat, lon + deg_lon


def _build_query(lat: float, lon: float, radius_m: float) -> str:
    """Overpass QL query for trail-like ways within a radius around a point."""
    south, west, north, east = _bbox_around(lat, lon, radius_m)
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    # Capture singletrack / paths / cycleway / footway. `route=mtb`
    # relations would also help but adding them complicates the geom
    # assembly; ways alone cover most of what KC trails are tagged as.
    return f"""
[out:json][timeout:25];
(
  way["highway"="path"]({bbox});
  way["highway"="track"]({bbox});
  way["highway"="footway"]({bbox});
  way["highway"="cycleway"]({bbox});
  way["highway"="bridleway"]({bbox});
);
out body geom;
""".strip()


def _to_geojson(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert Overpass's `way` elements (with embedded geom) to a GeoJSON
    FeatureCollection. Each way → LineString with its tags as properties.
    """
    features: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        coords = [[g["lon"], g["lat"]] for g in geom]
        tags = el.get("tags") or {}
        # Trim to the tags we actually use to keep payload small.
        keep = {
            k: tags[k]
            for k in (
                "highway", "name", "surface", "bicycle", "foot",
                "mtb:scale", "route", "trail_visibility",
            )
            if k in tags
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"id": el.get("id"), **keep},
        })
    return {"type": "FeatureCollection", "features": features}


async def fetch_paths_near(
    lat: float, lon: float, radius_m: float = 500,
) -> dict[str, Any]:
    """Query Overpass for trail-like ways near a point. Returns a GeoJSON
    FeatureCollection (possibly empty). Falls back across mirrors if the
    primary host returns 429 / 504 / fails."""
    query = _build_query(lat, lon, radius_m)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for host in OVERPASS_HOSTS:
            try:
                r = await client.post(host, data={"data": query}, headers=headers)
                if r.status_code in (429, 503, 504):
                    log.warning("overpass %s: %d, trying next mirror", host, r.status_code)
                    continue
                r.raise_for_status()
                payload = r.json()
                elements = payload.get("elements") or []
                return _to_geojson(elements)
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("overpass %s failed: %s", host, e)
    if last_err:
        raise last_err
    return {"type": "FeatureCollection", "features": []}


async def cache_paths_for_trail(
    trail_id: int, radius_m: float = 500,
) -> dict[str, Any]:
    """Fetch + persist OSM paths for a single trail. Caller must commit
    the session — actually no, we open our own session here so external
    callers can fire-and-forget from API endpoints / scheduler."""
    async with _session.SessionLocal() as db:
        t = await db.get(models.Trail, trail_id)
        if t is None:
            raise ValueError(f"trail {trail_id} not found")
        if t.latitude is None or t.longitude is None:
            raise ValueError(f"trail {trail_id} ({t.name}) has no pin")
        gj = await fetch_paths_near(t.latitude, t.longitude, radius_m)
        t.osm_paths_geojson = gj
        t.osm_paths_fetched_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "trail_id": trail_id, "name": t.name,
            "feature_count": len(gj.get("features") or []),
            "fetched_at": t.osm_paths_fetched_at,
        }
