"""Import named trails from the trailmap project's OSM state packs.

trailmap (a separate app in the same homelab) publishes one zip per US
state on the `trailpack` prerelease of its public GitHub repo, rebuilt
weekly from Geofabrik OpenStreetMap extracts. Each zip holds 0.25° tiles of
Overpass-style `out geom` JSON: `all/` (named walking/biking paths of every
surface) and `mtb/` (mountain-bike trails), plus `parks/`, which is not
used here. See trailmap's CLAUDE.md, "Trail packs".

Only states the user's own rides touch are fetched, and a state is only
re-downloaded when its pack is newer than the stored copy. The packs are
public data; no token, nothing about the user is sent.
"""
from __future__ import annotations

import io
import json
import logging
import math
import zipfile
from collections import Counter, defaultdict
from typing import Any

import httpx
import polyline as polyline_lib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import models

log = logging.getLogger(__name__)

RELEASE_BASE = "https://github.com/Pr0zak/trailmap/releases/download/trailpack"
INDEX_URL = f"{RELEASE_BASE}/trailpack-index.json"
USER_AGENT = "myvitals-trailmap-import (+self-hosted)"
KINDS = ("all", "mtb")
# Ways sharing a name are one trail only if they sit this close together;
# "Nature Trail" in two parks forty miles apart is two trails.
CLUSTER_M = 2_000.0


_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district-of-columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new-hampshire": "NH", "new-jersey": "NJ", "new-mexico": "NM", "new-york": "NY",
    "north-carolina": "NC", "north-dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode-island": "RI", "south-carolina": "SC",
    "south-dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west-virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def state_abbr(slug: str) -> str:
    """Pack slug ("kansas") → the two-letter code `trails.state` holds."""
    return _STATES.get(slug, slug[:8].upper())


def _hav_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def primary_name(raw: str | None) -> str | None:
    """OSM joins alternative names with ';' ("Gary L. Haller Trail;Mill
    Creek Trail"). The first is the one signage uses."""
    if not raw:
        return None
    name = raw.split(";")[0].strip()
    return name or None


