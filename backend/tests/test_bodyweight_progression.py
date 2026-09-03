"""A quarter of the prescribed work had a target that never moved — OG2-D-6.

A bodyweight strength exercise never progressed at all. `next_prescription`
gates `double_progression` on a dumbbell being present, and `generate_plan`
then forces the weight to None, so the range came only from `prescribe_slot`
— a pure function of goal, slot role, age and bodyweight that never reads the
log. Same body, same number, every session, forever. `_scale_bw_reps` is a
profile adjustment, not a progression, and the one history-driven rep ladder
in the repo, `adjust_mobility_target`, is wired only into the yoga plan and
the mobility cool-down. On this database that is 74 of 292 slots in completed
workouts and 130 of 780 logged sets.

THE TARGET IS NOT THE EVIDENCE, and this is the finding that shaped the
design. Both loggers prefill the rep field with the previous session's reps,
falling back to `target_reps_low` — so a user tapping through logs exactly
what was prescribed, and the next prefill reads the same number back. Butt
Lift (Bridge) sat at 9 reps against a 9-11 target across four sessions on that
loop; Pilates Criss-Cross at 8 against 8-10 across four. Reps therefore
cannot be the primary signal the way they are in `double_progression`, where
a weight the user chose makes the rep count an independent reading.

The RATING is what escapes the loop, which is why this ladder is built on the
same EASY_THRESHOLD and FAIL_THRESHOLD the weighted policy uses. Reps still
speak when they EXCEED the prescription, because that is a number the prefill
did not supply.

MEASURED BEFORE BUILDING, across this database's 118 bodyweight rep sessions:
69 are mobility and already laddered, leaving 49. Of those, 7 would advance,
1 logged above its prescription, and 0 would cut.

The cut rung ships despite never having fired, and that is deliberately
unlike OG2-B1's declined stall count. That had no consumer at all; this is
half of a policy whose other half ships, and omitting it would leave a ladder
that can only ever tighten. A one-way ratchet on a training target is exactly
the shape that hurts someone returning from injury.

There is no "add a set" rung and no "refuse" rung. Both need a lift sitting at
the rep cap and none is within reach, so each would be a branch that cannot
fire — the fault that got OG2-C1 refused. At the cap the ladder says so in an
advisory instead, the way `double_progression` speaks up at the top of the
dumbbell rack.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import (
    EASY_THRESHOLD,
    FAIL_THRESHOLD,
    bodyweight_progression,
    next_prescription,
    rep_ladder_bounds,
)

BASE = dict(base_reps_lo=9, base_reps_hi=11, is_timed=False,
            session_complete=True)


def _bp(**kw):
    return bodyweight_progression(**{**BASE, **kw})


class TestTheLadderMoves:
    def test_an_easy_session_adds_a_rep(self):
        """Butt Lift (Bridge), 2026-06-10, rated 5.00 — a session that under
        the old code changed nothing at all."""
        lo, hi, reason, why, _ = _bp(avg_rating=5.0, avg_reps=9.0)
        assert (lo, hi) == (10, 12)
        assert reason == "advanced"
        assert "easy" in why

    def test_a_middling_session_holds(self):
        """4.33 is below EASY_THRESHOLD, and the weighted policy holds there
        too. The ladder existing does not mean it should always move."""
        lo, hi, reason, _why, _ = _bp(avg_rating=4.33, avg_reps=9.0)
        assert (lo, hi) == (9, 11)
        assert reason == "rep_ladder"

    def test_a_failed_session_cuts(self):
        lo, hi, reason, why, _ = _bp(avg_rating=1.0, avg_reps=6.0)
        assert (lo, hi) == (8, 10)
        assert reason == "deloaded"
        assert "failed" in why

    def test_beating_the_range_raises_it(self):
        """Flutter Kicks, 2026-08-19: 12 reps against a 9-11 target. The one
        rep reading the prefill did not supply."""
        lo, hi, reason, why, _ = _bp(avg_rating=4.0, avg_reps=12.0)
        assert lo == 12
        assert reason == "advanced"
        assert "more than" in why

    def test_beating_the_range_keeps_its_width(self):
        """12-14, not 12-12. Flattening the range removes the room to grow
        inside it and leaves the rating as the only thing that could ever
        move the target again — the stall this ladder exists to end."""
        lo, hi, _reason, _why, _ = _bp(avg_rating=4.0, avg_reps=12.0)
        assert hi - lo == 2


class TestItKeepsB1sAsymmetry:
    def test_a_short_session_does_not_advance(self):
        lo, hi, reason, why, _ = _bp(
            avg_rating=5.0, avg_reps=9.0, session_complete=False)
        assert (lo, hi) == (9, 11)
        assert reason == "held_incomplete"
        assert "fewer" in why

    def test_a_short_failed_session_still_cuts(self):
        """The asymmetry. Two sets rated Failed are real evidence to ease
        off; refusing to act would leave a target the user could not hit
        standing because they stopped early."""
        lo, _hi, reason, _why, _ = _bp(
            avg_rating=1.0, avg_reps=6.0, session_complete=False)
        assert lo == 8
        assert reason == "deloaded"

    def test_the_cut_branch_sits_above_the_completeness_gate(self):
        src = inspect.getsource(bodyweight_progression)
        assert src.index("avg_rating <= FAIL_THRESHOLD") < src.index(
            "if not session_complete:")

    def test_an_unrated_session_holds(self):
        """OG2-A2's rule, unchanged — and it matters more here, because the
        reps alone are the prefill and say nothing on their own."""
        _lo, _hi, reason, why, _ = _bp(avg_rating=None, avg_reps=9.0)
        assert reason == "held_unrated"
        assert "without a rating" in why


class TestTheCapsAreSharedNotCopied:
    def test_one_table_serves_both_ladders(self):
        """A bodyweight hold capped at 15 SECONDS while a pose was capped at
        90 would be the same exercise obeying two rules."""
        assert rep_ladder_bounds(is_timed=False) == (1, 5, 15)
        assert rep_ladder_bounds(is_timed=True) == (5, 15, 90)
        assert "rep_ladder_bounds" in inspect.getsource(
            algo.adjust_mobility_target)
        assert "rep_ladder_bounds" in inspect.getsource(bodyweight_progression)

    def test_a_timed_hold_steps_in_seconds(self):
        """Plank is is_timed in the catalog and reaches this ladder, so a
        one-rep step would have been a one-second step."""
        lo, _hi, reason, _why, _ = bodyweight_progression(
            base_reps_lo=30, base_reps_hi=30, is_timed=True,
            session_complete=True, avg_rating=5.0, avg_reps=30.0)
        assert lo == 35
        assert reason == "advanced"

    def test_the_floor_holds(self):
        lo, hi, _reason, why, _ = bodyweight_progression(
            base_reps_lo=5, base_reps_hi=5, is_timed=False,
            session_complete=True, avg_rating=1.0, avg_reps=3.0)
        assert (lo, hi) == (5, 5)
        assert "lowest target" in why


class TestTheCapSpeaksRatherThanStalling:
    def test_at_the_cap_it_advises_instead_of_silently_holding(self):
        """No "add a set" rung and no "refuse" rung: both need a lift at the
        cap and none is within reach, so each would be a branch that cannot
        fire. The advisory is `double_progression`'s own answer at the top
        of the dumbbell rack."""
        lo, hi, _reason, _why, advisory = bodyweight_progression(
            base_reps_lo=15, base_reps_hi=15, is_timed=False,
            session_complete=True, avg_rating=5.0, avg_reps=15.0)
        assert (lo, hi) == (15, 15)
        assert advisory is not None
        assert "add load" in advisory

    def test_no_unreachable_set_rung_was_added(self):
        """Code only — the docstring names the rungs it declined, and
        matching that would be the note about the decision failing the
        test for the decision."""
        src = inspect.getsource(bodyweight_progression)
        body = src.split('"""')[2]
        assert "target_sets" not in body
        assert "sets" not in body


