"""Track geometry helpers — polyline simplification for map overviews.

The activities table stores full-fidelity Google-encoded polylines (avg
~6 KB, worst case ~27 KB). Shipping all ~560 of them to a client is
~3.4 MB, which is unreasonable over mobile data for a view where every
track is a few hundred pixels wide.

Ramer-Douglas-Peucker drops interior points that sit within `epsilon` of
the line between their neighbours, so straight sections collapse to two
points while switchbacks keep their shape. At the default 1e-4 degrees
(~11 m) an overview map is visually identical to the full track.
"""
from __future__ import annotations

import polyline as _polyline

# ~11 m at the equator. Detail below this is invisible at overview zoom.
DEFAULT_EPSILON_DEG = 1e-4
# Backstop for pathological tracks (GPS noise while stationary) that RDP
# can't thin enough on its own.
DEFAULT_MAX_POINTS = 400


def _perpendicular_distance(
    pt: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Distance from `pt` to the segment start-end, in degrees.

    Treats lat/lon as a plane. Fine at the scale of a single activity —
    we're choosing which points to drop, not measuring anything a user
    sees.
    """
    (x, y), (x1, y1), (x2, y2) = pt, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    # Project onto the segment, clamped to its endpoints.
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def rdp(
    points: list[tuple[float, float]], epsilon: float = DEFAULT_EPSILON_DEG
) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker, iterative so long tracks can't blow the stack.

    A 27 KB polyline decodes to ~5000 points; the recursive form bottoms
    out around Python's default 1000-frame limit on degenerate input.
    """
    if len(points) < 3:
        return list(points)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack: list[tuple[int, int]] = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        max_dist, index = 0.0, first
        for i in range(first + 1, last):
            d = _perpendicular_distance(points[i], points[first], points[last])
            if d > max_dist:
                max_dist, index = d, i
        if max_dist > epsilon:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))

    return [p for p, k in zip(points, keep) if k]


def _decimate(
    points: list[tuple[float, float]], max_points: int
) -> list[tuple[float, float]]:
    """Evenly thin to at most `max_points`, always keeping both ends."""
    if len(points) <= max_points or max_points < 2:
        return points
    step = (len(points) - 1) / (max_points - 1)
    out = [points[round(i * step)] for i in range(max_points)]
    out[-1] = points[-1]
    return out


def simplify_encoded(
    encoded: str,
    epsilon: float = DEFAULT_EPSILON_DEG,
    max_points: int = DEFAULT_MAX_POINTS,
) -> tuple[str, int, int]:
    """Decode → RDP → cap → re-encode.

    Returns `(encoded, original_point_count, simplified_point_count)`. A
    polyline that fails to decode yields `("", 0, 0)` rather than raising —
    one corrupt row shouldn't take down the whole map.
    """
    if not encoded:
        return "", 0, 0
    try:
        points = _polyline.decode(encoded)
    except Exception:
        return "", 0, 0
    if not points:
        return "", 0, 0
    simplified = _decimate(rdp(points, epsilon), max_points)
    return _polyline.encode(simplified), len(points), len(simplified)


def bounds_of(points: list[tuple[float, float]]) -> list[float] | None:
    """[south, west, north, east] for a set of lat/lon points."""
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return [min(lats), min(lons), max(lats), max(lons)]
