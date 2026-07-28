"""PROG-1 program-mode scheme state machines.

prescribe_program_lift → today's fixed prescription (snapped to the rack).
advance_program_lift → post-session progression (pure, returns new state).

Three schemes:
  linear    — 3×5, +5 on success, 3 misses → 10% deload
  greyskull — 5×5 last-set-AMRAP, +5 (double at 10+), 1 miss → deload
  double    — 3×8-12, reps first then +5 at the top of the range
"""
from __future__ import annotations

from myvitals.analytics.strength import (
    prescribe_program_lift, advance_program_lift, PROGRAM_SCHEME_DEFAULTS,
)

PAIRS_5S = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
WRISTS = [1.0, 1.5, 2.0, 3.0]


def _lift(scheme, weight, **over):
    # Mirror a materialised ProgramLiftState (consecutive_fails always
    # present) so the helper matches the real payload shape.
    d = {
        "exercise_id": "x", "scheme": scheme, "current_weight_lb": weight,
        "consecutive_fails": 0, "last_advanced_on": None,
    }
    d.update(PROGRAM_SCHEME_DEFAULTS[scheme])
    d.update(over)
    return d


class TestPrescribe:
    def test_linear_prescription_snaps_to_rack(self):
        # 47 lb has no pair; nearest loadable is 45 (or 45+wrist).
        p = prescribe_program_lift(_lift("linear", 47.0), PAIRS_5S, WRISTS)
        assert p["sets"] == 3 and p["reps_lo"] == 5 and p["reps_hi"] == 5
        assert p["weight_lb"] is not None and p["weight_lb"] <= 47.0 + 0.25
        assert p["amrap_last"] is False
        assert "Linear" in p["note"]

    def test_greyskull_marks_amrap_last_set(self):
        p = prescribe_program_lift(_lift("greyskull", 30.0), PAIRS_5S, WRISTS)
        assert p["amrap_last"] is True
        assert "AMRAP" in p["note"]

    def test_double_prescribes_rep_range(self):
        p = prescribe_program_lift(_lift("double", 20.0), PAIRS_5S, WRISTS)
        assert (p["reps_lo"], p["reps_hi"]) == (8, 12)
        assert p["amrap_last"] is False

    def test_bodyweight_lift_has_no_weight(self):
        p = prescribe_program_lift(
            _lift("linear", None), PAIRS_5S, WRISTS)
        assert p["weight_lb"] is None


class TestLinearAdvance:
    def test_success_adds_increment(self):
        s = advance_program_lift(_lift("linear", 40.0), min_working_reps=5)
        assert s["current_weight_lb"] == 45.0
        assert s["consecutive_fails"] == 0

    def test_miss_starts_fail_streak_no_deload_yet(self):
        s = advance_program_lift(_lift("linear", 40.0), min_working_reps=4)
        assert s["current_weight_lb"] == 40.0  # held
        assert s["consecutive_fails"] == 1

    def test_third_miss_deloads_ten_percent(self):
        s = _lift("linear", 40.0, consecutive_fails=2)
        s = advance_program_lift(s, min_working_reps=3)
        assert s["current_weight_lb"] == 36.0  # 40 * 0.90
        assert s["consecutive_fails"] == 0  # reset after deload

    def test_stamps_advance_date(self):
        s = advance_program_lift(
            _lift("linear", 40.0), min_working_reps=5, on_date="2026-07-28")
        assert s["last_advanced_on"] == "2026-07-28"

    def test_no_sets_logged_holds_everything(self):
        s = advance_program_lift(_lift("linear", 40.0), min_working_reps=None)
        assert s["current_weight_lb"] == 40.0
        assert s["consecutive_fails"] == 0


class TestGreyskullAdvance:
    def test_amrap_clears_floor_adds_increment(self):
        s = advance_program_lift(
            _lift("greyskull", 30.0), min_working_reps=5, amrap_reps=7)
        assert s["current_weight_lb"] == 35.0

    def test_amrap_double_at_ten_plus(self):
        # reps_low=5 → 10+ reps doubles the jump (+10).
        s = advance_program_lift(
            _lift("greyskull", 30.0), min_working_reps=5, amrap_reps=11)
        assert s["current_weight_lb"] == 40.0

    def test_single_miss_deloads_immediately(self):
        s = advance_program_lift(
            _lift("greyskull", 30.0), min_working_reps=3, amrap_reps=3)
        assert s["current_weight_lb"] == 27.0  # 30 * 0.90
        assert s["consecutive_fails"] == 0

    def test_amrap_reps_none_falls_back_to_working(self):
        s = advance_program_lift(
            _lift("greyskull", 30.0), min_working_reps=6, amrap_reps=None)
        assert s["current_weight_lb"] == 35.0


class TestDoubleAdvance:
    def test_top_of_range_adds_weight(self):
        # all sets hit reps_high=12 → +5.
        s = advance_program_lift(_lift("double", 20.0), min_working_reps=12)
        assert s["current_weight_lb"] == 25.0

    def test_in_range_holds_weight(self):
        # 10 reps: between 8 and 12 → rep progress, hold weight, no fail.
        s = advance_program_lift(_lift("double", 20.0), min_working_reps=10)
        assert s["current_weight_lb"] == 20.0
        assert s["consecutive_fails"] == 0

    def test_below_floor_is_a_fail(self):
        s = advance_program_lift(_lift("double", 20.0), min_working_reps=6)
        assert s["current_weight_lb"] == 20.0
        assert s["consecutive_fails"] == 1

    def test_three_fails_deloads(self):
        s = _lift("double", 20.0, consecutive_fails=2)
        s = advance_program_lift(s, min_working_reps=5)
        assert s["current_weight_lb"] == 18.0  # 20 * 0.90
        assert s["consecutive_fails"] == 0


class TestPurity:
    def test_input_state_not_mutated(self):
        orig = _lift("linear", 40.0)
        snapshot = dict(orig)
        advance_program_lift(orig, min_working_reps=5, on_date="2026-07-28")
        assert orig == snapshot  # advance returns a copy, never mutates
