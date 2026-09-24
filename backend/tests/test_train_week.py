"""UI-1 — the Train tab's week-vs-last-week block and the hero's next slot.

The phone used to sum `/stats.daily` itself and pick the delta's colour with
a hard-coded `up -> lime`; the web never showed the figure. Both now render
`/stats.week` verbatim, so these tests pin what that block means.
"""
from __future__ import annotations

import inspect
from datetime import date, timedelta

from myvitals.analytics import train_week
from myvitals.analytics.train_week import next_up, week_volume

TODAY = date(2026, 3, 11)  # a Wednesday — the midweek case the window exists for


def _d(n: int) -> date:
    return TODAY - timedelta(days=n)


class TestWindow:
    def test_seven_local_days_ending_today_oldest_first(self):
        w = week_volume({}, {}, TODAY)
        assert [r["date"] for r in w["days"]] == [_d(i).isoformat() for i in range(6, -1, -1)]
        assert w["start"] == _d(6).isoformat()
        assert w["end"] == TODAY.isoformat()

    def test_each_ghost_is_the_same_weekday_a_week_earlier(self):
        w = week_volume({}, {}, TODAY)
        for r in w["days"]:
            d = date.fromisoformat(r["date"])
            p = date.fromisoformat(r["prev_date"])
            assert d - p == timedelta(days=7)
            assert d.weekday() == p.weekday()

    def test_trailing_not_calendar_week(self):
        """Midweek, a Monday-anchored week would compare three days against
        seven and report a fall that is only the calendar."""
        vol = {_d(i): 1000.0 for i in range(14)}
        w = week_volume(vol, {}, TODAY)
        assert w["total_lb"] == w["prev_total_lb"] == 7000.0
        assert w["direction"] == "flat"


class TestTotalsAndDelta:
    def test_totals_and_percentage(self):
        vol = {_d(0): 3000.0, _d(2): 2000.0, _d(7): 2500.0, _d(9): 1500.0}
        w = week_volume(vol, {_d(0): 12}, TODAY)
        assert w["total_lb"] == 5000.0
        assert w["prev_total_lb"] == 4000.0
        assert w["delta_pct"] == 25.0
        assert w["days"][-1]["volume_lb"] == 3000.0
        assert w["days"][-1]["sets"] == 12
        assert w["days"][-1]["prev_volume_lb"] == 2500.0

    def test_better_is_decided_on_the_server(self):
        up = week_volume({_d(0): 5000.0, _d(7): 4000.0}, {}, TODAY)
        down = week_volume({_d(0): 3000.0, _d(7): 4000.0}, {}, TODAY)
        assert up["better"] == down["better"] == "higher"
        assert up["direction"] == "improved"
        assert down["direction"] == "worse"

    def test_noise_reads_flat(self):
        w = week_volume({_d(0): 4040.0, _d(7): 4000.0}, {}, TODAY)
        assert w["direction"] == "flat"

    def test_no_previous_week_is_no_comparison_not_plus_100(self):
        w = week_volume({_d(0): 4000.0}, {}, TODAY)
        assert w["delta_pct"] is None
        assert w["direction"] is None

    def test_rows_outside_both_windows_are_ignored(self):
        w = week_volume({_d(14): 9999.0, TODAY + timedelta(days=1): 9999.0}, {}, TODAY)
        assert w["total_lb"] == 0.0 and w["prev_total_lb"] == 0.0

    def test_unweighted_sets_are_reported_not_costed(self):
        w = week_volume({}, {_d(1): 5}, TODAY, unweighted_sets_this_week=5)
        assert w["unweighted_sets"] == 5
        assert w["total_lb"] == 0.0


class TestStatsEndpointWiring:
    def test_stats_emits_the_week_block_from_the_local_day(self):
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api.strength_stats)
        assert '"week": train_week.week_volume(' in src
        assert "today_local = _local_today()" in src
        # The fetch must cover both windows even when `days` is small.
        assert "fetch_since = min(since, week_since)" in src


def _ex(order, target, accounted, done, name=None):
    return {
        "exercise_id": f"ex{order}", "name": name or f"Exercise {order}",
        "order_index": order, "target_sets": target,
        "accounted_sets": accounted, "done": done,
    }


class TestNextUp:
    def test_first_unfinished_slot_by_order(self):
        n = next_up([_ex(2, 3, 0, False), _ex(0, 3, 3, True), _ex(1, 4, 2, False)])
        assert n["exercise_id"] == "ex1"
        assert n["set_number"] == 3
        assert n["started"] is True

    def test_nothing_logged_is_not_started(self):
        n = next_up([_ex(0, 3, 0, False), _ex(1, 3, 0, False)])
        assert n["set_number"] == 1
        assert n["started"] is False

    def test_all_done_is_none(self):
        assert next_up([_ex(0, 3, 3, True)]) is None

    def test_finished_session_names_no_next_slot(self):
        from myvitals.api.workout.strength import _next_up

        assert _next_up("completed", []) is None
        assert _next_up("skipped", []) is None

    def test_uses_the_counter_predicates(self):
        from myvitals.api.workout import strength as api

        src = inspect.getsource(api._next_up)
        assert "_accounted_sets(e)" in src and "_exercise_done(e)" in src


def test_window_constant():
    assert train_week.WINDOW_DAYS == 7
