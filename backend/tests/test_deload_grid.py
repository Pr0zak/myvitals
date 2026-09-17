"""Deloading on the (weight x reps) grid — OG3-E1.

`deload_round` searches one axis, and on this user's rack that axis has no
resolution to search. `dumbbells.pairs_lb` steps in 5 and `wrist_weights_lb`
is EMPTY, so the app's flagship micro-loader rounder is inert here and the
grid is 5 lb coarse.

Work a light deload through and the guard settles it: a 7.5% cut on a 15 lb
lift targets 13.875, `round_weight` drops to 10, `deload_round` sees a cut
more than twice the size intended and returns FULL WEIGHT. The same
arithmetic holds at every rung from 5 to 50 lb, so the light and moderate
recovery deload is a structural no-op on this equipment — which is consistent
with `strength_workouts.deload_factor` reading 1.0 on all 40 completed
workouts, including four whose recovery score maps to 0.85.

The guard is right. A gentle easing should not knock a third off the load.
But holding full weight is not the only alternative, and reps are continuous
where this rack is not.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as s

#: This user's actual rack, and the reason the feature exists.
PAIRS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
NO_MICROS: list[float] = []
#: What the rounder was designed for, and still handles alone.
MICROS = [1.5, 2.0]


class TestTheProblemItSolves:
    def test_the_weight_only_rounder_is_a_no_op_across_the_used_range(self):
        """The measurement behind the whole item, stated exactly.

        The no-op is not universal and the first draft of this test
        over-claimed that it was. Measured against this rack, a light or
        moderate deload cannot move the weight anywhere from 5 to 25 lb.
        Above that the absolute cut grows large enough to clear the
        disproportion guard and the drop goes through — 30 lb at 0.90 lands
        on 25, and 50 lb moves even at 0.95.

        What makes it total in practice is where this user actually trains.
        The mean of 547 weighted sets is 15.7 lb, the heaviest set ever
        logged is 30, and there are zero sets at or above 40 — so the rungs
        the guard freezes are the rungs this user lives on, and the ones
        where it lets go are ones they have barely reached.

        If this starts failing, either the rack changed or the user got
        stronger — and in both cases the feature has become less necessary
        rather than broken.
        """
        for rung in [p for p in PAIRS if p <= 25]:
            for factor in (0.95, 0.925, 0.90):
                out = s.deload_round(rung, factor, PAIRS, NO_MICROS)
                assert out == rung, (
                    f"{rung} lb at {factor} moved to {out} — the coarse-rack "
                    "premise no longer holds"
                )

    def test_above_that_range_the_weight_axis_does_move(self):
        """Stated so the scope of the claim is not lost.

        At 50 lb a 5% cut is 2.5 lb against a 5 lb step, which the guard
        lets through. The feature is aimed at the light end because that is
        where the arithmetic traps it.
        """
        assert s.deload_round(50, 0.95, PAIRS, NO_MICROS) < 50

    def test_the_grid_delivers_the_easing_the_rounder_could_not(self):
        w, reps, note = s.select_deload_candidate(15, 10, 8, PAIRS, NO_MICROS, 0.925)
        assert w == 15, "weight should hold — the rack has nothing between 10 and 15"
        assert reps < 10, "the easing has to come from somewhere"
        assert note and "cannot deliver" in note


class TestTheWeightAxisStillWinsWhenItCan:
    def test_micro_loaders_take_the_weight_axis(self):
        """The distinguishing feature must not be switched off by its cover.

        An earlier draft tie-broke toward the heavier load and so held 15 lb
        and cut reps even when 13.5 lb was loadable — turning the one thing
        this app does that Fitbod, Hevy, Strong and JEFIT do not into dead
        code, in the name of working around its absence.
        """
        w, reps, note = s.select_deload_candidate(15, 10, 8, PAIRS, MICROS, 0.925)
        assert w == s.deload_round(15, 0.925, PAIRS, MICROS)
        assert w < 15
        assert reps == 10, "reps hold when the weight axis did the work"
        assert note and "eased to" in note

    def test_a_severe_deload_still_takes_the_pair_drop(self):
        """Unchanged behaviour: the guard only ever protected light cuts."""
        w, reps, _ = s.select_deload_candidate(50, 6, 5, PAIRS, NO_MICROS, 0.85)
        assert w == s.deload_round(50, 0.85, PAIRS, NO_MICROS) < 50
        assert reps == 6


class TestItOnlyEverEases:
    def test_no_deload_is_a_no_op(self):
        assert s.select_deload_candidate(15, 10, 8, PAIRS, NO_MICROS, 1.0) == (15, 10, None)

    def test_it_never_returns_more_weight(self):
        for factor in (0.95, 0.90, 0.85, 0.70):
            w, _, _ = s.select_deload_candidate(30, 8, 6, PAIRS, NO_MICROS, factor)
            assert w is not None and w <= 30

    def test_it_never_returns_more_reps(self):
        """More reps at the same weight is not an easier session.

        An unbounded search picks exactly that, because adding reps at a
        lighter load lands closer to the eased target e1RM. The first draft
        of this function turned a 7.5% deload of 15x10 into 10 lb x 12.
        """
        for factor in (0.95, 0.90, 0.85):
            for reps in (6, 8, 10, 12):
                _, r, _ = s.select_deload_candidate(
                    20, reps, max(1, reps - 4), PAIRS, NO_MICROS, factor)
                assert r <= reps

    def test_it_never_goes_below_the_working_range(self):
        _, r, _ = s.select_deload_candidate(20, 12, 10, PAIRS, NO_MICROS, 0.70)
        assert r >= 10

    def test_a_none_weight_passes_through(self):
        """Bodyweight lifts have no load to ease; they have their own ladder."""
        assert s.select_deload_candidate(None, 10, 8, PAIRS, NO_MICROS, 0.85) == (None, 10, None)


class TestTheChangeIsAlwaysStated:
    def test_every_adjustment_carries_a_note(self):
        """A silent adjustment is the thing that erodes trust in the rest.

        A prescription that quietly holds its weight and drops two reps,
        while the screen still says the session was eased for recovery, is
        indistinguishable from a bug — same convention as MEAL-9's visible
        arithmetic repairs.
        """
        for factor in (0.925, 0.90, 0.85):
            w, r, note = s.select_deload_candidate(15, 10, 8, PAIRS, NO_MICROS, factor)
            changed = w != 15 or r != 10
            assert changed == (note is not None)

    def test_a_no_op_says_nothing(self):
        """No claim of an easing that did not happen."""
        _, _, note = s.select_deload_candidate(5, 10, 10, PAIRS, NO_MICROS, 0.925)
        assert note is None


class TestItIsScopedToTheNonAdvancingBranches:
    def test_the_easing_helper_refuses_to_touch_an_advance(self):
        src = inspect.getsource(s.next_prescription)
        assert "never ease an advance" in src

    def test_the_prescription_carries_the_note_to_both_clients(self):
        """Through `Prescription.why`, so no client change is needed.

        OG2-B3 already made `why` the one place a target explains itself,
        and both surfaces render it verbatim.
        """
        src = inspect.getsource(s.next_prescription)
        assert "Recovery:" in src
