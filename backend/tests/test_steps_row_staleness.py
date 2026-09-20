"""`daily_summary.steps_total` must not freeze at a partial count — SA-L1.

The lazy recompute asked two questions: is sleep missing, is HRV missing.
Both are overnight metrics that land once and then the row is finished, so
once they have landed neither branch ever fires again. Steps are not like
that — they accumulate all day — so a row written at 00:05, or by the
startup job, kept whatever count existed at that instant for good. 32 of the
last 100 stored days were short, one of them by 17,733 steps, and every
surface except the Steps detail screen reads the stored column: the hero
ring, Trends, the Steps tile's own sparkline, Compare, the CSV export, the
MCP tools and the AI coach payloads.

Two things had to be true before a staleness test could be added at all, and
both are pinned here:

* The recount has to be DETERMINISTIC. On 50 of the last 100 days both
  `com.fitbit.FitbitMobile` and Google Health write steps, disagreeing by
  ~5,000 on average, and the picker chose with a `next(...)` over an
  unordered GROUP BY — so "canonical" meant whichever row postgres returned
  first. A staleness test against a number that changes on every recount
  never settles.
* The comparison has to have a TOLERANCE. Steps arrive all day; an exact
  test would rebuild the whole daily_summary row on every page load while
  the user is out walking.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from myvitals.analytics import tiles
from myvitals.analytics.jobs import (
    STEPS_STALE_TOLERANCE,
    _pick_steps_source,
    canonical_steps_by_day,
    canonical_steps_total,
    steps_total_is_stale,
)

WATCH = "com.fitbit.FitbitMobile"
GOOGLE = "com.google.android.apps.healthdata"
PHONE = "android"


# ── fakes ────────────────────────────────────────────────────────────────

class _Result:
    """One `db.execute(...)` return, consumed as `.all()` or `.scalar()`."""

    def __init__(self, rows: list | None = None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _FakeDb:
    """Hands back queued results in order. The queries under test are fixed
    in number and sequence, so ordering is enough to stand in for them."""

    def __init__(self, *results: _Result):
        self._queue = list(results)

    async def execute(self, _stmt):
        assert self._queue, "more queries were issued than the test queued"
        return self._queue.pop(0)


def _saved(**kw):
    """A daily_summary row. Sleep and HRV present by default — that is the
    state in which the old predicate went permanently blind."""
    return SimpleNamespace(
        **{"steps_total": None, "sleep_duration_s": 28200,
           "hrv_avg": 23.81, **kw})


DAY = date(2026, 9, 6)
START = datetime(2026, 9, 6, 5, tzinfo=timezone.utc)
END = datetime(2026, 9, 7, 4, 59, 59, tzinfo=timezone.utc)


# ── the picker is deterministic ──────────────────────────────────────────

def test_the_same_day_picks_the_same_source_whatever_order_it_arrives_in():
    """The GROUP BY has no ORDER BY, so both orderings are things postgres
    really returns for the same day."""
    forward = [(WATCH, 10846), (GOOGLE, 23089)]
    assert _pick_steps_source(forward) == _pick_steps_source(forward[::-1])


def test_two_watch_writers_resolve_to_the_fuller_one():
    """Mid-rebrand both packages write. The partial one is the writer being
    left behind, and picking it is how a day reads as 10,846 instead of
    23,089."""
    assert _pick_steps_source([(WATCH, 10846), (GOOGLE, 23089)]) == GOOGLE


def test_a_watch_still_beats_a_bigger_phone_count():
    """The phone pedometer over-counts in a pocket; the rule that the wrist
    wins is older than this fix and must survive it."""
    assert _pick_steps_source([(PHONE, 30000), (WATCH, 17855)]) == WATCH


def test_no_watch_falls_back_to_the_largest_source():
    assert _pick_steps_source([(PHONE, 9000), ("other", 4000)]) == PHONE


def test_an_exact_tie_is_broken_by_name_not_by_luck():
    tied = [("b-source", 5000), ("a-source", 5000)]
    assert _pick_steps_source(tied) == "a-source"
    assert _pick_steps_source(tied[::-1]) == "a-source"


def test_no_sources_means_no_answer():
    assert _pick_steps_source([]) is None


async def test_canonical_steps_by_day_is_order_independent_too():
    """The batched scan reads per-day rows in whatever order the GROUP BY
    emits them, and must reach the same number as the single-day path."""
    rows = [
        (DAY, WATCH, 10846),
        (DAY, GOOGLE, 23089),
        (date(2026, 9, 7), WATCH, 6745),
    ]
    a = await canonical_steps_by_day(_FakeDb(_Result(rows)), START, END, "UTC")
    b = await canonical_steps_by_day(
        _FakeDb(_Result(rows[::-1])), START, END, "UTC")
    assert a == b == {DAY: 23089, date(2026, 9, 7): 6745}


# ── the staleness rule ───────────────────────────────────────────────────

def test_a_frozen_partial_count_is_stale():
    """2026-09-06: the row said 122, the raw samples said 17,855."""
    assert steps_total_is_stale(122, 17855) is True


def test_a_row_that_never_got_a_step_count_is_stale():
    """Startup wrote the row before any steps existed, or wrote it for a day
    that had not started. Either way the null must not be permanent."""
    assert steps_total_is_stale(None, 9881) is True


def test_a_recount_that_agrees_is_not_stale():
    assert steps_total_is_stale(17855, 17855) is False


def test_a_few_steps_of_drift_does_not_trigger_a_rebuild():
    """Steps land all day. Rebuilding the row for every handful of them
    would mean recomputing readiness, training load and the alert scan on
    every page load."""
    assert steps_total_is_stale(17855, 17855 + STEPS_STALE_TOLERANCE) is False


def test_drift_past_the_tolerance_does_trigger_one():
    assert steps_total_is_stale(17855, 17855 + STEPS_STALE_TOLERANCE + 1) is True


def test_a_day_with_no_usable_source_is_never_stale():
    """There is nothing to repair the row with, so marking it stale would
    recompute the same day on every single read, forever."""
    assert steps_total_is_stale(None, None) is False
    assert steps_total_is_stale(None, 0) is False


# ── the single-day predicate uses it ─────────────────────────────────────

async def _is_stale(saved, *results):
    from myvitals.api.summary import _today_row_is_stale

    return await _today_row_is_stale(_FakeDb(*results), saved, DAY, START, END)


async def test_today_row_with_sleep_and_hrv_is_still_checked_for_steps():
    """The exact state of every offending day: sleep and HRV present, so the
    two old branches short-circuit and the row can never repair itself."""
    stale = await _is_stale(
        _saved(steps_total=122),
        _Result(rows=[(GOOGLE, 23089)]),   # pick_canonical_steps_source
        _Result(scalar=17855),             # per-minute MAX recount
    )
    assert stale is True


async def test_today_row_matching_the_recount_is_left_alone():
    stale = await _is_stale(
        _saved(steps_total=17855),
        _Result(rows=[(GOOGLE, 23089)]),
        _Result(scalar=17855),
    )
    assert stale is False


async def test_a_day_with_steps_but_no_overnight_data_gets_a_row():
    """2026-09-16 had raw steps, no sleep and no HRV, and so produced no row
    at all — the day simply vanished from every chart."""
    stale = await _is_stale(
        None,
        _Result(scalar=0),                 # sleep_stages count
        _Result(scalar=0),                 # vitals_hrv count
        _Result(rows=[(WATCH, 1864)]),
        _Result(scalar=1864),
    )
    assert stale is True


async def test_a_day_with_nothing_at_all_stays_absent():
    """No sleep, no HRV, no steps — there is no row to write, and the scan
    must not loop trying to write one."""
    stale = await _is_stale(
        None,
        _Result(scalar=0),
        _Result(scalar=0),
        _Result(rows=[]),                  # no source covered the day
    )
    assert stale is False


async def test_the_recount_is_the_number_the_write_path_stores():
    """`canonical_steps_total` is shared by the write and the check. If they
    computed steps separately the row would be judged stale immediately
    after being repaired."""
    total = await canonical_steps_total(
        _FakeDb(_Result(rows=[(WATCH, 10846), (GOOGLE, 23089)]),
                _Result(scalar=17855)),
        START, END,
    )
    assert total == 17855
    assert "canonical_steps_total" in inspect.getsource(
        __import__("myvitals.analytics.jobs", fromlist=["compute_daily_summary"])
        .compute_daily_summary)


async def test_a_source_that_recorded_zero_is_zero_not_missing():
    """A day the user genuinely did not walk is data. It used to be coerced
    to null by `int(...) or None`, which reads as "no watch" rather than
    "no steps"."""
    total = await canonical_steps_total(
        _FakeDb(_Result(rows=[(WATCH, 0)]), _Result(scalar=0)), START, END)
    assert total == 0


async def test_no_source_at_all_is_still_none():
    total = await canonical_steps_total(_FakeDb(_Result(rows=[])), START, END)
    assert total is None


# ── the batched scan applies the same rule ───────────────────────────────

def test_the_range_scan_shares_the_single_day_rule():
    """Two copies of "is this row stale" drifting apart is how /summary/range
    and /summary/today would start disagreeing about the same date."""
    from myvitals.api import summary

    src = inspect.getsource(summary.summary_range)
    assert "steps_total_is_stale" in src
    assert "canonical_steps_by_day" in src


# ── the tile sparkline no longer contradicts its own headline ────────────

class _SeriesDb:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _Result(rows=self._rows)


STORED = [
    (date(2026, 9, 15), 594),
    (date(2026, 9, 17), 1051),
]


async def test_the_last_bar_follows_the_live_headline():
    """The card showed 1,324 above a sparkline whose last bar was the stored
    1,051 — one card disagreeing with itself. The headline was already
    spliced live via `steps_override`; the series was not."""
    series = await tiles._series(
        _SeriesDb(STORED), None, date(2026, 9, 17), 3, override=1324)
    assert series[-1] == {"date": "2026-09-17", "value": 1324}


async def test_without_an_override_the_stored_value_still_shows():
    series = await tiles._series(
        _SeriesDb(STORED), None, date(2026, 9, 17), 3)
    assert series[-1] == {"date": "2026-09-17", "value": 1051}


async def test_an_override_does_not_reach_back_over_earlier_days():
    """Only today's point is live. Painting this minute's count onto last
    Tuesday would be a fabrication."""
    series = await tiles._series(
        _SeriesDb(STORED), None, date(2026, 9, 17), 3, override=1324)
    assert [p["value"] for p in series] == [594, None, 1324]


async def test_a_gap_is_still_a_gap():
    """Missing days stay null — the override must not close the hole in the
    middle of the sparkline."""
    series = await tiles._series(
        _SeriesDb(STORED), None, date(2026, 9, 17), 3, override=1324)
    assert series[1]["value"] is None


def test_the_steps_tile_passes_the_live_count_to_its_series():
    """The wiring, not just the capability. `steps_override` reaching the
    headline and not the series is the whole bug, and the weekly hero ring
    on /summary/tiles is summed from this series so it inherits either
    way."""
    tree = ast.parse(Path(tiles.__file__).read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "add"):
            continue
        keys = {kw.arg: kw.value for kw in node.keywords}
        key = keys.get("key")
        if not (isinstance(key, ast.Constant) and key.value == "steps"):
            continue
        series = keys.get("series")
        assert isinstance(series, ast.Await), "series is built by an await"
        call = series.value
        assert any(
            kw.arg == "override" and getattr(kw.value, "id", "") == "steps_override"
            for kw in call.keywords
        ), 'the steps tile builds its series without override=steps_override'
        return
    raise AssertionError('no add(key="steps", ...) call found in tiles.py')
