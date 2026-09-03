"""Three strength readers that disagreed with their siblings — OG2-D-1.

OG2-B1, B2 and B3 unified the readers that decide a LOAD. Three readers
adjacent to them were not in that pass and each had drifted from the
predicate its siblings share. None of the three had bitten yet on this
database, which is the argument for fixing them now rather than after they
do: all three are latent because of what the user happens not to have done,
not because of anything in the code.

**(a) `swap_exercise` nulled the weight but not the reason for it.** Its two
siblings null both together — `generate_plan` ("The weight reason described a
load this lift does not carry") and `add_exercise`. Before B3 this was
invisible, because nothing rendered `wex.notes`. B3 shipped that render to
both surfaces a week ago, so swapping a bodyweight lift into a slot now
prints a starting-weight rationale beside no weight. Zero rows carry it today
only because the render is newer than the last swap.

**(b) `recent_ratings_by_exercise` claimed a predicate it did not apply.** The
docstring said "completed workouts"; the query filtered neither status nor
set_type, while gating exercise SELECTION at `AUTO_AVOID_THRESHOLD`. The
set_type half is the fault OG2-A1 named on the progression side, and both
directions are wrong without cancelling: a warm-up rated Easy makes a hard
lift look comfortable, and a drop set is taken near failure by design, so
counting it makes a lift the user chose to push look like one they are
failing. The status half was a real choice between two siblings that
deliberately disagree, and it is recorded in the docstring.

**(c) `_advance_program_on_complete` advanced a linear program off one set.**
It filtered `set_type` and `actual_reps` but not `skipped`, and then took
`min(reps)` over whatever existed — so a prescribed three-set lift that logged
one advanced exactly as if it had logged three. `SessionRead.enough` is the
predicate B1 built for this question and this reader did not consult it.

The gate keeps B1's asymmetry, and the reason is the same one: `min_working`
is a minimum over the sets that EXIST, and the sets a user abandons are the
late ones, which are the hard ones. A truncated session's minimum therefore
reads higher than the session was, and it advances precisely when the advance
is least earned. A short session that genuinely failed is still real evidence
to cut.

It is written as one gate over the computed result rather than a branch inside
each of the three schemes, so a fourth scheme inherits it instead of having to
remember it — and it declines to stamp `last_advanced_on`, for the reason the
`min_working_reps is None` branch already states: the date is consumed by an
act, and holding is not one.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import (
    PROGRESSION_EXCLUDED_SET_TYPES,
    SetFacts,
    advance_program_lift,
    read_session,
)
from myvitals.api.workout import strength as api

LINEAR = {
    "exercise_id": "X", "scheme": "linear", "current_weight_lb": 100.0,
    "increment_lb": 5.0, "reps_low": 5, "consecutive_fails": 0,
    "fails_before_deload": 3, "deload_pct": 0.10,
}


def _sets(*specs) -> list[SetFacts]:
    return [
        SetFacts(skipped=sk, actual_reps=r, set_type=t,
                 actual_weight_lb=25.0, rating=4)
        for r, t, sk in specs
    ]


class TestSwapNullsBothOrNeither:
    def test_a_bodyweight_swap_clears_the_weight_reason(self):
        """The reason renders verbatim on both surfaces since B3, so leaving
        it describes a load the slot does not carry."""
        src = inspect.getsource(api.swap_exercise)
        block = src[src.index('if "dumbbell" not in new_ex["equipment"]:'):]
        assert "target = None" in block[:400]
        assert "why_target = None" in block[:400]

    def test_all_three_prescription_sites_agree(self):
        """generate_plan and add_exercise already did this. The value of the
        fix is that the three sites now say the same thing."""
        for src in (
            inspect.getsource(algo.generate_plan),
            inspect.getsource(api.add_exercise),
            inspect.getsource(api.swap_exercise),
        ):
            assert "why_target = None" in src


class TestTheRatingsReaderAppliesWhatItClaims:
    def test_it_excludes_warmups_and_drops(self):
        """OG2-A1's constant, shared rather than re-listed."""
        src = inspect.getsource(algo.recent_ratings_by_exercise)
        assert "PROGRESSION_EXCLUDED_SET_TYPES" in src

    def test_it_filters_on_workout_status(self):
        src = inspect.getsource(algo.recent_ratings_by_exercise)
        assert "StrengthWorkout.status" in src

    def test_the_docstring_no_longer_claims_an_unapplied_predicate(self):
        """The original said "completed workouts" over a query with no status
        filter at all. Either half may be corrected; they may not disagree."""
        doc = algo.recent_ratings_by_exercise.__doc__ or ""
        src = inspect.getsource(algo.recent_ratings_by_exercise)
        if "completed" in doc.split("Two predicates")[0]:
            assert "status" in src

    def test_the_status_choice_is_stated(self):
        """Its two sibling readers disagree here deliberately —
        `days_since_muscle_trained` includes in_progress and
        `read_recent_sessions` does not — so which one this follows is a
        decision that has to be written down, not inferred from a WHERE."""
        doc = algo.recent_ratings_by_exercise.__doc__ or ""
        assert "days_since_muscle_trained" in doc
        assert "read_recent_sessions" in doc


