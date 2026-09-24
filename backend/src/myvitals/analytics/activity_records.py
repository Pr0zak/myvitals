"""Personal records and the period-stats filter for the Activities feed (UI-F2).

UI-5 rebuilt the web feed and dropped its personal-records card, which had
been computed in the browser from whatever rows the page happened to load:
a record was "the longest ride in the last 90 days of what we fetched",
silently different from the phone (which never had the card at all). The
records now come from here, over the same window and category filter the
feed shows, so both clients print the same record for the same selection.

Rules this module holds:

* **Null, never zero.** A record with no qualifying activity is ``None``.
  A ride with no distance is not a 0 km record, and a category with no
  suffer scores has no "highest suffer score" — printing 0 would read as a
  measured result.
* **Category mapping is the clients' mapping.** ``category_for_type`` is a
  line-for-line port of ``frontend/src/utils/activityCategory.ts`` and
  ``ui/common/ActivityCategory.kt`` (the feed's filter chips and icon
  tints), so "Ride" here is exactly the set of rows the Ride chip shows.
* **Fastest is only asked where it means something.** Pace across a ride
  and a walk is not a comparison, so ``fastest`` exists for the ride and
  run categories only, and only over a minimum distance: a 150 m GPS blip
  at 40 km/h is not the user's fastest ride.

Pure — rows in, dict out — so it is testable without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: The feed's filter-chip categories, in the clients' order.
ACTIVITY_CATEGORIES: tuple[str, ...] = (
    "ride", "run", "walk", "row", "strength", "yoga", "other",
)

_EXACT: dict[str, str] = {
    "ride": "ride", "ebikeride": "ride", "mountain_biking": "ride", "cycling": "ride",
    "run": "run", "trailrun": "run", "running": "run",
    "hike": "walk", "walk": "walk", "walking": "walk",
    "rower": "row", "rowing": "row", "row": "row",
}


def category_for_type(type_: str | None) -> str:
    """Classify a raw activity ``type`` — the clients' mapping, verbatim.

    Order matters: "row" before "run" (kayak/paddle), and "run" before
    "walk" because several MyFitnessPal labels contain both words.
    """
    t = (type_ or "").lower()
    if t in _EXACT:
        return _EXACT[t]
    if not t:
        return "other"
    if re.search(r"kayak|row|paddle|canoe", t):
        return "row"
    if re.search(r"run|jog", t):
        return "run"
    if re.search(r"hike|walk", t):
        return "walk"
    if re.search(r"bike|cycl|ride", t):
        return "ride"
    if re.search(r"strength|weight|lifting", t):
        return "strength"
    if re.search(r"yoga|pilates|mobility", t):
        return "yoga"
    return "other"


#: Shortest effort a "fastest" record will consider, per category. Below
#: this a GPS glitch or a lap around the car park wins the record.
FASTEST_MIN_DISTANCE_M: dict[str, float] = {"run": 1_000.0, "ride": 5_000.0}

#: How each category's fastest is best read: a runner thinks in pace
#: (time per distance), a cyclist in speed. The value is m/s either way;
#: the client converts it to the user's units.
FASTEST_DISPLAY: dict[str, str] = {"run": "pace", "ride": "speed"}


@dataclass(frozen=True)
class Row:
    source: str
    source_id: str
    name: str | None
    type: str
    start_at: datetime
    day: date  # the user's LOCAL day
    duration_s: int | None
    distance_m: float | None
    elevation_m: float | None
    suffer_score: float | None


def _ref(r: Row) -> dict[str, Any]:
    return {
        "source": r.source, "source_id": r.source_id, "name": r.name,
        "type": r.type, "start_at": r.start_at.isoformat(), "date": r.day.isoformat(),
    }


def _best(rows: list[Row], value) -> tuple[float, Row] | None:
    best: tuple[float, Row] | None = None
    for r in rows:
        v = value(r)
        if v is None or v <= 0:
            continue
        # Ties go to the EARLIER effort — the one that set the record.
        if best is None or v > best[0] or (v == best[0] and r.start_at < best[1].start_at):
            best = (float(v), r)
    return best


def _record(key: str, label: str, unit: str, found: tuple[float, Row] | None,
            **extra: Any) -> dict[str, Any]:
    return {
        "key": key, "label": label, "unit": unit,
        "value": round(found[0], 3) if found else None,
        "activity": _ref(found[1]) if found else None,
        **extra,
    }


def _speed(r: Row, min_distance: float) -> float | None:
    if not r.distance_m or not r.duration_s or r.duration_s <= 0:
        return None
    if r.distance_m < min_distance:
        return None
    return r.distance_m / r.duration_s


def personal_records(rows: list[Row], category: str | None) -> dict[str, Any]:
    """Records over ``rows`` (already windowed by the caller).

    ``category`` None / "all" means every activity. Rows are filtered here
    with ``category_for_type`` so the caller cannot use a different mapping.
    """
    cat = None if category in (None, "", "all") else category
    pool = [r for r in rows if cat is None or category_for_type(r.type) == cat]
    records = [
        _record("longest_distance", "Longest distance", "m",
                _best(pool, lambda r: r.distance_m)),
        _record("longest_duration", "Longest time", "s",
                _best(pool, lambda r: r.duration_s)),
        _record("most_elevation", "Most climbing", "m",
                _best(pool, lambda r: r.elevation_m)),
        _record("highest_suffer", "Highest suffer score", "",
                _best(pool, lambda r: r.suffer_score)),
    ]
    if cat in FASTEST_MIN_DISTANCE_M:
        min_d = FASTEST_MIN_DISTANCE_M[cat]
        records.append(_record(
            "fastest", "Fastest pace" if FASTEST_DISPLAY[cat] == "pace" else "Fastest average",
            "m/s", _best(pool, lambda r: _speed(r, min_d)),
            display=FASTEST_DISPLAY[cat], min_distance_m=min_d,
        ))
    return {
        "category": cat or "all",
        "n_considered": len(pool),
        "records": records,
    }
