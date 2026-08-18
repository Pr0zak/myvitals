"""Session energy and net duration — TD-4.

Two defects motivated this module, and both are pinned here.

A lifting session contributed nothing at all to the user's energy picture:
there was no kcal, calorie or MET term anywhere in the strength API or its
generator, and the activities feed synthesised every strength row with
kcal: null. An hour of work simply did not exist.

Separately, both clients derived session duration as gross
``completed_at - started_at`` while analytics/advanced.py's training-stress
model subtracted the accumulated pause -- so the feed and the CTL/ATL model
already reported different lengths for the same workout.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from myvitals.analytics import energy

START = datetime(2026, 8, 1, 17, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Net duration
# --------------------------------------------------------------------------

def test_net_duration_subtracts_accumulated_pause():
    """A session left open on the rack is not a three-hour effort."""
    net = energy.net_duration_s(START, START + timedelta(hours=3), 7200)
    assert net == 3600


def test_net_duration_never_goes_negative():
    """Clock skew or a bad pause total must not produce a negative session."""
    assert energy.net_duration_s(START, START + timedelta(minutes=10), 9999) == 0


def test_net_duration_is_none_without_both_endpoints():
    assert energy.net_duration_s(None, START, 0) is None
    assert energy.net_duration_s(START, None, 0) is None


def test_net_duration_matches_the_training_stress_model():
    """The number the feed shows and the number CTL/ATL consumes are one.

    analytics/advanced.py:_strength_training_stress computes
    `elapsed - total_paused_s` inline. This is the same arithmetic, and the
    point of extracting it is that there is now only one copy.
    """
    started, completed, paused = START, START + timedelta(minutes=75), 600
    inline = (completed - started).total_seconds() - paused
    assert energy.net_duration_s(started, completed, paused) == int(inline)


# --------------------------------------------------------------------------
# Refusing to fabricate
# --------------------------------------------------------------------------

def test_no_bodyweight_means_no_estimate():
    """The failure mode this module was written to avoid.

    SparkyFitness's calorie service substitutes a default body when the
    profile is thin, which yields a number that looks measured and is not.
    An empty cell is more honest, and `kcal_method` says which happened.
    """
    kcal, method = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=130, weight_kg=None, age=39, sex="male",
    )
    assert kcal is None
    assert method == "none"


def test_zero_length_session_has_no_energy_cost():
    kcal, method = energy.estimate_session_kcal(
        net_minutes=0, avg_hr=130, weight_kg=84, age=39, sex="male",
    )
    assert kcal is None
    assert method == "none"


def test_unknown_sex_falls_back_to_met_rather_than_guessing():
    """Keytel publishes two equations with different coefficients.

    There is no defensible way to pick one for a user who left sex blank or
    answered "other", so the heart-rate path declines and the weight-only
    MET path takes over — a coarser number, honestly labelled.
    """
    kcal, method = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=130, weight_kg=84, age=39, sex="other",
    )
    assert method == "met"
    assert kcal is not None


# --------------------------------------------------------------------------
# The estimators
# --------------------------------------------------------------------------

def test_heart_rate_is_preferred_over_the_met_table():
    """The whole reason myvitals can beat a nutrition-first app here.

    Those apps guess from a MET lookup because they have no heart-rate
    stream. This app owns a per-minute series covering exactly the session
    window, and heart rate distinguishes a hard session from an easy one at
    the same nominal activity.
    """
    hard, hard_method = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=150, weight_kg=84, age=39, sex="male",
    )
    easy, easy_method = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=95, weight_kg=84, age=39, sex="male",
    )
    assert hard_method == easy_method == "hr"
    assert hard > easy


def test_met_estimate_scales_with_bodyweight_and_time():
    light, _ = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=None, weight_kg=60, age=39, sex="male",
    )
    heavy, _ = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=None, weight_kg=90, age=39, sex="male",
    )
    half, _ = energy.estimate_session_kcal(
        net_minutes=30, avg_hr=None, weight_kg=90, age=39, sex="male",
    )
    assert heavy > light
    # abs tolerance, not relative: the result is rounded to one decimal, so
    # halving a rounded number lands a rounding step away from the exact half.
    assert half == pytest.approx(heavy / 2, abs=0.1)


def test_yoga_costs_less_than_lifting_at_the_same_duration():
    """Yoga days are generated by the same planner and stored in the same
    table, but they are not the same stimulus — the same distinction
    _strength_training_stress already makes for training load."""
    yoga, _ = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=None, weight_kg=84, age=39, sex="male",
        split_focus="yoga",
    )
    lift, _ = energy.estimate_session_kcal(
        net_minutes=60, avg_hr=None, weight_kg=84, age=39, sex="male",
        split_focus="push",
    )
    assert yoga < lift


def test_keytel_is_clamped_at_zero():
    """The regression can go negative at a resting heart rate. A session
    must never subtract energy from the day."""
    per_min = energy.keytel_kcal_per_min(45, 84, 39, "male")
    assert per_min == 0.0


@pytest.mark.parametrize("sex", ["male", "female"])
def test_keytel_returns_a_plausible_rate_for_both_equations(sex):
    per_min = energy.keytel_kcal_per_min(140, 75, 40, sex)
    assert per_min is not None
    # Sanity band rather than a fixed value: the point is that each equation
    # is wired to the right coefficients, not that the paper is re-derived.
    assert 5 < per_min < 25


def test_keytel_declines_an_unknown_sex():
    assert energy.keytel_kcal_per_min(140, 75, 40, "other") is None
    assert energy.keytel_kcal_per_min(140, 75, 40, "") is None
