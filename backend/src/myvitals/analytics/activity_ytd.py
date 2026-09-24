"""Year-to-date training totals against the same point last year (UI-5).

Before this, the comparison was computed on three clients from a raw
18-month activity list: ``YtdYoyCard`` in ActivitiesScreen.kt, the shared
``computeYtdComparison`` the phone Train tab uses, and ``ytdStats`` in
Activities.vue. They disagreed in exactly the ways a copied loop drifts:

* the phone card counted a strength session's NET duration, the shared
  helper its GROSS elapsed time, and the web the gross time again;
* every copy bucketed by the device's local date, which is not the user's
  zone when the backend and the phone disagree;
* all three reported "+100%" when last year was zero, which is not a
  percentage of anything — it is a number invented to fill the cell;
* a shortfall was painted in the crisis colour.

This module is pure (entries in, dict out) so it is testable without a
database, and it owns ``better``/``tone`` for the same reason
``analytics/compare.py`` does: a client that decides for itself whether a
falling number is bad news eventually decides wrong.

Deliberately not a claim that more training is always better. ``tone`` is
"caution" (amber) for a shortfall, never a crisis colour: being behind last
year's pace is information, not an alarm.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class Entry:
    """One finished session on the user's LOCAL calendar day."""

    day: date
    duration_s: int
    distance_m: float | None = None
    elevation_m: float | None = None


#: (key, label, unit). Ordered — clients render in this order.
_METRICS: tuple[tuple[str, str, str], ...] = (
    ("sessions", "Sessions", ""),
    ("distance_m", "Distance", "m"),
    ("duration_s", "Moving time", "s"),
    ("elevation_m", "Climbed", "m"),
)


def same_day_last_year(today: date) -> date:
    """Today's month/day one year back; 29 Feb falls back to the 28th."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def week_start(d: date) -> date:
    """The local Monday on or before ``d``."""
    return d - timedelta(days=d.weekday())


def _metric(key: str, label: str, unit: str, cur: float, prior: float) -> dict[str, Any]:
    delta = cur - prior
    if prior == 0:
        # No baseline: a percentage of zero is not a number, and "+100%"
        # was the invented stand-in all three clients used to print.
        pct = None
        if cur == 0:
            direction, tone, note = "flat", "neutral", None
        else:
            direction, tone, note = "new", "positive", "new"
    else:
        pct = round(delta / prior * 100.0, 1)
        # Flat at the display precision (whole percent): a change nobody
        # can see in the rendered number is not a direction.
        if round(pct) == 0:
            direction, tone = "flat", "neutral"
        elif delta > 0:
            direction, tone = "improved", "positive"
        else:
            direction, tone = "worse", "caution"
        note = None
    return {
        "key": key, "label": label, "unit": unit, "better": "higher",
        "current": round(cur, 1), "prior": round(prior, 1),
        "delta": round(delta, 1), "pct_change": pct,
        "direction": direction, "tone": tone, "note": note,
    }


def _cumulative(entries: list[Entry], year: int, last_day: date) -> list[int]:
    """Cumulative distance (whole metres) for each day of ``year`` up to and
    including ``last_day``; index 0 is 1 January."""
    start = date(year, 1, 1)
    n = (last_day - start).days + 1
    if n <= 0:
        return []
    daily = [0.0] * n
    for e in entries:
        if e.day.year != year or e.distance_m is None:
            continue
        i = (e.day - start).days
        if 0 <= i < n:
            daily[i] += e.distance_m
    out: list[int] = []
    run = 0.0
    for v in daily:
        run += v
        out.append(int(round(run)))
    return out


def ytd_compare(
    entries: list[Entry],
    today: date,
    *,
    weeks_back: int = 80,
) -> dict[str, Any]:
    """Totals this year to ``today`` vs last year to the same day.

    Also returns the two cumulative-distance series the feed hero draws
    (this year to today, last year for the whole year so the dashed line
    shows where last year went next), and per-week totals the feed's week
    headers print, so no client sums a week itself.
    """
    this_year = today.year
    prior_year = this_year - 1
    prior_cut = same_day_last_year(today)

    cur = {"sessions": 0.0, "distance_m": 0.0, "duration_s": 0.0, "elevation_m": 0.0}
    pri = dict(cur)
    for e in entries:
        if e.day.year == this_year and e.day <= today:
            b = cur
        elif e.day.year == prior_year and e.day <= prior_cut:
            b = pri
        else:
            continue
        b["sessions"] += 1
        b["duration_s"] += max(0, e.duration_s or 0)
        b["distance_m"] += e.distance_m or 0.0
        b["elevation_m"] += e.elevation_m or 0.0

    # Weekly totals, newest first, from `weeks_back` weeks ago to this week.
    this_week = week_start(today)
    first_week = this_week - timedelta(weeks=weeks_back - 1)
    weeks: dict[date, list[int]] = {}
    for e in entries:
        if e.day > today:
            continue
        w = week_start(e.day)
        if w < first_week:
            continue
        agg = weeks.setdefault(w, [0, 0])
        agg[0] += 1
        agg[1] += max(0, e.duration_s or 0)
    week_rows = [
        {"week_start": w.isoformat(), "sessions": v[0], "duration_s": v[1]}
        for w, v in sorted(weeks.items(), reverse=True)
    ]
    tw = weeks.get(this_week, [0, 0])

    return {
        "year": this_year,
        "prior_year": prior_year,
        "through": today.isoformat(),
        "prior_through": prior_cut.isoformat(),
        "metrics": [_metric(k, lbl, u, cur[k], pri[k]) for k, lbl, u in _METRICS],
        "cumulative_distance_m": {
            "this_year": _cumulative(entries, this_year, today),
            "last_year": _cumulative(entries, prior_year, date(prior_year, 12, 31)),
        },
        "this_week": {
            "week_start": this_week.isoformat(),
            "sessions": tw[0],
            "duration_s": tw[1],
        },
        "weeks": week_rows,
    }
