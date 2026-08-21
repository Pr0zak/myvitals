"""Unified day snapshot (DAY-1).

The day-parameterised twin of /summary/today/snapshot. What matters here
is what it deliberately does NOT do for a day that is not today.
"""

from __future__ import annotations

import inspect

from myvitals.api import summary


class TestDayScoping:
    def test_resolves_the_day_in_local_time(self):
        """Not `datetime.now(timezone.utc).date()`.

        The container runs TZ=UTC while the user is Central, so a
        UTC-derived day rolls at 7pm and the endpoint starts answering for
        tomorrow. This app has shipped that exact bug four times.
        """
        src = inspect.getsource(summary.day_snapshot)
        assert "resolve_day(date_)" in src
        assert "datetime.now(timezone.utc).date()" not in src

    def test_does_not_repair_a_stale_row_for_a_past_day(self):
        """`_ensure_fresh_today_row` recomputes from TODAY's samples.

        Running it while looking at last Tuesday would rewrite that day's
        stored summary using data from now.
        """
        src = inspect.getsource(summary.day_snapshot)
        assert "_ensure_fresh_today_row" not in src

    def test_does_not_splice_live_steps(self):
        """Live step counts are only meaningful for the current day."""
        src = inspect.getsource(summary.day_snapshot)
        assert "live_steps_today" not in src

    def test_reports_whether_the_day_is_today(self):
        """The clients tint their chrome off this."""
        src = inspect.getsource(summary.day_snapshot)
        assert '"is_today"' in src


class TestFailureIsolation:
    def test_each_section_is_wrapped(self):
        """One broken subsystem must not take down the page.

        An expired Strava token should cost you the activities card, not
        the whole day.
        """
        src = inspect.getsource(summary.day_snapshot)
        assert "async def safe(" in src
        assert "asyncio.gather(" in src

    def test_a_failed_section_lands_as_none_not_an_exception(self):
        src = inspect.getsource(summary.day_snapshot)
        assert "return name, None" in src

    def test_each_section_gets_its_own_session(self):
        """SQLAlchemy AsyncSession cannot run concurrent operations.

        Sharing the request session across gathered coroutines raises at
        runtime under exactly the concurrency this endpoint exists to use.
        """
        src = inspect.getsource(summary.day_snapshot)
        assert "async with SessionLocal() as own_db" in src


class TestWindows:
    def test_sleep_window_opens_the_previous_evening(self):
        """"Tuesday's sleep" means Monday night into Tuesday morning.

        Bounding sleep to Tuesday 00:00-23:59 would report the nap you
        took Tuesday afternoon as the night's sleep.
        """
        src = inspect.getsource(summary.day_snapshot)
        assert "day_start - _td(days=1)" in src

    def test_activities_are_bounded_on_start_not_overlap(self):
        """An activity beginning 23:40 belongs to the day it started.

        Counting it on both days would double it in any per-day total.
        """
        src = inspect.getsource(summary._day_activities)
        assert "Activity.start_at >= day_start" in src
        assert "Activity.start_at <= day_end" in src
        assert "end_at" not in src

    def test_workout_lookup_excludes_regenerated_plans(self):
        """A regenerated plan is superseded, not a second session."""
        src = inspect.getsource(summary._day_workout)
        assert "regenerated" in src
