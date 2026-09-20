"""Goal projection — where a trend is heading, and when to refuse to say (GOAL-1).

The hard part of this module is not the regression. It is deciding when
*not* to answer.

A projection is a claim about the future made from a handful of noisy
daily measurements. "You'll hit 175 lb on November 3rd" is a very
specific-sounding sentence that a linear fit over three weeks of a body
weight that swings two pounds on water alone cannot support. So every
path here can return ``is_fallback=True`` with a reason, and the callers
render that reason instead of a date.

Specifically it declines when:

* there are too few points to fit anything,
* the trend is flat — a slope indistinguishable from zero would produce
  an ETA in the thousands of days, or a divide-by-zero,
* the trend runs *away* from the target, where the arithmetic still
  yields a date but it is in the past,
* the fit is poor (low R²), meaning the "trend" is mostly noise,
* the ETA lands beyond a horizon where the extrapolation is meaningless.

Smoothing is a 7-day moving average before fitting, which takes out the
day-of-week cycle in steps and the water-weight sawtooth. Fitting raw
daily values makes the slope swing with whichever day the window happens
to end on.

The R² that gates the "noisy" refusal is scored against the RAW window
points, never the smoothed ones. A trailing average is autocorrelated by
construction, so testing a fit against its own smoother always looks
clean regardless of how noisy the underlying measurements are — that was
a bug (SA-N5), not a design choice. Smoothing stays for the slope, which
is genuinely more stable that way; the goodness-of-fit question ("does
this line actually explain what was measured?") has to be asked of what
was measured.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Literal, Sequence

#: Below this many smoothed points, do not fit at all.
MIN_POINTS = 10

#: A fit explaining less than this fraction of variance is noise wearing
#: a trend's clothes. Re-derived (SA-N5) after the previous 0.30 turned
#: out to have been graded on the smoothed series, which meant it had
#: never actually rejected anything real. Measured against this app's
#: own live weight goal: day-to-day scatter there is ~0.87 kg. Over a
#: full 28-point daily window, a Monte Carlo replay of a genuine 1 lb/
#: week loss at that noise level clears R²=0.30 only ~32% of the time —
#: the old value refused a real trend two times in three, which is the
#: same failure this fix exists to remove, just pointed the other way.
#: R²=0.10 clears that same real trend ~88% of the time while a
#: zero-slope series of pure noise only clears it ~6% of the time (see
#: TestNoiseGate in test_goal_projection.py). Below a full window, or
#: across a gap of several days, no threshold here cleanly separates a
#: real trend from noise — that is what MIN_POINTS is for, not this
#: constant.
MIN_R2 = 0.10

#: Slopes smaller than this (per day, relative to the value's own scale)
#: count as flat.
FLAT_REL_SLOPE = 1e-4

#: Refuse to name a date further out than this. Two years of linear
#: extrapolation from three weeks of data is not a forecast.
MAX_ETA_DAYS = 730

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Projection:
    per_day: float | None
    per_week: float | None
    eta_date: str | None
    eta_days: int | None
    confidence: Confidence | None
    r2: float | None
    n_points: int
    method: str
    is_fallback: bool
    fallback_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fallback(reason: str, n: int = 0, method: str = "none") -> Projection:
    return Projection(
        per_day=None, per_week=None, eta_date=None, eta_days=None,
        confidence=None, r2=None, n_points=n, method=method,
        is_fallback=True, fallback_reason=reason,
    )


def moving_average(
    points: Sequence[tuple[date, float]], window: int = 7,
) -> list[tuple[date, float]]:
    """Trailing moving average over dated points.

    Points are assumed sorted and may be sparse — missing days are simply
    absent rather than interpolated. Averaging over the last ``window``
    *available* points rather than the last ``window`` calendar days keeps
    a gap from silently shrinking the average toward whatever data
    surrounds it.
    """
    out: list[tuple[date, float]] = []
    buf: list[float] = []
    for d, v in points:
        buf.append(v)
        if len(buf) > window:
            buf.pop(0)
        out.append((d, sum(buf) / len(buf)))
    return out


def _ols(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float]:
    """Least-squares fit. Returns (slope, intercept, r2)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, intercept, max(0.0, min(1.0, r2))


def _r2_against(
    xs: Sequence[float], ys: Sequence[float], slope: float, intercept: float,
) -> float:
    """R² of an *already-fitted* line against a set of points.

    Unlike ``_ols``, the line here was not necessarily fit to ``xs``/``ys``
    — that is the point (SA-N5). Callers pass the slope/intercept fit to
    the smoothed series and ``xs``/``ys`` from the raw, unsmoothed window,
    so this measures whether the reported trend actually explains the
    measurements, not the smoother built on top of them.
    """
    my = sum(ys) / len(ys)
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot == 0:
        return 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    return max(0.0, min(1.0, 1.0 - ss_res / ss_tot))


def _confidence(r2: float, n: int) -> Confidence:
    """Confidence from fit quality and sample size, both of which matter.

    A tight fit over 12 points is not the same claim as a tight fit over
    60, and reporting both as "high" would overstate the shorter one.
    """
    if r2 >= 0.7 and n >= 21:
        return "high"
    if r2 >= 0.5 and n >= 14:
        return "medium"
    return "low"


