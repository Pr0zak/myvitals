"""A day of pull-ups is a day of training — OG2-A3.

Two aggregates opened their loop with::

    if skipped or w_lb is None or reps is None or set_type == "warmup":
        continue

one line above ``workout_dates.add(date_iso)``. So a set with no poundage was
dropped before ANYTHING was counted: ``n_workouts``, ``n_sets``, the daily
series, the ratings and the muscle split all excluded it, and a
calisthenics-only day reported as no session at all. The weekly mesocycle
chart showed a gap where training had happened.

That is 233 of 760 logged sets on this database and 101 of 275 catalog
exercises — on a home gym whose equipment is dumbbells, a bench and a pull-up
bar, so the excluded third is not an edge case, it is a large part of what
this user actually does.

The question those endpoints meant to ask is "was this set performed". The
question they asked is "does this set have poundage". Those are different,
and conflating them is what made a training day disappear.

`/records` already fixed exactly this in PR-1b — its docstring quotes the
same 233 figure — and `list_workouts` at :1358 has always filtered on
`actual_reps` alone. So the codebase contained both the right and the wrong
version of one query, twenty sections apart, and disagreed with itself on
screen. The predicate is now shared so a third reader cannot invent a fourth
answer.

An unweighted set is counted as work and withheld from the pounds totals. It
is deliberately NOT costed at zero: a volume figure that quietly absorbs a
set of pull-ups as 0 lb is worse than one that admits it is partial, which is
the rule `_sum_nutrition` follows for an ingredient it cannot cost. The
endpoints emit `weighted_sets` and `unweighted_sets` so a client can say what
fraction of the work the pounds total speaks for rather than implying it
covers the session.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import (
    SET_EXCLUDED,
    SET_UNWEIGHTED,
    SET_WEIGHTED,
    classify_set_row,
)


class TestTheReportedCase:
    def test_a_pull_up_is_performed_work(self):
        """The bug. A bodyweight set has reps and no weight."""
        assert classify_set_row(
            skipped=False, reps=8, set_type="working", weight_lb=None,
        ) == SET_UNWEIGHTED

    def test_a_plank_is_performed_work(self):
        """A timed hold stores its seconds in `actual_reps` and no weight."""
        assert classify_set_row(
            skipped=False, reps=60, set_type="working", weight_lb=None,
        ) == SET_UNWEIGHTED

    def test_unweighted_is_not_excluded(self):
        """Stated as its own assertion because this IS the fix.

        The two states used to be one. Everything else in this file follows
        from their being different.
        """
        assert SET_UNWEIGHTED != SET_EXCLUDED

    def test_a_loaded_set_is_still_weighted(self):
        assert classify_set_row(
            skipped=False, reps=8, set_type="working", weight_lb=45.0,
        ) == SET_WEIGHTED


class TestWhatIsGenuinelyNotWork:
    def test_a_skipped_set_is_excluded(self):
        assert classify_set_row(
            skipped=True, reps=8, set_type="working", weight_lb=45.0,
        ) == SET_EXCLUDED

    def test_a_warmup_is_excluded(self):
        """SETTYPE-1's rule, unchanged by this fix."""
        assert classify_set_row(
            skipped=False, reps=8, set_type="warmup", weight_lb=45.0,
        ) == SET_EXCLUDED

    def test_a_set_with_no_reps_was_never_logged(self):
        """`actual_reps IS NULL` means the row exists but nothing was done.

        This is the one null that genuinely means absence, which is why it
        keeps excluding while the null weight no longer does.
        """
        assert classify_set_row(
            skipped=False, reps=None, set_type="working", weight_lb=45.0,
        ) == SET_EXCLUDED

    def test_a_drop_set_still_counts_as_work(self):
        """Only warm-ups are excluded from volume, deliberately.

        A drop set is work performed — it is merely not evidence about next
        session's load, which is a different question answered by
        `PROGRESSION_EXCLUDED_SET_TYPES`. Sweeping it in here would make the
        volume audit disagree with `weekly_muscle_volume`.
        """
        assert classify_set_row(
            skipped=False, reps=8, set_type="drop", weight_lb=30.0,
        ) == SET_WEIGHTED


class TestZeroIsNotNull:
    def test_a_zero_weight_set_is_weighted_not_unweighted(self):
        """0.0 is falsy and the guard is `is None` for that reason.

        A truthy test would reclassify a genuine zero as unweighted and
        silently move it out of the pounds total.
        """
        assert classify_set_row(
            skipped=False, reps=8, set_type="working", weight_lb=0.0,
        ) == SET_WEIGHTED

    def test_zero_reps_is_still_a_logged_set(self):
        """A logged failure at 0 reps happened; it is not an absent row."""
        assert classify_set_row(
            skipped=False, reps=0, set_type="working", weight_lb=45.0,
        ) == SET_WEIGHTED


class TestBothEndpointsShareThePredicate:
    def test_stats_uses_it(self):
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api.strength_stats)
        assert "classify_set_row" in src
        assert "w_lb is None or reps is None" not in src, (
            "the conflated guard is back in /stats"
        )

    def test_volume_trend_uses_it(self):
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api.strength_volume_trend)
        assert "classify_set_row" in src
        assert "w_lb is None or reps is None" not in src, (
            "the conflated guard is back in /volume-trend"
        )

    def test_both_report_the_denominator(self):
        """A pounds total that cannot speak for the whole session must say so.

        Without these two counts a client showing "0 lb" beside "3 workouts"
        looks broken rather than accurate, and the honest caption cannot be
        written at all.
        """
        from myvitals.api.workout import strength as api

        for fn in (api.strength_stats, api.strength_volume_trend):
            src = inspect.getsource(fn)
            assert "unweighted_sets" in src, f"{fn.__name__} hides the gap"
            assert "weighted_sets" in src, f"{fn.__name__} hides the gap"


class TestTheUnweightedSetIsNotCostedAtZero:
    def test_the_stats_loop_skips_volume_for_an_unweighted_set(self):
        """Counted as a set, withheld from pounds — never added as 0 lb.

        Costing it at zero would keep the set count right and quietly drag
        every average down, which is the failure mode that looks correct.
        """
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api.strength_stats)
        i_kind = src.index("SET_UNWEIGHTED")
        i_vol = src.index("daily_vol[date_iso]")
        assert i_kind < i_vol, (
            "the unweighted branch must return before the volume accumulates"
        )

    def test_the_muscle_split_is_weighted_only(self):
        """`per_muscle` is a pounds figure and stays one.

        Attributing a bodyweight set to a muscle at zero pounds would put a
        muscle on the chart with no volume behind it, which reads as trained
        and un-trained at the same time. The muscle-volume audit answers that
        question separately, in sets.
        """
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api.strength_stats)
        i_kind = src.index("SET_UNWEIGHTED")
        i_muscle = src.index("per_muscle[muscle]")
        assert i_kind < i_muscle


class TestTheProgressionSeriesBoundaryMovedInC3:
    """A3 deliberately left the series weight-keyed and pinned that here.

    The pin did its job: OG2-C3 is the change that crosses it, and this test
    is the thing that made the crossing deliberate rather than accidental. It
    now asserts the new rule instead of the old boundary — see
    `test_progression_metric.py` for the substance.
    """

    def test_the_series_no_longer_drops_unweighted_sets(self):
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api.strength_stats)
        i_point = src.index("progression.setdefault")
        i_unweighted = src.index("SET_UNWEIGHTED")
        assert i_point < i_unweighted, (
            "the progression point must be built before the unweighted "
            "branch returns, or bodyweight history is dropped again"
        )
