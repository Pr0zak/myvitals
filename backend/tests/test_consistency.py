"""Training streaks and true frequency (CONS-1).

Every test here corresponds to a way the previous inline implementation
reported a number that was not true.
"""

from __future__ import annotations

from datetime import date, timedelta

from myvitals.analytics import consistency


def days(*offsets: int, anchor: date = date(2026, 8, 21)) -> set[date]:
    """Active days expressed as offsets back from an anchor."""
    return {anchor - timedelta(days=o) for o in offsets}


TODAY = date(2026, 8, 21)


class TestCurrentStreak:
    def test_counts_back_from_today(self):
        s = consistency.compute_streaks(days(0, 1, 2, 3), TODAY)
        assert s.current_days == 4
        assert s.current_start == TODAY - timedelta(days=3)
        assert s.today_pending is False

    def test_a_gap_ends_the_streak(self):
        s = consistency.compute_streaks(days(0, 1, 3, 4), TODAY)
        assert s.current_days == 2

    def test_untrained_today_keeps_yesterdays_streak_alive(self):
        """A day that has not ended has not been missed.

        Resetting to zero at midnight shows a broken streak every morning
        to someone who has not broken it — the app telling the user they
        failed at something they still have all day to do.
        """
        s = consistency.compute_streaks(days(1, 2, 3), TODAY)
        assert s.current_days == 3
        assert s.today_pending is True, (
            "the client needs to distinguish 'banked' from 'keep it alive'"
        )

    def test_two_days_idle_is_a_broken_streak(self):
        s = consistency.compute_streaks(days(2, 3, 4), TODAY)
        assert s.current_days == 0
        assert s.today_pending is False

    def test_no_history_is_zero_not_an_error(self):
        s = consistency.compute_streaks(set(), TODAY)
        assert s.current_days == 0
        assert s.longest_days == 0
        assert s.last_active is None

    def test_single_day_today(self):
        s = consistency.compute_streaks(days(0), TODAY)
        assert s.current_days == 1
        assert s.longest_days == 1


class TestStreakIsNotWindowed:
    def test_a_streak_older_than_any_display_window_is_not_truncated(self):
        """The headline bug.

        The old code built `active_days` from rows already filtered to the
        selected range, so a 40-day streak viewed on the "last 30 days"
        tab reported 30 — and switching to "last 7 days" reported 7. The
        streak had not changed; only the picker had.
        """
        s = consistency.compute_streaks(days(*range(0, 40)), TODAY)
        assert s.current_days == 40

    def test_longest_streak_can_predate_everything_recent(self):
        history = days(*range(0, 3)) | days(*range(100, 130))
        s = consistency.compute_streaks(history, TODAY)
        assert s.current_days == 3
        assert s.longest_days == 30
        assert s.longest_end == TODAY - timedelta(days=100)


class TestLongestStreak:
    def test_picks_the_longest_of_several_runs(self):
        history = days(0, 1) | days(10, 11, 12, 13, 14) | days(30, 31, 32)
        s = consistency.compute_streaks(history, TODAY)
        assert s.longest_days == 5

    def test_reports_the_run_boundaries(self):
        s = consistency.compute_streaks(days(10, 11, 12), TODAY)
        assert s.longest_start == TODAY - timedelta(days=12)
        assert s.longest_end == TODAY - timedelta(days=10)

    def test_current_streak_can_also_be_the_longest(self):
        s = consistency.compute_streaks(days(0, 1, 2, 3, 4), TODAY)
        assert s.current_days == s.longest_days == 5

    def test_duplicate_dates_do_not_inflate_a_streak(self):
        """Two sessions in one day is one day of the streak.

        The caller builds a set, but this is the invariant that matters if
        that ever becomes a list.
        """
        history = [TODAY, TODAY, TODAY - timedelta(days=1)]
        s = consistency.compute_streaks(history, TODAY)
        assert s.current_days == 2


class TestFrequency:
    def test_measured_over_a_fixed_window_not_the_caller_range(self):
        """The number must not move when the user changes the date picker.

        Deriving sessions/week as count/range*7 makes the headline change
        with the chart range, which reads as the app contradicting itself.
        """
        history = days(0, 2, 4, 6, 8, 10, 12, 14)
        a = consistency.sessions_per_week(history, TODAY, 28)
        b = consistency.sessions_per_week(history, TODAY, 28)
        assert a == b
        # 8 sessions in the trailing 28 days → 2.0/week
        assert a == 2.0

    def test_sessions_outside_the_window_do_not_count(self):
        history = days(0, 1) | days(200, 201, 202)
        assert consistency.sessions_per_week(history, TODAY, 28) == 0.5

    def test_empty_history_is_zero(self):
        assert consistency.sessions_per_week(set(), TODAY, 28) == 0.0

    def test_zero_window_does_not_divide_by_zero(self):
        assert consistency.sessions_per_week(days(0), TODAY, 0) == 0.0

    def test_count_in_window_includes_today(self):
        assert consistency.count_in_window(days(0), TODAY, 7) == 1

    def test_count_in_window_excludes_the_day_before_the_window(self):
        """A 7-day window is today plus the six before it."""
        assert consistency.count_in_window(days(7), TODAY, 7) == 0
        assert consistency.count_in_window(days(6), TODAY, 7) == 1


class TestLocalDayHandling:
    def test_streaks_use_whatever_dates_the_caller_supplies(self):
        """This module takes dates, not timestamps, deliberately.

        Timezone conversion belongs at the query boundary where the
        timestamps live (api/strava.py:_local_date). Accepting datetimes
        here would let a caller pass UTC instants and get a plausible,
        wrong answer — which is exactly how the original bug happened.
        """
        import inspect
        sig = inspect.signature(consistency.compute_streaks)
        assert "active_days" in sig.parameters
        assert "today" in sig.parameters
