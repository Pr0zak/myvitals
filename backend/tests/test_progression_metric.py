"""A chart plots what the history is about — OG2-C3 and OG2-C4.

**C3.** The per-exercise progress chart had no metric selection at all. The
axis was hard-named "lb", the card was titled "Weight progression", and the
series was built only from sets carrying a weight — so a pull-up, a push-up
or a plank could never appear in the picker however long its history. On this
database that is 153 of 548 performed sets over 90 days and 101 of 275
catalog exercises.

openGym hit the same thing and its issue #5 records both the fix and the
reasoning: the metric is a property of the DATA, not a setting. An exercise
that has never carried load progresses in reps, so reps are what to plot —
and "it switches back to weight the moment a loaded set appears" is the
honest half of the rule rather than a convenience, because that is the
session in which load became the thing improving.

The point is now built for every performed set and the metric decided per
exercise, with its unit and caption. A client renders those verbatim; the
axis label is no longer an assumption. e1RM is offered only on the weighted
branch, because an estimated one-rep maximum means nothing without a load.

**C4.** `rpe_avg` was printed bare on both surfaces. A rating is optional on
the way in — the web logger does not require one, and imported Strong/Hevy
history carries one only where the source file had an RPE column — so a
partly-rated history is the normal case and the mean silently spoke for sets
nobody rated.

This is house doctrine everywhere else: `analytics/projection.py` refuses
below MIN_POINTS with a rendered reason, `nutrition.py` refuses below
MIN_HISTORY rather than inventing a fat target, `/log/stats` refuses below 5
complete days and reports both counts. Reported rather than refused here,
because unlike those an average of five ratings is still worth seeing — it
simply must not claim to describe the other forty.
"""

from __future__ import annotations

import inspect
import pathlib

from myvitals.analytics.strength import (
    PROGRESSION_METRICS,
    progression_metric,
)
from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB_CHART = REPO / "frontend" / "src" / "views" / "workout" / "StrengthCharts.vue"
PHONE_CHART = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "WorkoutChartsScreen.kt"
)


class TestTheMetricComesFromTheData:
    def test_a_loaded_lift_plots_weight(self):
        assert progression_metric(has_weighted_set=True, is_timed=False) == "weight"

    def test_a_lift_never_loaded_plots_reps(self):
        """openGym's issue #5 verbatim: pull-ups and push-ups rendered "No
        data yet" against years of logged training."""
        assert progression_metric(has_weighted_set=False, is_timed=False) == "reps"

    def test_a_timed_hold_plots_seconds(self):
        assert progression_metric(has_weighted_set=False, is_timed=True) == "seconds"

    def test_a_weighted_hold_plots_weight_not_seconds(self):
        """Order matters. A weighted plank progresses by load, and its
        seconds are then the constant — so the weighted branch wins outright
        rather than being reached only for untimed lifts."""
        assert progression_metric(has_weighted_set=True, is_timed=True) == "weight"

    def test_every_metric_has_a_unit_and_a_caption(self):
        """The client renders these verbatim, so a metric without them would
        put an unlabelled axis on screen."""
        for metric in ("weight", "reps", "seconds"):
            unit, caption = PROGRESSION_METRICS[metric]
            assert unit and caption


class TestThePointIsBuiltForEverySet:
    def test_the_series_is_built_before_the_unweighted_branch(self):
        """The whole defect in one ordering.

        The progression point used to be built after the null-weight guard,
        so a bodyweight lift was dropped before it could have a series at
        all.
        """
        src = inspect.getsource(api.strength_stats)
        assert src.index("progression.setdefault") < src.index("SET_UNWEIGHTED")

    def test_a_point_carries_reps_as_well_as_weight(self):
        src = inspect.getsource(api.strength_stats)
        assert '"top_reps"' in src

    def test_weight_and_e1rm_stay_null_rather_than_zero(self):
        """A bodyweight set has no poundage, and 0 lb is a claim about a load
        rather than the absence of one — the null-is-not-zero rule this
        codebase applies from `_sum_nutrition` outward."""
        src = inspect.getsource(api.strength_stats)
        assert '"top_weight_lb": None' in src
        assert '"e1rm": None' in src

    def test_the_payload_names_the_metric(self):
        src = inspect.getsource(api.strength_stats)
        assert '"progression_metric": progression_metric_by_ex' in src


class TestTheRatingAverageCarriesItsDenominator:
    def test_the_payload_reports_the_rated_count(self):
        src = inspect.getsource(api.strength_stats)
        assert '"rated_sets": len(rpe_vals)' in src

    def test_it_is_reported_not_refused(self):
        """Unlike projection.py's MIN_POINTS, an average of five ratings is
        still worth seeing. The failure to avoid is it claiming to describe
        sets that were never rated, which a denominator fixes without hiding
        the number."""
        src = inspect.getsource(api.strength_stats)
        assert "rpe_avg" in src
        assert "MIN_RATED" not in src


class TestBothSurfacesRenderIt:
    def test_the_web_reads_the_server_metric(self):
        src = WEB_CHART.read_text()
        assert "progression_metric" in src
        # Scoped to the progression chart. The daily- and weekly-volume
        # charts are genuinely in pounds and keep their literal axis.
        prog = src[src.index("const progressionOption"):]
        prog = prog[:prog.index("const progressionCaption")]
        assert 'name: "lb"' not in prog, "the progression axis is hard-named again"
        assert "name: m.unit" in prog

    def test_the_web_shows_the_caption_and_denominator(self):
        src = WEB_CHART.read_text()
        assert "progressionCaption" in src
        assert "rpeDenominator" in src

    def test_the_web_card_is_no_longer_titled_weight_progression(self):
        """It charts reps and seconds too now."""
        assert 'title="Weight progression"' not in WEB_CHART.read_text()

    def test_the_phone_reads_the_server_metric(self):
        src = PHONE_CHART.read_text()
        assert "progressionMetric" in src
        assert "shape.caption" in src

    def test_the_phone_hides_e1rm_on_an_unweighted_lift(self):
        """An estimated one-rep maximum means nothing without a load, so the
        chip row is not offered rather than offering a chip that would plot
        a fabricated number."""
        src = PHONE_CHART.read_text()
        assert "if (weighted) {" in src

    def test_the_phone_shows_the_denominator(self):
        assert "ratedSets" in PHONE_CHART.read_text()

    def test_neither_client_decides_the_metric(self):
        """Server decides, clients render — the GOAL-STATE rule again."""
        for path in (WEB_CHART, PHONE_CHART):
            src = path.read_text()
            assert "is_timed" not in src
            assert "isTimed" not in src
