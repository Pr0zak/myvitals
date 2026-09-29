"""Which OSM trails did a ride actually use?

Pure — points in, numbers out — so it is testable without a database.

A pin cannot answer this for a trail that is a line. The Gary L. Haller
Trail is 16 miles of greenway; its "location" is every point along it, and a
ride on it can be nowhere near any single pin. So a ride is matched against
the trail's own paths, and a trail is scored by how much of the ride ran
along it (`on_trail_m`), not by how close the ride came to it once. Closest
approach alone would rank every connector and footbridge crossed at zero
distance alongside the trail the ride followed for ten miles.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

# A ride point within this distance of a trail segment counts as on it.
# Phone/watch GPS drifts ~5-15 m and OSM geometry a few more; 35 m keeps a
# parallel street a block away (~80 m+) from being credited as the trail.
ON_TRAIL_M = 35.0
# A trail needs at least this much of the ride on it to be suggested — below
# it, the ride merely crossed the trail.
MIN_ON_TRAIL_M = 300.0
_CELL_M = 100.0
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON_EQ = 111_320.0


@dataclass
class TrailMatch:
    key: int                  # caller's id for the trail
    on_trail_m: float         # ride distance within ON_TRAIL_M of the trail
    closest_m: float          # closest approach of the ride to the trail


class _Proj:
    """Equirectangular projection around the ride — metres, good to well
    under 1% across a city, which is all a 35 m threshold needs."""

    def __init__(self, lat0: float):
        self.kx = _M_PER_DEG_LON_EQ * math.cos(math.radians(lat0))

    def __call__(self, lat: float, lon: float) -> tuple[float, float]:
        return lon * self.kx, lat * _M_PER_DEG_LAT


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def match_trails(
    track: list[tuple[float, float]],
    trails: list[tuple[int, list[list[tuple[float, float]]]]],
    *,
    on_trail_m: float = ON_TRAIL_M,
    min_on_trail_m: float = MIN_ON_TRAIL_M,
) -> list[TrailMatch]:
    """Score each trail by how much of `track` ran along it.

    `trails` is `[(key, [path, ...])]`, each path a list of (lat, lon).
    Returns trails with at least `min_on_trail_m` of the ride on them, most
    ridden first. A ride point may count toward more than one trail — two
    named paths can share a corridor — because each score answers "how much
    of this ride was on THIS trail", independently.
    """
    if len(track) < 2 or not trails:
        return []
    # Bound the work on a long ride; a 60 m step is still far finer than a
    # trail worth suggesting.
    step = max(1, len(track) // 1500)
    pts = track[::step]
    if pts[-1] != track[-1]:
        pts.append(track[-1])

    proj = _Proj(sum(p[0] for p in pts) / len(pts))
    P = [proj(lat, lon) for lat, lon in pts]

    # Grid of trail segments, so each ride point only looks at segments in
    # its own and neighbouring cells.
    grid: dict[tuple[int, int], list[tuple[int, float, float, float, float]]] = defaultdict(list)
    for key, paths in trails:
        for path in paths:
            Q = [proj(lat, lon) for lat, lon in path]
            for (ax, ay), (bx, by) in zip(Q, Q[1:]):
                # Register the segment in every cell its bbox touches.
                for cx in range(int(min(ax, bx) // _CELL_M), int(max(ax, bx) // _CELL_M) + 1):
                    for cy in range(int(min(ay, by) // _CELL_M), int(max(ay, by) // _CELL_M) + 1):
                        grid[(cx, cy)].append((key, ax, ay, bx, by))

    on: dict[int, float] = defaultdict(float)
    closest: dict[int, float] = {}
    for i, (px, py) in enumerate(P):
        step_m = math.hypot(px - P[i - 1][0], py - P[i - 1][1]) if i else 0.0
        cx, cy = int(px // _CELL_M), int(py // _CELL_M)
        near: dict[int, float] = {}
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for key, ax, ay, bx, by in grid.get((gx, gy), ()):
                    d = _seg_dist(px, py, ax, ay, bx, by)
                    if d < near.get(key, math.inf):
                        near[key] = d
        for key, d in near.items():
            if d < closest.get(key, math.inf):
                closest[key] = d
            if d <= on_trail_m:
                on[key] += step_m

    out = [TrailMatch(k, m, closest[k]) for k, m in on.items() if m >= min_on_trail_m]
    out.sort(key=lambda t: -t.on_trail_m)
    return out
