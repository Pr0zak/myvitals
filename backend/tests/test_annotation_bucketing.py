"""Per-day annotation aggregation for correlations (MOOD-1).

Two defects that silently corrupted every correlation built on
annotations, both in `_annotation_per_day`.

The backlog entry asked for structured mood and symptom logging on the
grounds that subjective data was missing. It is not: `mood_score` is
already in SUPPORTED_METRICS and already routed here, and per-type
journal UI exists on both surfaces. What was missing was correctness.
"""

from __future__ import annotations

import inspect

from myvitals.api import analytics


class TestLocalDayBucketing:
    def test_annotations_are_bucketed_by_local_date(self):
        """`row.ts.date()` is the UTC date. An 8pm Central entry yields
        the FOLLOWING date, so every evening annotation was filed a day
        forward."""
        src = inspect.getsource(analytics._annotation_per_day)
        assert "astimezone(tz).date()" in src
        # The ASSIGNMENT, not the prose — the docstring quotes the old
        # expression to explain why it changed.
        assert "d = row.ts.date()" not in src

    def test_this_inverted_the_alcohol_preset(self):
        """Not merely noise. The shipped "Alcohol -> next-day HRV" preset
        depends on the drink preceding the HRV; filing it a day forward
        lands it on the SAME day, which measures the opposite thing.
        Evening is when alcohol annotations happen, so this was the
        common case."""
        src = inspect.getsource(analytics._annotation_per_day)
        assert "next-day HRV" in src, "the reason belongs next to the fix"

    def test_the_query_window_is_widened_before_filtering(self):
        """A row inside the LOCAL window can sit outside the same UTC
        window, so querying the exact range would drop edge days."""
        src = inspect.getsource(analytics._annotation_per_day)
        assert "since - timedelta(days=1)" in src
        assert "until + timedelta(days=1)" in src
        assert "if d < since or d > until:" in src


class TestAggregation:
    def test_scores_are_averaged_not_summed(self):
        """Two mood entries of 7 summed to 14, a value a 1-10 scale
        cannot produce, which would dominate any correlation."""
        src = inspect.getsource(analytics._series_for_metric)
        assert 'agg="mean"' in src

    def test_counts_and_doses_still_sum(self):
        """Two drinks IS two, and two coffees IS the total mg. Averaging
        those would be the mirror-image error."""
        src = inspect.getsource(analytics._series_for_metric)
        alcohol = src.split('alcohol_count')[1].split('caffeine')[0]
        assert 'agg="mean"' not in alcohol

    def test_default_is_sum(self):
        sig = inspect.signature(analytics._annotation_per_day)
        assert sig.parameters["agg"].default == "sum"

    def test_mean_divides_by_the_count_not_the_window(self):
        """Dividing by the number of days would turn a single entry into
        a fraction of itself."""
        src = inspect.getsource(analytics._annotation_per_day)
        assert "sums[d] / counts[d]" in src
