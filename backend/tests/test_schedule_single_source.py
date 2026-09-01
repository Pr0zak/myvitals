"""Which days you train has one answer — OG2-A4.

There were FOUR copies of the Mon-first weekday table:

* ``analytics/strength.py:_STRENGTH_WEEKDAYS_BY_COUNT`` — the generator's,
  and the only one that decides what actually gets made.
* ``api/workout/strength.py`` — the ``/upcoming`` forecast's, introduced with
  the comment "Mon-first weekday pattern matching the web/Android strip".
* ``frontend/src/views/workout/StrengthToday.vue`` — the web week strip's.
* ``android/.../StrengthTodayScreen.kt`` — the phone week strip's.

The three on the read side matched each other and disagreed with the
generator. At ``days_per_week=2`` they said Mon/Thu; the generator says
Mon/Fri. So every surface that told the user when they would next train
agreed with the other surfaces and was wrong.

The comment is the tell. It records the copy being made deliberately, to
match the strips — the strips being the thing that should have been reading
from it.

A second fault the local tables could not even express: they knew only
"training day or not". Cardio and yoga days were skipped entirely, so at this
user's 6 strength + 2 cardio days the Sunday cardio session was invisible in
the week ahead. Only genuine rest days are omitted now.

All three read-side copies are gone. The endpoint calls ``schedule_day_type``
— the same function ``generate_plan`` consults — and both clients render the
dates it returns instead of deriving their own.
"""

from __future__ import annotations

import inspect
import pathlib
import re

from myvitals.analytics.strength import (
    _STRENGTH_WEEKDAYS_BY_COUNT,
    schedule_day_type,
)
from myvitals.api.workout import strength as api

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB_STRIP = REPO / "frontend" / "src" / "views" / "workout" / "StrengthToday.vue"
PHONE_STRIP = (
    REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
    / "ui" / "strength" / "StrengthTodayScreen.kt"
)


class TestTheForecastAsksTheGenerator:
    def test_upcoming_calls_schedule_day_type(self):
        src = inspect.getsource(api.upcoming_workouts)
        assert "schedule_day_type" in src

    def test_upcoming_has_no_weekday_table_of_its_own(self):
        """The specific regression: a local table cannot disagree if it is
        not there. Reintroducing one is the failure this guards."""
        src = inspect.getsource(api.upcoming_workouts)
        assert "PATTERN" not in src
        assert "workout_dows" not in src

    def test_the_generator_and_the_forecast_agree_at_every_dpw(self):
        """Walk a fortnight at each supported days_per_week.

        Asserting agreement rather than a specific calendar: the point is
        that one function answers, not that Monday is special. At
        days_per_week=2 this is the case that used to differ — Thursday
        against Friday.
        """
        from datetime import date, timedelta

        base = date(2026, 8, 31)  # a Monday
        for dpw, expected in _STRENGTH_WEEKDAYS_BY_COUNT.items():
            for offset in range(14):
                d = base + timedelta(days=offset)
                is_strength = schedule_day_type(d, dpw, 0) == "strength"
                assert is_strength == (d.weekday() in expected), (
                    f"dpw={dpw} disagrees on {d} ({d.strftime('%a')})"
                )

    def test_two_days_a_week_is_monday_and_friday(self):
        """Pinned explicitly because this is the value that diverged.

        The read-side copies said {0, 3}. The generator says {0, 4}, and the
        generator is what builds the plan.
        """
        assert _STRENGTH_WEEKDAYS_BY_COUNT[2] == {0, 4}


class TestNonStrengthDaysAreVisible:
    def test_cardio_and_yoga_days_are_emitted(self):
        """They were skipped, so the week ahead looked emptier than it was."""
        src = inspect.getsource(api.upcoming_workouts)
        assert 'day_type == "rest"' in src, (
            "only rest should be omitted from the forecast"
        )
        assert 'day_type != "strength"' in src, (
            "a cardio or yoga day must still be emitted"
        )

    def test_a_non_strength_day_does_not_advance_the_rotation(self):
        """A ride is not a push day.

        Letting cardio advance `cursor_split` would walk the strength
        rotation forward on days no strength was done — the same class of bug
        the yoga filter on `last_done` was added to fix.
        """
        src = inspect.getsource(api.upcoming_workouts)
        head = src[src.index('day_type != "strength"'):]
        head = head[:head.index("continue")]
        # Strip comments — the branch explains itself at length, and naming
        # the variables in prose is not assigning to them.
        code = "\n".join(
            line for line in head.splitlines()
            if not line.strip().startswith("#")
        )
        assert "cursor_split =" not in code
        assert "last_done =" not in code

    def test_the_spacing_shift_also_uses_the_shared_schedule(self):
        """It tested the local table too, so it moved a day onto a date the
        generator might not consider a training day at all."""
        src = inspect.getsource(api.upcoming_workouts)
        shift = src[src.index("shifted = d + _td(days=1)"):]
        shift = shift[:shift.index("# else:")]
        assert "schedule_day_type" in shift


class TestNoClientDerivesTheSchedule:
    """Server is the source of truth, enforced by reading the clients.

    This is the rule CLAUDE.md states outright — any number a user sees is
    computed server-side and rendered verbatim — and the week strip was
    quietly breaking it on both surfaces at once.
    """

    def test_the_web_strip_has_no_weekday_table(self):
        src = WEB_STRIP.read_text()
        assert "projectedDates" in src, "the web strip should read the server's dates"
        assert not re.search(r"2:\s*\[0,\s*3\]", src), (
            "the web strip's local weekday table is back"
        )

    def test_the_phone_strip_has_no_weekday_table(self):
        src = PHONE_STRIP.read_text()
        assert "projectedDates" in src, "the phone strip should read the server's dates"
        assert not re.search(r"2\s*->\s*setOf\(0,\s*3\)", src), (
            "the phone strip's local weekday table is back"
        )

    def test_both_strips_changed_together(self):
        """Parity is enforced, and this is a paired surface.

        Fixing one strip and not the other would leave the two clients
        disagreeing about the same week, which is the failure the parity gate
        exists to catch.
        """
        for path in (WEB_STRIP, PHONE_STRIP):
            assert "projectedDates" in path.read_text(), f"{path.name} not updated"