class TestItIsReachedAndItsReasonSurvives:
    def test_a_bodyweight_lift_now_gets_a_rep_reason(self):
        rx = next_prescription(
            exercise={"id": "Pullups", "name": "Pull-Ups",
                      "equipment": ["bodyweight"], "is_compound": True,
                      "movement_pattern": "vertical_pull"},
            reps_lo=8, reps_hi=12, level="intermediate", goal="hypertrophy",
            avg_rating=5.0, avg_weight_lb=None, avg_reps=12.0, enough=True,
            pairs_lb=[10, 15, 20], wrist_weights_lb=[],
        )
        assert rx.weight_lb is None
        assert rx.reps_lo == 9 and rx.reps_hi == 13
        assert rx.about_load is False

    def test_a_bodyweight_lift_with_no_history_still_falls_through(self):
        """Nothing to read is still nothing to read — the ladder must not
        manufacture a first target out of an empty log."""
        rx = next_prescription(
            exercise={"id": "Pullups", "name": "Pull-Ups",
                      "equipment": ["bodyweight"], "is_compound": True,
                      "movement_pattern": "vertical_pull"},
            reps_lo=8, reps_hi=12, level="intermediate", goal="hypertrophy",
            avg_rating=None, avg_weight_lb=None, avg_reps=None, enough=True,
            pairs_lb=[10, 15, 20], wrist_weights_lb=[],
        )
        assert rx.reason == "no_history"
        assert (rx.reps_lo, rx.reps_hi) == (8, 12)

    def test_a_dumbbell_lift_is_untouched(self):
        """The whole weighted policy must be unchanged; this branch is
        reached only when there is no load to decide."""
        rx = next_prescription(
            exercise={"id": "Dumbbell_Bench_Press", "name": "DB Bench",
                      "equipment": ["dumbbell", "bench"], "is_compound": True,
                      "movement_pattern": "horizontal_push"},
            reps_lo=8, reps_hi=12, level="intermediate", goal="hypertrophy",
            avg_rating=5.0, avg_weight_lb=25.0, avg_reps=12.0, enough=True,
            pairs_lb=[10, 15, 20, 25, 30], wrist_weights_lb=[],
        )
        assert rx.weight_lb is not None
        assert rx.about_load is True

    def test_the_mobility_cooldown_is_not_double_laddered(self):
        """It builds its ExerciseInPlan directly with
        `adjust_mobility_target` and never calls `next_prescription`, so a
        pose is nudged once rather than twice."""
        src = inspect.getsource(algo.generate_plan)
        block = src[src.index("if include_mobility:"):]
        assert "adjust_mobility_target" in block
        assert "next_prescription" not in block
