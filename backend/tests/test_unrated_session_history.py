"""An unrated session is still a session — OG2-A2.

Every prescription site tested the same pair::

    if avg_rating is not None and avg_weight is not None:
        target = progress_from_rating(...)
    else:
        target = starting_weight_lb(movement_pattern, level)

`starting_weight_lb` is a table indexed by declared experience level. So a
session logged with real weights but no rating threw its own history away and
went back to that table: press 40 lb, forget to tap Hard/Good/Easy, and the
next prescription is 25 lb. `avg_weight` was in scope on the discarding line
and unused.

Reachable because the rating is optional on the way in. The phone requires
one before a set can be logged, but the web logger does not, and imported
Strong/Hevy history carries a rating only where the source file had an RPE
column — so a freshly imported history is largely unrated by construction.

The middle case now holds at the weight actually lifted. "Same as last time"
is the honest reading of an unrated session: it is not evidence to advance
on, and it is emphatically not evidence that the lifter has reverted to a
beginner. That reasoning is the same one `analytics/projection.py` applies
when it refuses to project rather than guessing a trend, and the same one
MEAL-2 applies by leaving the fat target None rather than inventing one.

Three call sites shared the bug — the generator, the ad-hoc add and the swap
— so the decision is one pure function they all consume rather than a branch
each of them spells out. Two of the three had already drifted apart on the
`goal` argument, which is what that consolidation is guarding against.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import weight_from_history


class TestTheReportedCase:
    def test_an_unrated_session_holds_at_what_was_lifted(self):
        """The bug, stated as a value.

        40 lb logged with no rating must prescribe 40 lb, not the starting
        table's answer for the user's declared level.
        """
        target, why = weight_from_history(40.0, None, is_compound=False)
        assert target == 40.0
        assert why == "held_unrated"

    def test_the_hold_is_not_a_silent_fallthrough(self):
        """It must be distinguishable from "no history" by the caller.

        Both used to produce a number with no way to tell which branch made
        it, which is precisely why the fault survived review: the wrong
        answer and the right one looked identical from outside.
        """
        held, why_held = weight_from_history(40.0, None, is_compound=False)
        none, why_none = weight_from_history(None, None, is_compound=False)
        assert why_held != why_none
        assert held is not None and none is None

    def test_no_history_still_falls_back(self):
        """The starting table is the right answer when there is nothing.

        The fix narrows when that table is consulted; it does not remove it.
        """
        target, why = weight_from_history(None, 4.0, is_compound=True)
        assert target is None
        assert why == "no_history"


class TestARatingStillDecides:
    def test_an_easy_rating_advances(self):
        target, why = weight_from_history(
            100.0, 5.0, is_compound=True, goal="hypertrophy")
        assert why == "rated"
        assert target > 100.0

    def test_a_failed_rating_backs_off(self):
        target, why = weight_from_history(100.0, 1.0, is_compound=True)
        assert why == "rated"
        assert target < 100.0

    def test_the_middle_of_the_scale_holds(self):
        """Which coincides with the unrated answer, and must not be confused
        with it: one is a judgement the user made, the other is the absence
        of one. The reason string keeps them apart."""
        rated, why_rated = weight_from_history(100.0, 3.0, is_compound=True)
        unrated, why_unrated = weight_from_history(100.0, None, is_compound=True)
        assert rated == unrated == 100.0
        assert why_rated == "rated"
        assert why_unrated == "held_unrated"

    def test_a_rating_of_zero_is_a_rating(self):
        """0 is falsy, and the guard is `is None` for that reason.

        Ratings are 1-5 today so this cannot arise from the UI, but an
        importer mapping an out-of-range RPE could produce it, and a truthy
        test would silently reclassify it as unrated.
        """
        target, why = weight_from_history(100.0, 0.0, is_compound=True)
        assert why == "rated"
        assert target < 100.0

    def test_the_goal_is_threaded_through(self):
        """A strength goal takes bigger jumps than a general one.

        Two of the three call sites omitted `goal` entirely and silently got
        the hypertrophy default, so the same lift advanced differently
        depending on how it entered the plan. Consolidating the branch is
        what makes fixing that a one-line change rather than three.
        """
        strength_goal, _ = weight_from_history(
            100.0, 5.0, is_compound=True, goal="strength")
        general_goal, _ = weight_from_history(
            100.0, 5.0, is_compound=True, goal="general")
        assert strength_goal > general_goal


class TestEveryCallSiteUsesIt:
    """Three sites had the identical branch, and had already diverged.

    `generate_plan` passed `goal`; the ad-hoc add and the swap did not, so an
    exercise appended mid-session advanced on the hypertrophy schedule while
    the same lift in the generated plan advanced on the user's actual goal.
    Consolidating removes that as a class rather than as an instance.
    """

    def test_the_generator_uses_it(self):
        """OG2-B2 moved the branch behind `next_prescription`, so the
        generator names the entry point and the entry point names this. The
        invariant is unchanged and is now enforced one layer up."""
        assert "weight_from_history" in inspect.getsource(algo.next_prescription)
        assert "next_prescription" in inspect.getsource(algo.generate_plan)

    def test_the_api_sites_use_it(self):
        from myvitals.api.workout import strength as api

        # OG2-B2: both now go through the shared entry point, which is the
        # stronger check — a site reaching past it to `weight_from_history`
        # would have reconstructed the branch this consolidated.
        for fn in (api.add_exercise, api.swap_exercise):
            src = inspect.getsource(fn)
            assert "next_prescription" in src, f"{fn.__name__} still branches itself"

    def test_no_site_reaches_past_it_to_the_starting_table(self):
        """`starting_weight_lb` must only be reached when the helper returns
        None. A site testing `avg_rating is not None` on its own has
        reintroduced the bug in the one shape that looks correct.
        """
        from myvitals.api.workout import strength as api

        sources = [
            inspect.getsource(algo.generate_plan),
            inspect.getsource(api.add_exercise),
            inspect.getsource(api.swap_exercise),
        ]
        for src in sources:
            assert "avg_rating is not None and avg_weight is not None" not in src or (
                "is_weighted" in src
            ), "the two-way rating/weight guard is back outside double progression"


class TestDoubleProgressionIsUnaffected:
    def test_a_rated_dumbbell_lift_still_takes_the_double_progression_path(self):
        """The fix must not swallow the rep-ladder policy.

        `double_progression` needs a rating to judge the last session, so it
        keeps its own guard; the consolidated helper is the weight-only
        fallback beneath it. Losing that ordering would unstick nothing and
        would quietly re-round light fixed pairs back onto the same load.
        """
        src = inspect.getsource(algo.next_prescription)
        i_dp = src.index("double_progression(")
        i_wfh = src.index("weight_from_history(")
        assert i_dp < i_wfh, "double progression must remain the first branch"
