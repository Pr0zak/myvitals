"""`/summary/range` must not re-flag the same day as stale forever — SA-N2.

`compute_daily_summary` attributes a night to the day it ENDS
(`_stages_for_night` / the HRV night window, both windowed by a function of
this shape), but the staleness scan used to ask "what is this raw sample's
OWN local calendar date" instead. For every evening sample those two
disagree by one day: the write always lands on D+1 while the scan kept
flagging D — a day with no sleep_stage/hrv row of its own, so it can never
satisfy the check and gets rescanned (and recomputed) on every single call,
forever. No stored number was ever wrong; this was pure wasted latency and
wasted upserts (measured 1.57-1.98s for a 30-day window, ~193ms per
redundant recompute, never getting faster no matter how many times the page
loads).

The fix, `_owning_days`, maps each raw sample to the night it actually
belongs to using the SAME window function `compute_daily_summary` reads —
sleep's own (`sleep.py`, unaffected by SA-N1) for sleep, and a local-clock
approximation of HRV's night for HRV, since sleep and HRV do not share one
window and HRV's real one (SA-N1) is now session-aware and needs a DB
lookup, which is exactly the O(days) round-trip this batched scan exists to
avoid.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from myvitals.api import summary

CENTRAL = "America/Chicago"


# ── fakes ────────────────────────────────────────────────────────────────

class _Scalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _Result:
    """One `db.execute(...)` return, consumed as `.scalars().all()` or
    `.all()` — `summary_range` uses both shapes across its five queries."""

    def __init__(self, scalars=None, rows=None):
        self._scalars = scalars
        self._rows = rows

    def scalars(self):
        return _Scalars(self._scalars or [])

    def all(self):
        return self._rows or []


class _FakeDb:
    """Hands back queued results in order. `summary_range` issues exactly
    five `db.execute(...)` calls in a fixed sequence: existing daily_summary
    rows, raw sleep_stage times, raw hrv times, the canonical-steps-by-day
    scan, then the final (post-recompute) daily_summary read. Recompute
    itself opens its own session, so it never touches this queue."""

    def __init__(self, *results: _Result):
        self._queue = list(results)

    async def execute(self, _stmt):
        assert self._queue, "summary_range issued more queries than queued"
        return self._queue.pop(0)


def _daily_summary(d: date, **kw):
    fields = {"date": d, "sleep_duration_s": None, "hrv_avg": None,
              "steps_total": None}
    fields.update(kw)
    return SimpleNamespace(**fields)


NO_STEPS = _Result(rows=[])  # canonical_steps_by_day's own query, empty


async def _run(since, until, existing, sleep_times, hrv_times, recorder):
    """One call to `summary_range` against a fresh, fully-queued fake DB."""
    db = _FakeDb(
        _Result(scalars=existing),
        _Result(scalars=sleep_times),
        _Result(scalars=hrv_times),
        NO_STEPS,
        _Result(scalars=[]),  # final read — return value isn't under test
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("myvitals.config.settings.tz", CENTRAL)

        async def fake_compute(d):
            recorder.append(d)

        mp.setattr(
            "myvitals.analytics.jobs.compute_daily_summary",
            AsyncMock(side_effect=fake_compute),
        )
        return await summary.summary_range(since=since, until=until, db=db)


# ── the regression itself ───────────────────────────────────────────────

class TestConvergesInsteadOfLoopingForever:
    """The exact shape of the production bug: an evening-only sleep sample,
    no daily_summary row for either day yet."""

    DAY1 = date(2026, 9, 1)
    DAY2 = date(2026, 9, 2)
    DAY3 = date(2026, 9, 3)

    def _evening_sample(self):
        # 22:41 local on DAY1 — SA-N1's own measured median bedtime. Under
        # the night-ending-on-`day` convention this belongs to the night
        # that ENDS on DAY2, not to DAY1.
        from zoneinfo import ZoneInfo
        return datetime(2026, 9, 1, 22, 41, tzinfo=ZoneInfo(CENTRAL))

    async def test_first_call_recomputes_the_night_it_actually_ends_on(self):
        recorder: list[date] = []
        await _run(
            self.DAY1, self.DAY3,
            existing=[],
            sleep_times=[self._evening_sample()],
            hrv_times=[],
            recorder=recorder,
        )
        # DAY2 owns this night (it ends there); DAY1 does not, even though
        # the sample's own calendar date is DAY1.
        assert self.DAY2 in recorder
        assert self.DAY1 not in recorder

    async def test_second_call_recomputes_nothing_the_bug_would_repeat(self):
        """This is the assertion the old code could not survive: called
        twice with the SAME underlying data, the second call must find
        zero work. The old scan flagged DAY1 forever because the raw
        sample's own date is DAY1 and DAY1's row can never pick up data
        that was always going to land on DAY2."""
        recorder: list[date] = []
        await _run(
            self.DAY1, self.DAY3,
            # DAY2's row is now correctly populated by the first pass;
            # DAY1 still has no row, because DAY1 genuinely has no night
            # ending on it in this data.
            existing=[_daily_summary(self.DAY2, sleep_duration_s=27000)],
            sleep_times=[self._evening_sample()],
            hrv_times=[],
            recorder=recorder,
        )
        assert recorder == []

    async def test_a_sample_in_the_dead_zone_recomputes_nothing(self):
        """14:00-18:00 UTC falls in neither night window (sleep's is
        18:00->14:00 UTC). It must not be attributed to any day, or it
        would be a second way to loop forever."""
        recorder: list[date] = []
        afternoon_utc = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)
        await _run(
            self.DAY1, self.DAY3,
            existing=[],
            sleep_times=[afternoon_utc],
            hrv_times=[],
            recorder=recorder,
        )
        assert recorder == []


class TestHrvUsesItsOwnWindowNotSleeps:
    """The correction's key refinement: sleep and HRV do not share a night
    window, so attributing HRV samples with sleep's boundary is wrong even
    though both are "night" concepts."""

    DAY1 = date(2026, 9, 1)
    DAY2 = date(2026, 9, 2)

    async def test_an_early_evening_hrv_sample_still_owns_the_next_day(self):
        from zoneinfo import ZoneInfo
        recorder: list[date] = []
        # 23:00 local — inside HRV's local 22:00-> window, and also inside
        # sleep's UTC 18:00-> window converted to local. Both windows would
        # (correctly, separately) attribute this to DAY2; this just checks
        # the HRV path is wired to ITS OWN function and fires at all.
        late = datetime(2026, 9, 1, 23, 0, tzinfo=ZoneInfo(CENTRAL))
        await _run(
            self.DAY1, self.DAY2,
            existing=[],
            sleep_times=[],
            hrv_times=[late],
            recorder=recorder,
        )
        assert self.DAY2 in recorder
        assert self.DAY1 not in recorder

    def test_hrv_window_is_local_not_utc(self):
        """SA-N1 exists because a UTC-anchored clock window silently drifts
        against the user's real timezone. Re-hardcoding UTC here would be
        the identical bug at a second call site."""
        from zoneinfo import ZoneInfo
        start, end = summary._hrv_night_window(
            date(2026, 9, 2), ZoneInfo(CENTRAL))
        assert start.tzinfo != timezone.utc
        assert start.utcoffset() != timedelta(0)


# ── the pure attribution helper, directly ───────────────────────────────

class TestOwningDays:
    SINCE = date(2026, 9, 1)
    UNTIL = date(2026, 9, 5)

    def test_evening_utc_sample_owns_the_following_day(self):
        ts = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)  # 18:00-> window
        days = summary._owning_days(
            [ts], summary._sleep_night_window, self.SINCE, self.UNTIL)
        assert days == {date(2026, 9, 3)}

    def test_early_morning_utc_sample_owns_the_same_day(self):
        ts = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)  # before 14:00
        days = summary._owning_days(
            [ts], summary._sleep_night_window, self.SINCE, self.UNTIL)
        assert days == {date(2026, 9, 3)}

    def test_no_samples_owns_nothing(self):
        assert summary._owning_days(
            [], summary._sleep_night_window, self.SINCE, self.UNTIL) == set()

    def test_a_sample_outside_the_requested_range_is_not_counted(self):
        # Owns 2026-09-10, which is past `UNTIL` — must not leak in.
        ts = datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)
        days = summary._owning_days(
            [ts], summary._sleep_night_window, self.SINCE, self.UNTIL)
        assert days == set()

    def test_the_range_scan_uses_owning_days_not_a_raw_date_cast(self):
        """Two copies of "which day does this sample belong to" drifting
        apart is exactly how this bug shipped in the first place."""
        import inspect

        src = inspect.getsource(summary.summary_range)
        assert "_owning_days" in src
        assert "func.timezone(tzname" not in src, (
            "back to casting a raw sample to its own local date — the "
            "exact SA-N2 bug"
        )