def project(
    points: Sequence[tuple[date, float]],
    *,
    target: float | None,
    today: date,
    window_days: int = 28,
    smoothing: int = 7,
) -> Projection:
    """Fit a trend and, if the data supports it, name a date.

    ``points`` are (date, value) pairs, any order, possibly sparse.
    ``target`` may be None — the slope is still useful on its own.
    """
    if not points:
        return _fallback("No data yet.")

    since = today - timedelta(days=window_days - 1)
    window = sorted((d, v) for d, v in points if since <= d <= today)
    if len(window) < MIN_POINTS:
        return _fallback(
            f"Only {len(window)} days of data in the last {window_days}; "
            f"need {MIN_POINTS} to see a trend.",
            n=len(window),
        )

    smoothed = moving_average(window, smoothing)
    origin = smoothed[0][0]
    xs = [float((d - origin).days) for d, _ in smoothed]
    ys = [v for _, v in smoothed]
    slope, intercept, _ = _ols(xs, ys)

    # Score that line against the RAW window it was smoothed from, not
    # against the smoothed series it was fit to (SA-N5) — a trailing
    # average is autocorrelated by construction, so grading a fit against
    # its own smoother can never come back low.
    raw_xs = [float((d - origin).days) for d, _ in window]
    raw_ys = [v for _, v in window]
    r2 = _r2_against(raw_xs, raw_ys, slope, intercept)

    n = len(smoothed)
    current = ys[-1]
    scale = max(abs(current), 1e-9)

    # Flat: report the (near-zero) rate honestly but refuse a date.
    if abs(slope) / scale < FLAT_REL_SLOPE:
        return Projection(
            per_day=round(slope, 4), per_week=round(slope * 7, 3),
            eta_date=None, eta_days=None,
            confidence="low", r2=round(r2, 3), n_points=n, method="ols",
            is_fallback=True,
            fallback_reason="Holding steady — no trend to project from.",
        )

    if r2 < MIN_R2:
        return Projection(
            per_day=round(slope, 4), per_week=round(slope * 7, 3),
            eta_date=None, eta_days=None,
            confidence="low", r2=round(r2, 3), n_points=n, method="ols",
            is_fallback=True,
            fallback_reason=(
                f"Too much day-to-day variation to project "
                f"(fit explains {r2 * 100:.0f}% of it)."
            ),
        )

    per_week = slope * 7
    base = Projection(
        per_day=round(slope, 4), per_week=round(per_week, 3),
        eta_date=None, eta_days=None,
        confidence=_confidence(r2, n), r2=round(r2, 3), n_points=n,
        method="ols", is_fallback=False, fallback_reason=None,
    )

    if target is None:
        return base

    remaining = target - current
    if abs(remaining) < 1e-9:
        return Projection(
            **{**base.to_dict(), "eta_days": 0, "eta_date": today.isoformat()}
        )

    # Moving away from the target. The arithmetic still returns a number
    # here — a negative one — and reporting it as a date would put the
    # goal in the past.
    if (remaining > 0) != (slope > 0):
        return Projection(
            **{
                **base.to_dict(),
                "is_fallback": True,
                "fallback_reason": "Currently trending away from this target.",
            }
        )

    eta_days = int(round(remaining / slope))
    if eta_days > MAX_ETA_DAYS:
        return Projection(
            **{
                **base.to_dict(),
                "is_fallback": True,
                "fallback_reason": (
                    f"At this rate it is more than "
                    f"{MAX_ETA_DAYS // 365} years out — too far to be meaningful."
                ),
            }
        )

    return Projection(
        **{
            **base.to_dict(),
            "eta_days": eta_days,
            "eta_date": (today + timedelta(days=eta_days)).isoformat(),
        }
    )


def project_deterministic(
    current: float | None, target: float | None, today: date, per_day: float = 1.0,
) -> Projection:
    """For goals that advance at a known rate rather than a fitted one.

    A sober-days streak gains exactly one day per day; a regression over
    it would return slope≈1.0 with r²≈1.0 and dress arithmetic up as a
    forecast. Saying so plainly is both more honest and more accurate —
    the only uncertainty is behavioural, not statistical, and this module
    has no business modelling that.
    """
    if current is None or target is None:
        return _fallback("No target set.", method="deterministic")
    remaining = target - current
    if remaining <= 0:
        return Projection(
            per_day=per_day, per_week=per_day * 7, eta_date=today.isoformat(),
            eta_days=0, confidence="high", r2=None, n_points=1,
            method="deterministic", is_fallback=False, fallback_reason=None,
        )
    eta_days = int(round(remaining / per_day))
    return Projection(
        per_day=per_day, per_week=per_day * 7,
        eta_date=(today + timedelta(days=eta_days)).isoformat(),
        eta_days=eta_days,
        # "High" here means the arithmetic is exact if the streak holds —
        # not that holding it is likely. The client wording carries that.
        confidence="high", r2=None, n_points=1,
        method="deterministic", is_fallback=False, fallback_reason=None,
    )
