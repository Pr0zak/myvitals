"""The workouts-list heart-rate aggregate must stay bounded — v0.8.1.

TD-4 set out to remove an N+1: `list_workouts` issued one heart-rate
aggregate per workout in the page. The replacement was worse than the problem.
It took the earliest start and latest end across the whole page and pulled
EVERY heart-rate sample in that span into Python to bucket by hand — so
summarising five workouts spread over a fortnight meant loading a fortnight
of per-second heart rate to compute five averages.

The effect in production: `/workout/strength/workouts?limit=5` took 5.5
seconds to return 1.6 KB, and `limit=200` took 17 seconds. Slow enough that
concurrent screen loads on the phone tripped OkHttp's read timeout, the
status interceptor marked the backend UNREACHABLE, and the app showed
"Can't reach server" while the server was in fact answering every request
with a 200.

The lesson is narrow and worth keeping: a session window is a few thousand
samples, the span between the first and last session in a page is not, and
"one query" is only an optimisation if the database is still doing the
aggregation.
"""

from __future__ import annotations

import inspect
import re

from myvitals.api.workout import strength


def _list_workouts_source() -> str:
    return inspect.getsource(strength.list_workouts)


def test_heart_rate_is_aggregated_in_sql_not_in_python():
    """The database must reduce the samples, not hand them over.

    `func.avg` / `func.max` in the statement is the whole point: without
    them the query returns every row in the range.
    """
    src = _list_workouts_source()
    assert "func.avg(models.HeartRate.bpm)" in src
    assert "func.max(models.HeartRate.bpm)" in src


def test_the_query_is_bounded_to_session_windows():
    """Each workout's own window, joined as a VALUES list — not one range
    covering the whole page."""
    src = _list_workouts_source()
    assert "sa_values(" in src, "windows must be joined, not collapsed to a span"
    assert "win.c.w_start" in src and "win.c.w_end" in src
    assert "group_by(win.c.wid)" in src


def test_no_unaggregated_sample_select_survives():
    """The exact shape of the regression: selecting raw (time, bpm) rows in
    this handler means the page span is being materialised again."""
    src = _list_workouts_source()
    offending = re.search(
        r"select\(\s*models\.HeartRate\.time\s*,\s*models\.HeartRate\.bpm", src,
    )
    assert not offending, (
        "list_workouts is selecting raw heart-rate samples again. A page can "
        "span months; aggregate per session window in SQL instead."
    )


def test_no_span_collapse_across_the_page():
    """min(start) / max(end) across every workout is how the span got built."""
    src = _list_workouts_source()
    assert "span_start" not in src and "span_end" not in src, (
        "the page-wide span scan is back — see this module's docstring"
    )
