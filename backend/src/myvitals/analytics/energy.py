"""Energy cost of a training session.

Until now a lifting session contributed nothing at all to the user's energy
picture: there is no kcal, calorie or MET term anywhere in the strength API or
its generator, and the activities feed synthesised every strength row with
``kcal: null``. An hour under the bar simply did not exist as work.

The obvious fix is the one every nutrition-first app reaches for -- a MET
lookup keyed on activity type, scaled by body weight. myvitals can do better,
because it owns something those apps do not: a continuous per-minute heart
rate series covering exactly the session window. Heart rate is a far better
proxy for the metabolic cost of a set of squats than a table entry that says
"resistance training, vigorous" and cannot tell a warm-up from a top single.

So there are two estimators and a refusal:

``hr``
    Keytel et al. (2005), the regression fitted on heart rate, body mass, age
    and sex. Used whenever a real average heart rate covers the session and
    the profile carries the three inputs it needs.
``met``
    The compendium fallback, for a session with no heart-rate series at all.
    Needs body weight but not age or sex.
``none``
    Not enough profile data to estimate honestly. This is a real outcome, not
    a failure path: inventing a 70 kg thirty-year-old to keep a number on the
    screen produces a figure that looks measured and is not, which is worse
    than an empty cell. SparkyFitness's calorie service does exactly that,
    and flags in its own comments that the result is "not based on a precise
    scientific model".

Whichever produced the number travels with it as ``kcal_method`` so the UI can
say so. An estimate presented as a fact is the failure this module exists to
avoid.

Two honest limitations, both worth knowing before quoting the figure:

* Every number here is **gross** expenditure over the session window, not
  expenditure above resting. The resting metabolic cost of simply being alive
  for that hour is included, as it is in most consumer fitness apps, so these
  figures are not directly comparable to a strict "calories burned by the
  exercise" definition.
* Keytel is fitted on continuous submaximal exercise. A strength session is
  intermittent -- a hard set, then two minutes of standing around -- and its
  average heart rate sits well above rest throughout, so the regression tends
  to read high for lifting relative to steady cardio at the same mean heart
  rate. No correction factor is applied, because any coefficient chosen here
  would be invented rather than measured, and an invented adjustment is the
  same failure as an invented body weight.
"""

from __future__ import annotations

from typing import Any, Literal

KcalMethod = Literal["hr", "met", "none"]

# ACSM Compendium of Physical Activities, rounded to the nearest half-MET.
# Only consulted when there is no heart-rate series to integrate.
MET_BY_FOCUS: dict[str, float] = {
    "yoga": 2.5,        # hatha
    "cardio": 6.0,      # moderate-to-vigorous continuous effort
    "mobility": 2.3,
}
DEFAULT_STRENGTH_MET = 5.0  # resistance training, vigorous effort

_KCAL_PER_KJ = 4.184


def keytel_kcal_per_min(
    hr_bpm: float, weight_kg: float, age: int, sex: str,
) -> float | None:
    """Keytel et al. (2005) energy expenditure from heart rate.

    Published as kJ/min; divided here to kcal/min. The regression is fitted
    on submaximal steady-state exercise, so it is least reliable at the
    extremes -- it can return a negative number at a resting heart rate,
    which is clamped to zero rather than allowed to subtract from a session.

    Returns None when sex is neither male nor female. The two published
    equations have different coefficients and there is no defensible way to
    pick one for a user who has said "other" or left it blank; a silent
    coin-flip between them would be a fabricated number wearing a citation.
    """
    s = (sex or "").strip().lower()
    if s == "male":
        kj_per_min = (
            -55.0969 + 0.6309 * hr_bpm + 0.1988 * weight_kg + 0.2017 * age
        )
    elif s == "female":
        kj_per_min = (
            -20.4022 + 0.4472 * hr_bpm - 0.1263 * weight_kg + 0.0740 * age
        )
    else:
        return None
    return max(0.0, kj_per_min / _KCAL_PER_KJ)


def met_kcal_per_min(met: float, weight_kg: float) -> float:
    """Standard compendium arithmetic: 1 MET = 3.5 ml O2 / kg / min."""
    return met * 3.5 * weight_kg / 200.0


def met_for_focus(split_focus: str | None) -> float:
    return MET_BY_FOCUS.get((split_focus or "").lower(), DEFAULT_STRENGTH_MET)


def estimate_session_kcal(
    *,
    net_minutes: float,
    avg_hr: float | None,
    weight_kg: float | None,
    age: int | None,
    sex: str | None,
    split_focus: str | None = None,
) -> tuple[float | None, KcalMethod]:
    """Best available estimate for one session, and how it was reached.

    Order is deliberate: heart rate first because it reflects what the
    session actually cost, MET second because it reflects only what the
    session nominally was, and nothing at all rather than a default body.
    """
    if net_minutes <= 0:
        return None, "none"

    if avg_hr is not None and weight_kg and age is not None and sex:
        per_min = keytel_kcal_per_min(avg_hr, weight_kg, age, sex)
        if per_min is not None:
            return round(per_min * net_minutes, 1), "hr"

    if weight_kg:
        per_min = met_kcal_per_min(met_for_focus(split_focus), weight_kg)
        return round(per_min * net_minutes, 1), "met"

    return None, "none"


def net_duration_s(
    started_at: Any, completed_at: Any, total_paused_s: int | None,
) -> int | None:
    """Elapsed minus accumulated pause, floored at zero.

    The single definition of "how long was that session". Both clients used
    to compute gross ``completed_at - started_at`` when synthesising the
    activities-feed row, while analytics/advanced.py:_strength_training_stress
    correctly subtracted the paused time -- so the feed and the training-load
    model already disagreed about the same workout, and a session left open
    on the rack during a phone call read as a multi-hour effort in one place
    and a realistic one in the other.
    """
    if not started_at or not completed_at:
        return None
    elapsed = (completed_at - started_at).total_seconds()
    return max(0, int(elapsed - float(total_paused_s or 0)))
