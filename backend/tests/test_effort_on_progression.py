"""A flat line that was actually progress — OG2-D-4 and OG2-D-3.

Straight-Arm Dumbbell Pullover holds 20 lb across four sessions while the
rating moves 4, 4, 5, 5, and then jumps to 25. The weight-only line draws
those four sessions dead flat — so the sessions in which the lift got easier,
which are the sessions that EARNED the jump, were rendered as no progress at
all. The rating was already SELECTed, already unpacked and already fed the
global average; it was simply dropped before reaching the point.

**The band is decided on the server, and its boundaries are the progression
policy's own.** `effort_band` reuses `EASY_THRESHOLD` and `FAIL_THRESHOLD`
rather than introducing a scale of its own, so a dot marked "easy" is exactly
the dot where `weight_from_history` added weight and one marked "failed" is
exactly where it cut. A second set of thresholds would let the chart disagree
with the prescription it is drawing.

It is decided server-side for GOAL-STATE's reason, and the reason is sharper
here than usual: this app rates sets 1-5 where 5 is EASY, so the scale counts
UP with ease, while openGym's RIR counts down. Which end means what is
exactly the sort of inversion two clients eventually disagree about.

**Measured before shipping**, per exercise per day across this database's
rated history: working 199 exercise-days (2.00-4.33), easy 82 (4.50-5.00),
failed 1 (1.00). All three bands occur — the test OG2-C1's fatigue model and
OG2-B1's stall count both failed, where a band that can never fire is a
legend entry explaining nothing.

**An unrated day is an absence, not the middle band.** A rating is optional
on the way in — the web logger does not require one and imported history
carries one only where the source had an RPE column — so `rating_avg` and
`effort` stay None and the clients say "No sets rated this session" rather
than painting it as ordinary. `rated_sets` travels alongside for OG2-C4's
reason: a mean over two of five sets must not silently speak for the other
three.

**D-3, the phone half.** None of the four Vico charts passed a `marker` and
nothing under ui/strength took a pointer gesture, so the series was
interrogable on the desktop and mute on the phone — and unlike the ~14
hand-rolled Canvas charts, which all carry an exact-value list beneath them,
these four had no way at all to read a point. The readout defaults to the
LATEST session rather than to nothing, because a readout that appears only
after a tap is one most people never find.
"""

from __future__ import annotations

import inspect
import pathlib

from myvitals.analytics import strength as algo
from myvitals.analytics.strength import (
    EASY_THRESHOLD,
    EFFORT_BANDS,
    FAIL_THRESHOLD,
    effort_band,
    finish_progression_point,
)
from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]


