"""Stat blocks for the metric detail screens (UI-4).

The Steps, Heart rate, Sleep and Weight detail screens each grew their own
arithmetic on BOTH clients: the phone summed steps and counted goal days in
Compose, bucketed the HR trace into zones and 5-bpm bins, averaged resting
HR per weekday, took min/avg/max of the nights, and judged the colour of a
weight change with a private copy of the GOAL-STATE noise band; the web did
its own versions of most of that. Four formulas per number is how two
surfaces end up showing different values for the same day.

Everything a detail screen prints as a figure is computed here, once, from
the same rows the charts draw, and the clients render it verbatim. The
functions are pure (rows in, dict out) so they can be tested without a
database; the endpoints in `api/summary.py` and `api/query.py` do the
fetching.

Rules carried over from the rest of the app:

* Null is not zero. A day with no reading is excluded from averages and
  from the goal-day denominator, and a stat with no inputs is None — never 0.
* Calendar days are LOCAL days (the rows are already local-day rows).
* Zone boundaries come from `analytics/cardio.py`, the single definition.
* Weight tone follows GOAL-STATE: amber for drifting away from the goal,
  never rose; no goal means no verdict.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Sequence

# Sun-first, matching the order both clients have always drawn.
WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

#: A gap longer than this between two HR points is missing data, not time
#: spent in the earlier point's zone. The phone's old client-side version used
#: the same five minutes, so the numbers do not jump on upgrade.
HR_GAP_CAP_S = 5 * 60

#: Histogram bin width. Five beats keeps a resting cluster readable without
#: turning a broad day into noise.
HR_BIN_BPM = 5


def _dow_index(d: date) -> int:
    """0 = Sunday … 6 = Saturday."""
    return (d.weekday() + 1) % 7


def _as_date(v: Any) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])


def weekday_means(pairs: Iterable[tuple[date, float | None]], digits: int = 0) -> list[dict[str, Any]]:
    """Mean per weekday. A weekday with no reading is `mean: None`, not 0 —
    rendering it as a zero bar made a gap in the data look like a rest day."""
    sums = [0.0] * 7
    counts = [0] * 7
    for d, v in pairs:
        if v is None:
            continue
        i = _dow_index(d)
        sums[i] += float(v)
        counts[i] += 1
    out = []
    for i, name in enumerate(WEEKDAYS):
        mean = round(sums[i] / counts[i], digits) if counts[i] else None
        if mean is not None and digits == 0:
            mean = int(mean)
        out.append({"dow": name, "mean": mean, "n": counts[i]})
    return out


def _basic(values: Sequence[float], digits: int = 1) -> dict[str, Any]:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {
        "avg": round(sum(values) / len(values), digits),
        "min": round(min(values), digits),
        "max": round(max(values), digits),
    }


def steps_stats(rows: Sequence[Any], window_days: int) -> dict[str, Any]:
    """Steps over a window of daily-summary rows.

    `rows` need `.date`, `.steps_total` and `.steps_goal` (the day's OWN
    target, weekday schedule included — UX-D10). `goal_days` is out of
    `days_with_data`: a day the watch was off is not a missed goal.
    """
    with_data = [r for r in rows if r.steps_total is not None]
    vals = [int(r.steps_total) for r in with_data]
    goal_days = sum(
        1 for r in with_data
        if r.steps_goal is not None and r.steps_total >= r.steps_goal
    )
    # Trailing seven-day mean for each day in the window, over the days that
    # HAVE a reading. None when the whole trailing week is empty.
    ordered = sorted(rows, key=lambda r: _as_date(r.date))
    rolling = []
    for i, r in enumerate(ordered):
        d = _as_date(r.date)
        wk = [
            x.steps_total for x in ordered[max(0, i - 6): i + 1]
            if x.steps_total is not None and (d - _as_date(x.date)).days < 7
        ]
        rolling.append({
            "date": d.isoformat(),
            "value": round(sum(wk) / len(wk)) if wk else None,
        })
    return {
        "avg": round(sum(vals) / len(vals)) if vals else None,
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "total": sum(vals) if vals else None,
        "days_with_data": len(vals),
        "goal_days": goal_days,
        "window_days": window_days,
        "weekday_means": weekday_means((_as_date(r.date), r.steps_total) for r in rows),
        "rolling_7d": rolling,
    }


def resting_hr_stats(rows: Sequence[Any]) -> dict[str, Any]:
    """Resting HR over a window of daily-summary rows."""
    pairs = [(_as_date(r.date), r.resting_hr) for r in rows]
    vals = [float(v) for _, v in pairs if v is not None]
    latest = next((float(v) for _, v in sorted(pairs, reverse=True) if v is not None), None)
    out = _basic(vals, digits=1)
    avg = out["avg"]
    out.update({
        "latest": round(latest, 1) if latest is not None else None,
        # The latest reading against the window's own mean, so the hero can
        # say "+3 vs 30d avg" without a client subtracting.
        "latest_vs_avg": (round(latest - avg, 1)
                          if latest is not None and avg is not None else None),
        "days_with_data": len(vals),
        "weekday_means": weekday_means(pairs, digits=1),
    })
    return out


def sleep_stats(nights: Sequence[Any]) -> dict[str, Any]:
    """Nightly sleep over a window of SleepNight-shaped objects.

    Naps are excluded from every figure: a 45-minute nap averaged in with
    eight-hour nights dragged the headline down and made "Min" the nap.
    """
    real = [n for n in nights if getattr(n, "kind", "sleep") != "nap"]
    vals = [int(n.total_s) for n in real]
    return {
        "avg_s": round(sum(vals) / len(vals)) if vals else None,
        "min_s": min(vals) if vals else None,
        "max_s": max(vals) if vals else None,
        "nights": len(real),
        "naps": len(nights) - len(real),
    }


# ── Heart rate (one day) ─────────────────────────────────────────────────

def hr_zone_stats(
    points: Sequence[tuple[datetime, float]],
    max_hr: float,
    bucket_seconds: int | None,
) -> dict[str, Any]:
    """Time-in-zone and a minutes-per-band histogram for an HR trace.

    Zone boundaries are `cardio.zone_bounds` — the one definition the
    activity zones already use. Each point is credited with the time until
    the next point, capped by HR_GAP_CAP_S (a watch taken off to charge is
    not five hours in Z1).

    The histogram counts TIME, not rows: when the series is bucketed each
    point is a fixed `bucket_seconds` slice, which is what "minutes in this
    band" means. For a raw series the same gap-credit as the zones is used.
    """
    from .cardio import zone_bounds, zone_for

    bounds = zone_bounds(max_hr)
    secs = {b["zone"]: 0 for b in bounds}
    bins: dict[int, float] = {}
    pts = sorted(points, key=lambda p: p[0])
    for i, (t, bpm) in enumerate(pts):
        if bpm is None:
            continue
        if i + 1 < len(pts):
            gap = (pts[i + 1][0] - t).total_seconds()
            credit = gap if 0 < gap <= HR_GAP_CAP_S else 0
        else:
            credit = 0
        if credit:
            secs[zone_for(bpm, max_hr)] += int(credit)
        b = int(bpm // HR_BIN_BPM) * HR_BIN_BPM
        if bucket_seconds:
            bins[b] = bins.get(b, 0.0) + bucket_seconds / 60.0
        elif credit:
            bins[b] = bins.get(b, 0.0) + credit / 60.0

    total = sum(secs.values())
    tiz = []
    for b in bounds:
        s = secs[b["zone"]]
        tiz.append({
            **b,
            "seconds": s,
            # Null, not 0, when there is no time at all to divide.
            "pct": round(s / total * 100, 1) if total else None,
        })
    histogram = []
    if bins:
        lo, hi = min(bins), max(bins)
        for b in range(lo, hi + HR_BIN_BPM, HR_BIN_BPM):
            histogram.append({"lo": b, "hi": b + HR_BIN_BPM,
                              "minutes": round(bins.get(b, 0.0), 1)})
    return {"time_in_zone": tiz, "tracked_s": total, "histogram": histogram}


# ── Weight ───────────────────────────────────────────────────────────────

def weight_tone(delta_kg: float | None, current_kg: float | None,
                goal_kg: float | None) -> str:
    """positive | caution | neutral for a change over a window.

    Moved here from the phone's `weightDeltaTone` so the colour of a weight
    change is decided in one place with GOAL-STATE's noise band. A body-weight
    delta has no intrinsic good direction (`compare.py` calls it "context");
    only the user's goal can settle it, and with no goal there is no verdict.
    Caution renders amber, never rose.
    """
    from ..api.ai import WEIGHT_NOISE_BAND_KG

    if delta_kg is None or current_kg is None or goal_kg is None:
        return "neutral"
    if abs(delta_kg) < WEIGHT_NOISE_BAND_KG:
        return "neutral"
    gap = goal_kg - current_kg
    # Sitting on the target: there is nowhere good left to move.
    if abs(gap) < WEIGHT_NOISE_BAND_KG:
        return "neutral"
    toward = delta_kg < 0 if gap < 0 else delta_kg > 0
    return "positive" if toward else "caution"


def _recomp(points: Sequence[tuple[datetime, float, float | None]]) -> dict[str, Any] | None:
    """Fat vs lean direction over the last 30 days of readings that carry a
    body-fat figure. Moved off the web, which painted "Fat gain" rose — the
    crisis colour — for an ordinary month. Tones are GOAL-STATE's: caution is
    amber and the worst this can say."""
    with_bf = [(t, w, bf) for t, w, bf in points if bf is not None]
    if not with_bf:
        return None
    cutoff = with_bf[-1][0].timestamp() - 30 * 86400
    recent = [p for p in with_bf if p[0].timestamp() >= cutoff]
    if len(recent) < 5:
        return None
    (_, w0, bf0), (_, w1, bf1) = recent[0], recent[-1]
    fat_d = w1 * bf1 / 100 - w0 * bf0 / 100
    lean_d = (w1 - w1 * bf1 / 100) - (w0 - w0 * bf0 / 100)
    if fat_d < -0.3 and lean_d > -0.2:
        label, tone = "Body recomp", "positive"
    elif fat_d < 0 and lean_d < 0:
        label, tone = "Cutting", "neutral"
    elif fat_d > 0 and lean_d > 0:
        label, tone = "Bulking", "neutral"
    elif fat_d > 0.3:
        label, tone = "Fat gain", "caution"
    else:
        label, tone = "Stable", "neutral"
    return {"label": label, "tone": tone,
            "fat_delta_kg": round(fat_d, 2), "lean_delta_kg": round(lean_d, 2)}


def _delta_since(pts: Sequence[tuple[datetime, float]], days: int,
                 goal_kg: float | None) -> dict[str, Any]:
    """Latest minus the first reading within `days` of the latest one."""
    latest_t, latest = pts[-1]
    cutoff = latest_t.timestamp() - days * 86400
    base = next((w for t, w in pts if t.timestamp() >= cutoff), None)
    if base is None or len(pts) < 2:
        return {"delta_kg": None, "tone": "neutral"}
    d = round(latest - base, 2)
    return {"delta_kg": d, "tone": weight_tone(d, latest, goal_kg)}


def weight_stats(
    points: Sequence[tuple[datetime, float]], goal_kg: float | None,
    body_fat: Sequence[tuple[datetime, float, float | None]] | None = None,
) -> dict[str, Any]:
    """Window stats + the trend line for a weight series, all in KILOGRAMS.

    Clients convert to the user's unit for display (Units / units.ts) — the
    one thing they do to these numbers. The trend is an ordinary least-squares
    fit against TIME, so its ends sit at the first and last reading's
    timestamps rather than at list indices (evenly spacing readings is what
    made 7d, 30d and 90d look like the same picture).
    """
    pts = sorted(((t, float(w)) for t, w in points if w is not None), key=lambda p: p[0])
    if not pts:
        return {"count": 0, "rolling_7d": [], "recomp": None,
                "delta_7d": {"delta_kg": None, "tone": "neutral"},
                "delta_30d": {"delta_kg": None, "tone": "neutral"},
                "first_kg": None, "latest_kg": None, "delta_kg": None,
                "min_kg": None, "max_kg": None, "avg_kg": None,
                "goal_kg": goal_kg, "goal_gap_kg": None, "tone": "neutral",
                "trend": None}
    ws = [w for _, w in pts]
    first, latest = ws[0], ws[-1]
    delta = round(latest - first, 2) if len(ws) >= 2 else None
    trend = None
    if len(pts) >= 2:
        t0 = pts[0][0].timestamp()
        xs = [(t.timestamp() - t0) / 86400.0 for t, _ in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ws) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ws, strict=True)) / sxx
            a = my - slope * mx
            trend = {
                "start_time": pts[0][0].isoformat(), "start_kg": round(a, 2),
                "end_time": pts[-1][0].isoformat(), "end_kg": round(a + slope * xs[-1], 2),
                "per_week_kg": round(slope * 7, 2),
            }
    # Trailing seven-day mean at each reading, by TIME not by count.
    rolling = []
    lo = 0
    for i, (t, _w) in enumerate(pts):
        while (t - pts[lo][0]).total_seconds() > 7 * 86400:
            lo += 1
        win = [w for _, w in pts[lo:i + 1]]
        rolling.append({"time": t.isoformat(), "kg": round(sum(win) / len(win), 2)})
    return {
        "count": len(ws),
        "rolling_7d": rolling,
        "delta_7d": _delta_since(pts, 7, goal_kg),
        "delta_30d": _delta_since(pts, 30, goal_kg),
        "recomp": _recomp(sorted(body_fat, key=lambda p: p[0])) if body_fat else None,
        "first_kg": round(first, 2),
        "latest_kg": round(latest, 2),
        "delta_kg": delta,
        "min_kg": round(min(ws), 2),
        "max_kg": round(max(ws), 2),
        "avg_kg": round(sum(ws) / len(ws), 2),
        "goal_kg": goal_kg,
        # Signed latest - goal: positive = above the goal.
        "goal_gap_kg": round(latest - goal_kg, 2) if goal_kg is not None else None,
        "tone": weight_tone(delta, latest, goal_kg),
        "trend": trend,
    }
