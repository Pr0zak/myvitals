"""This week's lifting volume against last week's, day by day (UI-1).

The Train tab's weekly card used to sum `/stats.daily` on the phone: filter
rows by "days ago", add them up, and divide for a week-over-week percentage.
Three rules broke at once. A number the user reads was derived in a client
(the web never showed it at all, so the two surfaces disagreed by
construction); "days ago" was measured against the PHONE's clock while the
rows were dated by the server; and whether a fall in volume was good news was
decided by a hard-coded `up -> lime`. This module is the one answer.

Window: the trailing seven LOCAL days ending today, against the seven before
it. Deliberately not the calendar week. A Monday-anchored week would compare
Monday-to-Wednesday against a whole previous week every midweek and report a
steep fall that is only the calendar — the kind of number that is wrong most
days of the week and so gets ignored the one day it matters. Each column's
ghost is the same weekday seven days earlier, so the chart pairs like with
like.

A day with nothing logged is a real 0 lb, not a missing reading: volume is a
sum of work performed, and no work was performed. What the pounds figure
CANNOT speak for is bodyweight work, so each day also reports its set count
and the total reports how many sets carried no poundage (the OG2-A3 rule).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

WINDOW_DAYS = 7

# Below this, the change is reported as flat. A single extra warm-up-sized
# set moves a week's tonnage by a percent or two; painting that lime or amber
# would colour noise.
FLAT_BAND_PCT = 2.0


def week_volume(
    daily_volume_lb: dict[date, float],
    daily_sets: dict[date, int],
    today: date,
    unweighted_sets_this_week: int = 0,
) -> dict[str, Any]:
    """Seven local days ending `today`, each paired with the day a week before.

    `daily_volume_lb` / `daily_sets` are keyed by the workout's LOCAL date and
    must already cover both windows (today-13 .. today).
    """
    days: list[dict[str, Any]] = []
    total = 0.0
    prev_total = 0.0
    for i in range(WINDOW_DAYS - 1, -1, -1):
        d = today - timedelta(days=i)
        p = d - timedelta(days=WINDOW_DAYS)
        v = float(daily_volume_lb.get(d, 0.0))
        pv = float(daily_volume_lb.get(p, 0.0))
        total += v
        prev_total += pv
        days.append({
            "date": d.isoformat(),
            "volume_lb": round(v, 1),
            "sets": int(daily_sets.get(d, 0)),
            "prev_date": p.isoformat(),
            "prev_volume_lb": round(pv, 1),
        })

    # No previous week to compare against is "no comparison", never +100%.
    delta_pct: float | None
    direction: str | None
    if prev_total <= 0:
        delta_pct = None
        direction = None
    else:
        delta_pct = round((total - prev_total) / prev_total * 100.0, 1)
        if abs(delta_pct) < FLAT_BAND_PCT:
            direction = "flat"
        else:
            # `better` below is "higher", so up is the improvement. Decided
            # here, once, so neither client picks the colour.
            direction = "improved" if delta_pct > 0 else "worse"

    return {
        "start": (today - timedelta(days=WINDOW_DAYS - 1)).isoformat(),
        "end": today.isoformat(),
        "days": days,
        "total_lb": round(total, 1),
        "prev_total_lb": round(prev_total, 1),
        "delta_pct": delta_pct,
        "better": "higher",
        "direction": direction,
        "unweighted_sets": int(unweighted_sets_this_week),
    }


def next_up(exercises: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The slot the user would log next, and which set of it.

    `exercises` are dicts with `exercise_id`, `name`, `order_index`,
    `target_sets`, `accounted_sets` and `done` — `done` and `accounted_sets`
    come from the SAME predicates that produce `exercises_done`/`sets_done`,
    so the hero's button can never name a slot the counters call finished.
    Returns None when nothing is left.
    """
    remaining = [e for e in exercises if not e["done"]]
    if not remaining:
        return None
    e = min(remaining, key=lambda r: r["order_index"])
    return {
        "exercise_id": e["exercise_id"],
        "name": e["name"],
        "set_number": min(int(e["accounted_sets"]) + 1, max(int(e["target_sets"]), 1)),
        "target_sets": int(e["target_sets"]),
        # True once any set of the session has been dealt with — the client
        # labels the button "Continue" rather than "Start" off this, not off
        # its own reading of the counters.
        "started": any(int(r["accounted_sets"]) > 0 for r in exercises),
    }