class TestTheProgramAdvanceReadsTheSessionOnce:
    def test_the_caller_uses_the_shared_reducer(self):
        src = inspect.getsource(api._advance_program_on_complete)
        assert "read_session" in src

    def test_it_no_longer_re_derives_the_qualifying_predicate(self):
        """A fourth hand-rolled copy of "which sets count" is how this one
        came to be missing `skipped`."""
        src = inspect.getsource(api._advance_program_on_complete)
        assert "PROGRESSION_EXCLUDED_SET_TYPES" not in src

    def test_a_skipped_set_carrying_reps_is_excluded(self):
        """The concrete defect. The old query filtered actual_reps IS NOT
        NULL and nothing else, so a skipped set with reps entered min()."""
        r = read_session(target_sets=2, slot_declined=False,
                         sets=_sets((8, "working", False), (2, "working", True)))
        assert r.qualifying_reps == (8,)

    def test_a_warmup_does_not_become_the_minimum(self):
        r = read_session(target_sets=2, slot_declined=False,
                         sets=_sets((3, "warmup", False), (8, "working", False)))
        assert r.qualifying_reps == (8,)

    def test_a_failure_set_still_counts(self):
        """Greyskull's AMRAP is tagged set_type="failure" and is the whole
        input to that scheme."""
        assert "failure" not in PROGRESSION_EXCLUDED_SET_TYPES
        r = read_session(target_sets=2, slot_declined=False,
                         sets=_sets((8, "working", False), (11, "failure", False)))
        assert r.qualifying_reps == (8, 11)

    def test_the_reps_stay_in_set_number_order(self):
        """Greyskull reads reps[-1] as the AMRAP, so order is load-bearing
        and the list must not be re-sorted by value."""
        r = read_session(target_sets=3, slot_declined=False,
                         sets=_sets((9, "working", False), (5, "working", False),
                                    (12, "failure", False)))
        assert r.qualifying_reps == (9, 5, 12)


class TestTheShortSessionGate:
    def test_a_full_session_advances(self):
        out = advance_program_lift(LINEAR, 8, on_date="2026-09-02",
                                   session_complete=True)
        assert out["current_weight_lb"] == 105.0

    def test_a_short_session_holds_instead(self):
        """One logged set of a prescribed three used to advance identically."""
        out = advance_program_lift(LINEAR, 8, on_date="2026-09-02",
                                   session_complete=False)
        assert out["current_weight_lb"] == 100.0

    def test_a_short_failed_session_still_cuts(self):
        """B1's asymmetry. Refusing to act would leave a weight the user
        could not lift standing because they stopped early."""
        st = {**LINEAR, "consecutive_fails": 2}
        out = advance_program_lift(st, 3, on_date="2026-09-02",
                                   session_complete=False)
        assert out["current_weight_lb"] == 90.0

    def test_a_held_session_does_not_burn_the_date_guard(self):
        """The same reasoning the `min_working_reps is None` branch states:
        the per-date guard is consumed by an ACT. Stamping on a hold would
        mean finishing the remaining sets and re-completing could never
        advance the lift."""
        out = advance_program_lift(LINEAR, 8, on_date="2026-09-02",
                                   session_complete=False)
        assert "last_advanced_on" not in out

    def test_a_session_that_acted_does_stamp(self):
        for complete, reps in ((True, 8), (False, 3)):
            out = advance_program_lift({**LINEAR, "consecutive_fails": 2},
                                       reps, on_date="2026-09-02",
                                       session_complete=complete)
            assert out["last_advanced_on"] == "2026-09-02"

    def test_greyskull_is_gated_too(self):
        st = {**LINEAR, "scheme": "greyskull", "fails_before_deload": 1}
        assert advance_program_lift(
            st, 5, 10, session_complete=True)["current_weight_lb"] > 100.0
        assert advance_program_lift(
            st, 5, 10, session_complete=False)["current_weight_lb"] == 100.0

    def test_double_is_gated_too(self):
        st = {**LINEAR, "scheme": "double", "reps_high": 12}
        assert advance_program_lift(
            st, 12, session_complete=True)["current_weight_lb"] > 100.0
        assert advance_program_lift(
            st, 12, session_complete=False)["current_weight_lb"] == 100.0

    def test_the_gate_is_one_block_not_three(self):
        """Written over the computed result rather than inside each scheme,
        so a fourth scheme inherits it instead of having to remember it."""
        src = inspect.getsource(advance_program_lift)
        assert src.count("if not session_complete") == 1

    def test_the_default_preserves_existing_behaviour(self):
        assert inspect.signature(
            advance_program_lift).parameters["session_complete"].default is True

    def test_a_bodyweight_program_lift_is_unaffected(self):
        """current_weight_lb is None — there is no weight to hold or raise,
        and the gate must not crash reaching for one."""
        st = {**LINEAR, "current_weight_lb": None}
        out = advance_program_lift(st, 8, on_date="2026-09-02",
                                   session_complete=False)
        assert out["current_weight_lb"] is None
