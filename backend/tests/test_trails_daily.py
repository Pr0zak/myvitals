"""GET /trails/daily — trails open at 07:00, and what flipped that day.

The poller writes a snapshot only when a trail changes (SA-C5), so "status
at 07:00" is the latest snapshot at or before 07:00, however old — a trail
open for a month has no snapshot this morning and is still open. Unknown
and pending say nothing about the trail, so they are left out of `known`
and skipped when deciding what a status changed FROM.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from myvitals.analytics import trail_days
from myvitals.api import trails
from myvitals.localtime import local_today

CHI = ZoneInfo("America/Chicago")
TODAY = date(2026, 9, 26)
D = date(2026, 9, 20)


def _t(d: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    """A snapshot time, as the DB returns it (UTC)."""
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=CHI).astimezone(timezone.utc)


def _days(since, until, seeds=None, changes=(), today=TODAY):
    return trail_days.build_trail_days(since, until, CHI, seeds or {}, list(changes), today)


def _one(**kw):
    [row] = _days(D, D, **kw)
    return row


class TestMorningStatus:
    def test_an_old_snapshot_still_counts(self):
        """No snapshot for weeks is the normal case now, not missing data."""
        row = _one(seeds={1: ("open", "open"), 2: ("closed", "closed")})
        assert (row["open_at_0700"], row["known_at_0700"], row["total"]) == (1, 2, 2)

    def test_a_change_at_exactly_0700_counts_and_0700_01_does_not(self):
        at = _one(seeds={1: ("closed", "closed")}, changes=[(1, _t(D, 7), "open")])
        after = _one(seeds={1: ("closed", "closed")}, changes=[(1, _t(D, 7, 0, 1), "open")])
        assert at["open_at_0700"] == 1
        assert after["open_at_0700"] == 0

    def test_unknown_and_pending_are_not_known_but_are_in_total(self):
        row = _one(seeds={1: ("unknown", "open"), 2: ("pending", None), 3: ("open", "open")})
        assert (row["open_at_0700"], row["known_at_0700"], row["total"]) == (1, 1, 3)

    def test_delayed_is_known_but_not_open(self):
        row = _one(seeds={1: ("delayed", "delayed")})
        assert (row["open_at_0700"], row["delayed_at_0700"], row["known_at_0700"]) == (0, 1, 1)

    def test_a_trail_first_seen_after_0700_is_not_in_that_morning(self):
        rows = _days(D, D + timedelta(days=1), changes=[(1, _t(D, 12), "open")])
        assert [r["total"] for r in rows] == [0, 1]

    def test_morning_read_on_the_dst_change_day(self):
        """Nov 1 2026: 07:00 is CST (UTC-6), i.e. 13:00 UTC, not 12:00."""
        day = date(2026, 11, 1)
        at_1230_utc = datetime(2026, 11, 1, 12, 30, tzinfo=timezone.utc)   # 06:30 CST
        at_1330_utc = datetime(2026, 11, 1, 13, 30, tzinfo=timezone.utc)   # 07:30 CST
        [before] = _days(day, day, seeds={1: ("closed", "closed")},
                         changes=[(1, at_1230_utc, "open")])
        [after] = _days(day, day, seeds={1: ("closed", "closed")},
                        changes=[(1, at_1330_utc, "open")])
        assert before["open_at_0700"] == 1
        assert after["open_at_0700"] == 0


class TestFlips:
    def test_close_and_reopen_land_on_their_local_days(self):
        changes = [(1, _t(D, 15), "closed"), (1, _t(D + timedelta(days=2), 6, 59), "open")]
        rows = _days(D, D + timedelta(days=2), seeds={1: ("open", "open")}, changes=changes)
        assert [(r["closures"], r["reopenings"]) for r in rows] == [(1, 0), (0, 0), (0, 1)]
        assert [r["open_at_0700"] for r in rows] == [1, 0, 1]

    def test_late_evening_utc_is_still_the_local_day(self):
        """23:30 local is 04:30 UTC the next day."""
        row = _one(seeds={1: ("open", "open")}, changes=[(1, _t(D, 23, 30), "closed")])
        assert row["closures"] == 1

    def test_through_unknown_counts_once(self):
        changes = [(1, _t(D, 9), "unknown"), (1, _t(D, 11), "closed")]
        row = _one(seeds={1: ("open", "open")}, changes=changes)
        assert (row["closures"], row["reopenings"]) == (1, 0)

    def test_back_to_the_same_status_through_unknown_is_no_flip(self):
        changes = [(1, _t(D, 9), "unknown"), (1, _t(D, 11), "closed")]
        row = _one(seeds={1: ("closed", "closed")}, changes=changes)
        assert (row["closures"], row["reopenings"]) == (0, 0)

    def test_previous_known_status_reaches_back_past_an_unknown_seed(self):
        """The seed's latest status is unknown, but the latest KNOWN status
        before the window was open — so closed is a closure."""
        row = _one(seeds={1: ("unknown", "open")}, changes=[(1, _t(D, 10), "closed")])
        assert row["closures"] == 1

    def test_first_sighting_is_not_a_flip(self):
        row = _one(changes=[(1, _t(D, 10), "closed"), (2, _t(D, 10), "open")])
        assert (row["closures"], row["reopenings"]) == (0, 0)

    def test_repeated_status_rows_are_not_flips(self):
        changes = [(1, _t(D, 1), "open"), (1, _t(D, 2), "open"), (1, _t(D, 3), "open")]
        row = _one(seeds={1: ("open", "open")}, changes=changes)
        assert (row["closures"], row["reopenings"]) == (0, 0)

    @pytest.mark.parametrize("prev,new,expected", [
        ("delayed", "closed", (1, 0)),
        ("delayed", "open", (0, 1)),
        ("open", "delayed", (0, 0)),
        ("closed", "delayed", (0, 0)),
    ])
    def test_delayed_transitions(self, prev, new, expected):
        row = _one(seeds={1: (prev, prev)}, changes=[(1, _t(D, 10), new)])
        assert (row["closures"], row["reopenings"]) == expected

    def test_unsorted_changes(self):
        changes = [(1, _t(D, 15), "open"), (1, _t(D, 10), "closed")]
        row = _one(seeds={1: ("open", "open")}, changes=changes)
        assert (row["closures"], row["reopenings"]) == (1, 1)


class TestShape:
    def test_one_row_per_day_with_in_progress(self):
        rows = _days(TODAY - timedelta(days=2), TODAY)
        assert [r["date"] for r in rows] == [
            (TODAY - timedelta(days=i)).isoformat() for i in (2, 1, 0)]
        assert [r["in_progress"] for r in rows] == [False, False, True]
        assert set(rows[0]) == {"date", "in_progress", "open_at_0700", "delayed_at_0700",
                                "known_at_0700", "total", "closures", "reopenings"}


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.asyncpg.dialect())).lower()


class TestQueries:
    def test_changes_are_window_bounded_and_collapsed_in_sql(self):
        start = datetime(2026, 9, 1, tzinfo=CHI)
        sql = _sql(trail_days.changes_stmt(start, start + timedelta(days=30)))
        assert "trail_status_snapshots.fetched_at >=" in sql
        assert "trail_status_snapshots.fetched_at <" in sql
        assert "lag(trail_status_snapshots.status) over (partition by" in sql
        assert "w.prev is null" in sql

    def test_seeds_look_strictly_before_the_window(self):
        sql = _sql(trail_days.seeds_stmt(datetime(2026, 9, 1, tzinfo=CHI)))
        assert sql.count("trail_status_snapshots.fetched_at <") == 2
        assert "not in" in sql
        assert sql.count("limit") == 2


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _QueuedDb:
    def __init__(self, *results):
        self._queue = list(results)

    async def execute(self, _stmt):
        return self._queue.pop(0)


@pytest.fixture
def central(monkeypatch):
    monkeypatch.setattr("myvitals.config.settings.tz", "America/Chicago")


class TestEndpoint:
    async def test_happy_path(self, central):
        today = local_today()
        day = today - timedelta(days=1)
        db = _QueuedDb(
            _Res([(1, "open", "open"), (2, "closed", "closed")]),
            _Res([(1, _t(day, 16), "closed")]),
        )
        rows = await trails.trails_daily(since=day, until=day, db=db)
        assert rows == [{
            "date": day.isoformat(), "in_progress": False, "open_at_0700": 1,
            "delayed_at_0700": 0, "known_at_0700": 2, "total": 2,
            "closures": 1, "reopenings": 0,
        }]

    @pytest.mark.parametrize("since_off,until_off", [(0, -1), (3, None), (-400, 0)])
    async def test_bad_ranges_are_422(self, central, since_off, until_off):
        today = local_today()
        until = None if until_off is None else today + timedelta(days=until_off)
        with pytest.raises(HTTPException) as ei:
            await trails.trails_daily(
                since=today + timedelta(days=since_off), until=until,
                db=SimpleNamespace())
        assert ei.value.status_code == 422

    async def test_until_is_clamped_to_today(self, central):
        today = local_today()
        rows = await trails.trails_daily(
            since=today, until=today + timedelta(days=5),
            db=_QueuedDb(_Res([]), _Res([])))
        assert [r["date"] for r in rows] == [today.isoformat()]