def parse_pack(data: bytes) -> list[dict[str, Any]]:
    """A state pack zip → one dict per named trail cluster.

    Pure (bytes in, rows out), so tests can feed it a synthetic zip.
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    seen: set[int] = set()
    # name -> list of (kind, surface, [(lat, lon), ...])
    ways: dict[str, list[tuple[str, str | None, list[tuple[float, float]]]]] = defaultdict(list)
    for member in zf.namelist():
        kind = member.split("/", 1)[0]
        if kind not in KINDS or not member.endswith(".json"):
            continue
        doc = json.loads(zf.read(member))
        for el in doc.get("elements", []) if isinstance(doc, dict) else doc:
            if el.get("type") != "way" or el.get("id") in seen:
                continue
            tags = el.get("tags") or {}
            name = primary_name(tags.get("name"))
            geom = [(g["lat"], g["lon"]) for g in el.get("geometry") or [] if g]
            if not name or len(geom) < 2:
                continue
            seen.add(el["id"])
            ways[name].append((kind, tags.get("surface"), geom))

    rows: list[dict[str, Any]] = []
    for name, ws in ways.items():
        for cluster in _cluster(ws):
            pts = [p for _, _, g in cluster for p in g]
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            clat, clon = sum(lats) / len(lats), sum(lons) / len(lons)
            surfaces = Counter(s for _, s, _ in cluster if s)
            rows.append({
                "name": name[:255],
                "key": f"{name[:280]}@{clat:.2f},{clon:.2f}",
                "kind": "mtb" if any(k == "mtb" for k, _, _ in cluster) else "all",
                "surface": surfaces.most_common(1)[0][0][:32] if surfaces else None,
                "paths": [polyline_lib.encode(g) for _, _, g in cluster],
                "length_m": sum(_hav_m(a, b) for _, _, g in cluster for a, b in zip(g, g[1:])),
                "min_lat": min(lats), "max_lat": max(lats),
                "min_lon": min(lons), "max_lon": max(lons),
            })
    return rows


def _cluster(ws: list[tuple[str, str | None, list[tuple[float, float]]]]):
    """Group same-named ways whose endpoints come within CLUSTER_M.
    Union-find over way pairs; a state rarely has more than a few dozen
    ways under one name, so the pairwise pass is cheap."""
    parent = list(range(len(ws)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends = [(g[0], g[-1], g[len(g) // 2]) for _, _, g in ws]
    for i in range(len(ws)):
        for j in range(i + 1, len(ws)):
            if find(i) == find(j):
                continue
            if min(_hav_m(a, b) for a in ends[i] for b in ends[j]) <= CLUSTER_M:
                parent[find(i)] = find(j)
    groups: dict[int, list] = defaultdict(list)
    for i, w in enumerate(ws):
        groups[find(i)].append(w)
    return list(groups.values())


async def _ride_points(db: AsyncSession) -> list[tuple[float, float]]:
    """One start point per GPS activity — enough to say which states the
    user rides in."""
    rows = (await db.execute(
        select(models.Activity.polyline_simple, models.Activity.polyline)
        .where((models.Activity.polyline_simple.is_not(None))
               | (models.Activity.polyline.is_not(None)))
    )).all()
    pts: set[tuple[float, float]] = set()
    for simple, full in rows:
        try:
            dec = polyline_lib.decode(simple or full)
        except Exception:  # noqa: BLE001
            continue
        if dec:
            pts.add((round(dec[0][0], 2), round(dec[0][1], 2)))
    return list(pts)


def states_for(index: dict[str, Any], points: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """Index entries whose bbox ([w, s, e, n]) holds any of the points."""
    out = []
    for st in index.get("states", []):
        w, s, e, n = st["bbox"]
        if any(s <= lat <= n and w <= lon <= e for lat, lon in points):
            out.append(st)
    return out


async def refresh(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """Fetch the index, then every relevant state pack that is newer than
    what is stored. Upserts by (state, key) so the ids that linked `trails`
    rows point at survive a rebuild; a trail that vanished from OSM is only
    deleted when nothing links to it."""
    points = await _ride_points(db)
    if not points:
        return {"states": [], "note": "no GPS activities yet"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(INDEX_URL)
        r.raise_for_status()
        index = r.json()
        report: dict[str, Any] = {"states": []}
        for st in states_for(index, points):
            slug = st["slug"]
            stored = (await db.execute(
                select(models.OsmTrail.pack_built)
                .where(models.OsmTrail.state == slug).limit(1)
            )).scalar_one_or_none()
            if stored == st.get("built") and not force:
                report["states"].append({"state": slug, "skipped": "up to date"})
                continue
            z = await client.get(f"{RELEASE_BASE}/{st['asset']}")
            z.raise_for_status()
            rows = parse_pack(z.content)
            report["states"].append({"state": slug, **await _upsert(db, slug, st.get("built"), rows)})
    return report


async def _upsert(db: AsyncSession, slug: str, built: str | None,
                  rows: list[dict[str, Any]]) -> dict[str, int]:
    existing = {t.key: t for t in (await db.execute(
        select(models.OsmTrail).where(models.OsmTrail.state == slug)
    )).scalars().all()}
    linked = set((await db.execute(
        select(models.Trail.osm_trail_id).where(models.Trail.osm_trail_id.is_not(None))
    )).scalars().all())
    added = updated = removed = 0
    keys = set()
    for row in rows:
        if row["key"] in keys:      # two clusters rounding to one key
            continue
        keys.add(row["key"])
        t = existing.get(row["key"])
        if t is None:
            db.add(models.OsmTrail(state=slug, pack_built=built, **row))
            added += 1
        else:
            for k, v in row.items():
                setattr(t, k, v)
            t.pack_built = built
            updated += 1
    for key, t in existing.items():
        if key not in keys and t.id not in linked:
            await db.delete(t)
            removed += 1
    await db.commit()
    log.info("trailmap %s: %d added, %d updated, %d removed", slug, added, updated, removed)
    return {"added": added, "updated": updated, "removed": removed}
