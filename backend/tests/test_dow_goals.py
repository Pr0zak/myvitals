"""Day-of-week step goals (DOW-1).

A single step goal treats every day the same, which does not match how
anyone actually moves. The design choice worth pinning is that overrides
are SPARSE: only days that differ need an entry, so the existing scalar
keeps working and a user who sets a weekend figure need not restate the
other five.
"""

from __future__ import annotations

from datetime import date

import pytest

from myvitals.analytics import tiles


MONDAY = date(2026, 8, 17)
SATURDAY = date(2026, 8, 22)


class TestFallback:
    def test_no_schedule_uses_the_base_goal(self):
        assert tiles.resolve_steps_goal({"steps_goal": 12000}, MONDAY) == 12000

    def test_no_goal_at_all_uses_the_default(self):
        assert tiles.resolve_steps_goal({}, MONDAY) == tiles.DEFAULT_STEPS_GOAL

    def test_a_day_absent_from_the_schedule_uses_the_base(self):
        """Sparse by design — setting Saturday must not zero the rest."""
        extra = {"steps_goal": 10000, "steps_goal_schedule": {"sat": 6000}}
        assert tiles.resolve_steps_goal(extra, MONDAY) == 10000
        assert tiles.resolve_steps_goal(extra, SATURDAY) == 6000

    def test_none_extra_is_safe(self):
        assert tiles.resolve_steps_goal(None, MONDAY) == tiles.DEFAULT_STEPS_GOAL


class TestBadInput:
    @pytest.mark.parametrize("bad", [0, -100])
    def test_non_positive_overrides_are_ignored(self, bad):
        """A zero goal is always met and a negative one never reachable;
        neither is something a user means, so fall back rather than
        rendering a tile that cannot behave."""
        extra = {"steps_goal": 10000, "steps_goal_schedule": {"mon": bad}}
        assert tiles.resolve_steps_goal(extra, MONDAY) == 10000

    @pytest.mark.parametrize("bad", ["abc", None, {}, []])
    def test_unparseable_overrides_fall_back(self, bad):
        extra = {"steps_goal": 10000, "steps_goal_schedule": {"mon": bad}}
        assert tiles.resolve_steps_goal(extra, MONDAY) == 10000

    def test_a_non_dict_schedule_falls_back(self):
        extra = {"steps_goal": 9000, "steps_goal_schedule": "weekends off"}
        assert tiles.resolve_steps_goal(extra, MONDAY) == 9000

    def test_unparseable_base_falls_back_to_the_default(self):
        assert tiles.resolve_steps_goal(
            {"steps_goal": "lots"}, MONDAY,
        ) == tiles.DEFAULT_STEPS_GOAL


class TestWeekdayKeys:
    def test_seven_keys_starting_monday(self):
        assert len(tiles.WEEKDAY_KEYS) == 7
        assert tiles.WEEKDAY_KEYS[0] == "mon"

    def test_keys_match_python_weekday_ordering(self):
        """resolve_steps_goal indexes with date.weekday(), where Monday is
        0 — an off-by-one here shifts every override by a day, which would
        look like the feature simply not working."""
        for i, key in enumerate(tiles.WEEKDAY_KEYS):
            d = date(2026, 8, 17)  # a Monday
            probe = date.fromordinal(d.toordinal() + i)
            assert probe.weekday() == i
            extra = {"steps_goal": 1, "steps_goal_schedule": {key: 5000}}
            assert tiles.resolve_steps_goal(extra, probe) == 5000


class TestScopeOfTheFeature:
    def test_the_ai_goal_target_is_not_made_to_vary(self):
        """A long-run goal tracks progress toward ONE number. Making its
        target vary by weekday would make its progress percentage mean
        something different on a Tuesday than a Sunday."""
        import inspect
        src = inspect.getsource(tiles.resolve_steps_goal)
        assert "AiGoal" in src, "the boundary belongs next to the code"
