"""Period-over-period comparison of daily summary metrics (CMP-1).

Before this module, the same comparison was hand-rolled in five places:
``_wow_deltas`` in ``integrations/claude.py`` (hardcoded to 7d-vs-prior-7d
and reachable only from AI payload builders), plus four client-side
derivations across Vue and Compose. They disagreed on three things that
matter:

* **Which direction is good.** Each client decided locally whether a
  falling number should render green. Resting HR falling is an
  improvement; HRV falling is not. Getting that wrong inverts the meaning
  of the colour, which is worse than showing no colour at all.
* **What counts as enough data.** A "week" in which the watch was worn
  twice is not comparable to a week it was worn seven times, but a plain
  mean hides that completely.
* **Rounding.** Steps rounded to one decimal, HRV rounded to zero.

All three now have exactly one answer, here.

Deliberately *not* included: any claim of statistical significance. With
n≈7 per window almost nothing here would survive a real test, so this
module reports coverage (``n_current`` / ``n_baseline`` / ``sufficient``)
and leaves interpretation to the reader rather than dressing noise up as
a finding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

Better = Literal["higher", "lower", "context"]
Direction = Literal["improved", "worse", "flat", "neutral"]


@dataclass(frozen=True)
class MetricSpec:
    """How one metric is named, rounded, and read.

    ``better`` is the field that used to live in client code. It answers
    "if this number went up, is that good news?" — and it is a property of
    the metric, not of the surface rendering it.

    ``better="context"`` means the question has no universal answer.
    Bodyweight is the case: whether +2 lb is good depends entirely on
    whether the user is cutting or bulking, and the app does not get to
    assume. Those metrics report the delta and render neutral rather than
    picking a colour and being wrong for half of all users.
    """

    key: str
    label: str
    unit: str
    better: Better
    precision: int = 1


# Ordered — clients render in this order so web and phone agree without
# either of them sorting.
COMPARE_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("rhr", "Resting HR", "bpm", "lower"),
    MetricSpec("hrv", "HRV", "ms", "higher"),
    MetricSpec("recovery", "Recovery", "", "higher"),
    MetricSpec("readiness", "Readiness", "", "higher"),
    MetricSpec("sleep_h", "Sleep", "h", "higher", precision=2),
    MetricSpec("sleep_score", "Sleep score", "", "higher"),
    MetricSpec("sleep_consistency", "Sleep consistency", "", "higher"),
    MetricSpec("sleep_debt_h", "Sleep debt", "h", "lower", precision=2),
    MetricSpec("steps", "Steps", "", "higher", precision=0),
    MetricSpec("tsb", "Form (TSB)", "", "higher"),
    MetricSpec("ctl", "Fitness (CTL)", "", "higher"),
    MetricSpec("atl", "Fatigue (ATL)", "", "lower"),
    MetricSpec("weight_kg", "Weight", "kg", "context", precision=2),
    MetricSpec("body_fat_pct", "Body fat", "%", "context"),
)

METRICS_BY_KEY = {m.key: m for m in COMPARE_METRICS}


def baseline_window(
    since: date, until: date, vs: str,
) -> tuple[date, date]:
    """The window to compare against, given the current one.

    ``previous`` is the immediately preceding block of the same length,
    which is what "vs last week" means to a user.

    ``last_year`` is the same calendar window shifted back 364 days —
    *not* 365, and not the same calendar date. 364 is 52 whole weeks, so
    a Monday-to-Sunday window maps onto a Monday-to-Sunday window. Using
    365 shifts the weekday by one and quietly compares five weekdays
    against four weekdays plus a Saturday, which for step counts and
    training load is a systematic bias rather than noise.
    """
    span = (until - since).days
    if vs == "last_year":
        shift = timedelta(days=364)
        return since - shift, until - shift
    return since - timedelta(days=span + 1), since - timedelta(days=1)


def _mean(rows: list[dict[str, Any]], key: str) -> tuple[float | None, int]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


def _direction(delta: float, spec: MetricSpec) -> Direction:
    """Read a delta against the metric's own sense of "good".

    Flatness is judged at the metric's own display precision rather than
    against an invented percentage threshold: if the change would not be
    visible in the number as rendered, calling it a change is noise. At
    precision 0 (steps) that means a delta under half a step, which is
    effectively never — correct, since any real step delta is visible.
    """
    if round(delta, spec.precision) == 0:
        return "flat"
    if spec.better == "context":
        return "neutral"
    improved = delta > 0 if spec.better == "higher" else delta < 0
    return "improved" if improved else "worse"


def compare_windows(
    current_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    *,
    window_days: int,
    keys: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compare two lists of daily-summary dicts, metric by metric.

    Rows are the shape ``_daily_rows`` produces in ``claude.py``: a
    ``date`` string plus nullable metric keys. Missing days are simply
    absent rather than zero-filled — a day the watch was not worn has no
    resting HR, and averaging a zero in would drag the mean down and
    invent an improvement that did not happen.
    """
    specs = (
        COMPARE_METRICS
        if keys is None
        else tuple(METRICS_BY_KEY[k] for k in keys if k in METRICS_BY_KEY)
    )

    # Half the window is the coverage bar. It is a judgement call, but a
    # defensible one: below half, the mean is describing a different
    # sample of days than the window it claims to summarise.
    min_days = max(1, math.ceil(window_days / 2))

    out: dict[str, dict[str, Any]] = {}
    for spec in specs:
        cur, n_cur = _mean(current_rows, spec.key)
        base, n_base = _mean(baseline_rows, spec.key)
        if cur is None or base is None:
            # Nothing to compare. Emit the row anyway with nulls so the
            # client can render "—" in a stable position rather than the
            # table reflowing as metrics appear and vanish.
            out[spec.key] = {
                "label": spec.label,
                "unit": spec.unit,
                "better": spec.better,
                "current": round(cur, spec.precision) if cur is not None else None,
                "baseline": round(base, spec.precision) if base is not None else None,
                "delta": None,
                "pct_change": None,
                "direction": None,
                "n_current": n_cur,
                "n_baseline": n_base,
                "sufficient": False,
            }
            continue

        delta = cur - base
        pct = (delta / base * 100.0) if base else None
        out[spec.key] = {
            "label": spec.label,
            "unit": spec.unit,
            "better": spec.better,
            "current": round(cur, spec.precision),
            "baseline": round(base, spec.precision),
            "delta": round(delta, spec.precision),
            "pct_change": round(pct, 1) if pct is not None else None,
            "direction": _direction(delta, spec),
            "n_current": n_cur,
            "n_baseline": n_base,
            "sufficient": n_cur >= min_days and n_base >= min_days,
        }
    return out
