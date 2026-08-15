"""SKIP-1 — per-exercise skip and the progress counters both clients render.

The bug this feature closes: completing a workout left any exercise the user
had walked away from with zero set rows, which every client's done-predicate
reads as "not started". Those slots then sorted to the TOP of a finished
session and kept rendering live set-logging tables.

The counters live here rather than in the clients because four separate client
formulas used to derive them independently and disagreed — the web set pip
excluded individually-skipped sets while the phone's included them.
"""
from __future__ import annotations

from myvitals.api.workout.strength import (
    SetOut,
    WorkoutExerciseOut,
    _accounted_sets,
    _exercise_done,
)


def _wex(target_sets: int = 3, *, skipped: bool = False,
         sets: list[SetOut] | None = None) -> WorkoutExerciseOut:
    return WorkoutExerciseOut(
        id=1, workout_id=1, exercise_id="Some_Lift", order_index=0,
        superset_id=None, target_sets=target_sets,
        target_reps_low=8, target_reps_high=10, target_weight_lb=30.0,
        target_rest_s=90, notes=None, skipped=skipped, sets=sets or [],
    )


def _set(n: int, *, reps: int | None = 8, skipped: bool = False) -> SetOut:
    return SetOut(
        id=n, workout_exercise_id=1, set_number=n,
        target_weight_lb=30.0, target_reps=8,
        actual_weight_lb=30.0 if reps is not None else None,
        actual_reps=reps, rating=4 if reps is not None else None,
        rest_seconds_taken=None, logged_at=None, skipped=skipped,
    )


class TestAccountedSets:
    def test_untouched_exercise_accounts_for_nothing(self):
        assert _accounted_sets(_wex(3)) == 0

    def test_logged_sets_count(self):
        assert _accounted_sets(_wex(3, sets=[_set(1), _set(2)])) == 2

    def test_individually_skipped_sets_count_as_dealt_with(self):
        wex = _wex(3, sets=[_set(1), _set(2, reps=None, skipped=True)])
        assert _accounted_sets(wex) == 2

    def test_skipped_exercise_accounts_for_its_whole_prescription(self):
        assert _accounted_sets(_wex(3, skipped=True)) == 3

    def test_skipped_exercise_ignores_its_own_set_rows(self):
        # Belt-and-braces: a slot skipped after a partial log still reports
        # the full prescription, so session progress can't exceed 100%.
        assert _accounted_sets(_wex(3, skipped=True, sets=[_set(1)])) == 3

    def test_extra_sets_cannot_inflate_progress(self):
        wex = _wex(2, sets=[_set(1), _set(2), _set(3)])
        assert _accounted_sets(wex) == 2


class TestExerciseDone:
    def test_untouched_is_not_done(self):
        assert _exercise_done(_wex(2)) is False

    def test_partial_is_not_done(self):
        assert _exercise_done(_wex(2, sets=[_set(1)])) is False

    def test_all_sets_logged_is_done(self):
        assert _exercise_done(_wex(2, sets=[_set(1), _set(2)])) is True

    def test_skipped_exercise_is_done_with_no_sets_at_all(self):
        # The regression under test: this is exactly the state that made two
        # yoga poses float to the top of a completed workout.
        assert _exercise_done(_wex(2, skipped=True)) is True

    def test_timed_hold_with_zero_reps_still_counts_as_logged(self):
        # A 0-second hold is a real (bad) log, not an absence. actual_reps=0
        # is not None, so it must not read as untouched.
        assert _exercise_done(_wex(1, sets=[_set(1, reps=0)])) is True


class TestSessionCounters:
    """The shape _hydrate_workout folds into exercises_done / sets_done."""

    def test_workout_202_shape_before_and_after_skip(self):
        # Eight fully-logged lifts plus a two-pose mobility block, which is
        # the live workout that surfaced this bug.
        lifts = [_wex(2, sets=[_set(1), _set(2)]) for _ in range(8)]
        yoga_untouched = [_wex(2), _wex(2)]
        before = lifts + yoga_untouched
        assert sum(1 for e in before if _exercise_done(e)) == 8
        assert sum(_accounted_sets(e) for e in before) == 16
        assert sum(e.target_sets for e in before) == 20

        after = lifts + [_wex(2, skipped=True), _wex(2, skipped=True)]
        assert sum(1 for e in after if _exercise_done(e)) == 10
        assert sum(_accounted_sets(e) for e in after) == 20