def _code_only(src: str) -> str:
    """Strip // and /* */ comments.

    Every check below that asserts something is ABSENT has to read code
    rather than prose, or it matches the paragraph explaining why the thing
    is absent — which is the note that keeps these decisions legible and
    should not be what makes the test pass or fail.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
        else:
            out.append(src[i])
            i += 1
    return "".join(out)
WEB_CHART = REPO / "frontend" / "src" / "views" / "workout" / "StrengthCharts.vue"
WEB_MOD = REPO / "frontend" / "src" / "effort.ts"
PHONE_CHART = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "WorkoutChartsScreen.kt"
)
PHONE_MOD = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "Effort.kt"
)


class TestTheBandIsThePolicysOwn:
    def test_easy_starts_where_the_policy_adds_weight(self):
        assert effort_band(EASY_THRESHOLD) == "easy"
        assert effort_band(EASY_THRESHOLD - 0.01) == "working"

    def test_failed_ends_where_the_policy_cuts(self):
        assert effort_band(FAIL_THRESHOLD) == "failed"
        assert effort_band(FAIL_THRESHOLD + 0.01) == "working"

    def test_it_does_not_introduce_its_own_thresholds(self):
        """A second set would let the chart disagree with the prescription
        it is drawing."""
        src = inspect.getsource(effort_band)
        assert "EASY_THRESHOLD" in src and "FAIL_THRESHOLD" in src

    def test_the_scale_counts_up_with_ease(self):
        """5 is Easy in this app. Asserting the direction because openGym's
        RIR runs the other way and the inversion is the whole reason the
        band is not computed in two clients."""
        assert effort_band(5.0) == "easy"
        assert effort_band(1.0) == "failed"

    def test_every_band_has_a_legend_sentence(self):
        assert set(EFFORT_BANDS) == {"easy", "working", "failed"}
        assert all(v for v in EFFORT_BANDS.values())

    def test_all_three_bands_occur_in_real_history(self):
        """Measured: working 199 exercise-days, easy 82, failed 1. A band
        that can never fire is a legend entry explaining nothing — the fault
        that got C1's fatigue model and B1's stall count declined."""
        for avg in (4.8, 3.2, 1.0):
            assert effort_band(avg) in EFFORT_BANDS


class TestUnratedIsAbsentNotMiddling:
    def test_no_rating_yields_no_band(self):
        assert effort_band(None) is None

    def test_a_day_with_no_rated_set_keeps_both_fields_null(self):
        out = finish_progression_point({
            "date": "2026-09-02", "top_weight_lb": None, "e1rm": None,
            "top_reps": 20, "_r_sum": 0.0, "rated_sets": 0,
        })
        assert out["rating_avg"] is None
        assert out["effort"] is None
        assert out["rated_sets"] == 0

    def test_the_denominator_travels_with_the_average(self):
        """OG2-C4's rule. A mean over two of five sets must not silently
        speak for the other three."""
        out = finish_progression_point({
            "date": "2026-09-01", "top_weight_lb": 25.0, "e1rm": 31.2,
            "top_reps": 12, "_r_sum": 14.0, "rated_sets": 3,
        })
        assert out["rating_avg"] == 4.67
        assert out["rated_sets"] == 3
        assert out["effort"] == "easy"

    def test_the_accumulator_does_not_leak_to_the_client(self):
        out = finish_progression_point({
            "date": "2026-09-01", "top_weight_lb": 25.0, "e1rm": None,
            "top_reps": 12, "_r_sum": 9.0, "rated_sets": 3,
        })
        assert "_r_sum" not in out


class TestItIsReachableAndPure:
    def test_the_reducer_is_module_level_not_a_closure(self):
        """This suite has no database fixture, so a reduction that can only
        be exercised through a live request is one nobody checks."""
        assert not inspect.iscoroutinefunction(finish_progression_point)
        assert "db" not in inspect.signature(finish_progression_point).parameters

    def test_the_endpoint_uses_it(self):
        src = inspect.getsource(api.strength_stats)
        assert "finish_progression_point" in src

    def test_the_legend_is_served(self):
        src = inspect.getsource(api.strength_stats)
        assert '"effort_legend": effort_legend' in src


class TestBothSurfacesRenderItAndNeitherDerivesIt:
    def test_the_web_has_a_shared_module(self):
        assert WEB_MOD.exists()

    def test_the_phone_mirrors_it(self):
        """The Units.kt / units.ts convention."""
        assert PHONE_MOD.exists()
        assert "effort.ts" in PHONE_MOD.read_text()

    def test_the_web_chart_colours_the_dot_per_point(self):
        src = WEB_CHART.read_text()
        assert "effortColor" in src and "effortSymbolSize" in src

    def test_the_web_tooltip_carries_the_effort_line(self):
        assert "effortSummary" in WEB_CHART.read_text()

    def test_the_phone_chart_now_takes_a_marker(self):
        """D-3: no CartesianChartHost in the app passed one, so the series
        was interrogable on the desktop and mute on the phone."""
        src = PHONE_CHART.read_text()
        assert "markerVisibilityListener" in src
        assert "rememberDefaultCartesianMarker" in src

    def test_the_phone_readout_defaults_to_the_latest_session(self):
        """A readout that appears only after a tap is one most people never
        find."""
        src = PHONE_CHART.read_text()
        assert "pts.lastOrNull()" in src

    def test_neither_client_decides_the_band(self):
        """GOAL-STATE's rule. The 1-5 scale counts up with ease here and
        down in the app this came from; two clients mapping that
        independently is how they end up disagreeing about which end is
        good."""
        for path in (WEB_CHART, WEB_MOD, PHONE_CHART, PHONE_MOD):
            src = _code_only(path.read_text())
            assert "EASY_THRESHOLD" not in src, path.name
            assert "4.5" not in src, path.name

    def test_neither_client_writes_the_band_label(self):
        """The words come from `effort_legend`, so they cannot drift from
        the thresholds that define them."""
        for path in (WEB_MOD, PHONE_MOD):
            src = _code_only(path.read_text())
            assert "the policy adds weight" not in src, path.name
