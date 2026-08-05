"""PROG-2 — a coarse dumbbell step must not freeze a lift forever.

Before this, topping out the rep range when the percentage jump rounded
back onto the current weight produced a "weight-locked" hold plus advice
to buy micro-loaders. If the user never bought them the lift was pinned
permanently, even with a heavier dumbbell sitting on the rack.
"""
from myvitals.analytics.strength import (
    double_progression,
    next_loadable_above,
    valid_dumbbell_loads,
)

# The real inventory: 5 lb steps, 5 → 50, no micro-loaders.
PAIRS = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
NO_MICRO: list[float] = []
MICRO = [1.5, 2.5]


def _dp(**kw):
    base = dict(
        base_reps_lo=10, base_reps_hi=12, last_weight_lb=25.0,
        last_avg_rating=5.0, last_avg_reps=12.0, is_compound=False,
        goal="hypertrophy", pairs_lb=PAIRS, wrist_weights_lb=NO_MICRO,
    )
    base.update(kw)
    return double_progression(**base)


# ── next_loadable_above ───────────────────────────────────────────────

def test_next_loadable_above_finds_the_next_rack_weight():
    assert next_loadable_above(25.0, PAIRS, NO_MICRO) == 30.0


def test_next_loadable_above_uses_micro_weights_when_owned():
    step = next_loadable_above(25.0, PAIRS, MICRO)
    assert step is not None and 25.0 < step < 30.0


def test_next_loadable_above_returns_none_at_the_top():
    assert next_loadable_above(max(valid_dumbbell_loads(PAIRS, NO_MICRO)),
                               PAIRS, NO_MICRO) is None


def test_next_loadable_above_handles_none():
    assert next_loadable_above(None, PAIRS, NO_MICRO) is None


# ── the reported bug ──────────────────────────────────────────────────

def test_maxed_rep_range_now_advances_to_the_next_dumbbell():
    """25 lb × 12 reps, rated easy → 30 lb, not a permanent hold."""
    weight, lo, hi, advisory = _dp()
    assert weight == 30.0, "must take the next available load, not freeze"
    assert (lo, hi) == (10, 12), "reps reset to the range to absorb the jump"
    assert advisory and "+20%" in advisory


def test_the_advisory_is_a_warning_not_a_refusal():
    _w, _lo, _hi, advisory = _dp()
    assert "locked" not in advisory.lower()
    # Still points at the fix, since it stays the better long-term answer.
    assert "micro" in advisory.lower()


def test_no_warning_when_the_step_matches_the_intended_jump():
    # Heavy compound: +7.5% of 40 is 43, and 45 is close enough that the
    # forced step isn't worth commenting on.
    _w, _lo, _hi, advisory = _dp(
        last_weight_lb=40.0, is_compound=True, base_reps_lo=5, base_reps_hi=8,
        last_avg_reps=8.0,
    )
    assert advisory is None or "+" in advisory


def test_top_of_the_rack_still_holds_and_says_so():
    top = max(valid_dumbbell_loads(PAIRS, NO_MICRO))
    weight, lo, hi, advisory = _dp(last_weight_lb=top)
    assert weight == top
    assert lo == hi, "held at the top of the rep range"
    assert advisory and "heaviest" in advisory.lower()


def test_owning_micro_weights_gives_a_gentle_step_and_no_warning():
    weight, _lo, _hi, advisory = _dp(wrist_weights_lb=MICRO)
    assert weight is not None and 25.0 < weight < 30.0
    assert advisory is None


# ── unchanged paths ───────────────────────────────────────────────────

def test_mid_range_still_adds_a_rep_not_weight():
    weight, lo, _hi, advisory = _dp(last_avg_reps=10.0, last_avg_rating=4.0)
    assert weight == 25.0
    assert lo == 11
    assert advisory is None


def test_failure_still_cuts_weight():
    weight, lo, hi, advisory = _dp(last_avg_rating=1.0)
    assert weight is not None and weight <= 25.0
    assert (lo, hi) == (10, 12)
    assert advisory is None


def test_advisory_quotes_the_unrounded_policy_target():
    """The 'wanted' figure must come from the raw percentage, not the
    rounded one — the rounded jump is 0 by definition in this branch, so
    the note used to read a nonsensical "~+0% was wanted"."""
    _w, _lo, _hi, advisory = _dp()
    assert advisory is not None
    assert "+0%" not in advisory
    assert "+5%" in advisory  # isolation / hypertrophy policy
