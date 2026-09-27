"""GET /summary/coverage — per-day "was this measured, or only carried?".

The day builder is pure and tested directly; the endpoint is tested with a
queued fake session (no test in this suite runs Postgres), and the one
query against the big heart-rate table is compiled and checked for the
shape that keeps it cheap: bounded on both sides of `time`, collapsed per
minute, then per local day.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from myvitals.analytics import coverage
from myvitals.api import summary
from myvitals.localtime import local_today

CHI = ZoneInfo("America/Chicago")
TODAY = date(2026, 9, 26)


def _t(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=CHI)


def _row(d: date, **kw):
    base = {f: None for f in coverage.CARRY_FIELDS}
    base.update(kw)
    return SimpleNamespace(date=d, **base)


def _build(since, until, *, hr=None, sessions=(), hrv=(), summaries=None, today=TODAY):
    return coverage.build_coverage(
        since, until, CHI, hr or {}, list(sessions), list(hrv), summaries or {}, today,
    )


class TestMainSession:
    def test_longest_session_of_three_hours_ending_that_day(self):
        night = (_t(2026, 9, 19, 23, 30), _t(2026, 9, 20, 7, 0))
        dup = (_t(2026, 9, 20, 0, 30), _t(2026, 9, 20, 5, 0))       # shorter, other source
        nap = (_t(2026, 9, 20, 14, 0), _t(2026, 9, 20, 15, 0))      # < 3 h
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), sessions=[dup, nap, night])
        assert row["main_session"] == {
            "start": "2026-09-19T23:30:00-05:00",
            "end": "2026-09-20T07:00:00-05:00",
            "hours": 7.5,
        }

    def test_naps_alone_are_not_a_main_session(self):
        nap = (_t(2026, 9, 20, 13, 0), _t(2026, 9, 20, 15, 59))
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), sessions=[nap])
        assert row["main_session"] is None

    def test_exactly_three_hours_counts(self):
        s = (_t(2026, 9, 20, 3, 0), _t(2026, 9, 20, 6, 0))
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), sessions=[s])
        assert row["main_session"]["hours"] == 3.0

    def test_attributed_to_the_local_day_it_ends(self):
        """00:30 local on the 21st is 05:30 UTC — still the 21st locally,
        and 04:30 local (09:30 UTC) is not the 20th."""
        late = (datetime(2026, 9, 20, 21, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 21, 5, 30, tzinfo=timezone.utc))
        rows = _build(date(2026, 9, 20), date(2026, 9, 21), sessions=[late])
        assert rows[0]["main_session"] is None
        assert rows[1]["main_session"]["end"] == "2026-09-21T00:30:00-05:00"

    def test_sessions_outside_the_range_are_ignored(self):
        s = (_t(2026, 9, 18, 23, 0), _t(2026, 9, 19, 7, 0))
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), sessions=[s])
        assert row["main_session"] is None


class TestHrv:
    def test_counted_inside_the_main_session(self):
        night = (_t(2026, 9, 19, 23, 30), _t(2026, 9, 20, 7, 0))
        hrv = [_t(2026, 9, 19, 23, 0),          # before the session
               _t(2026, 9, 19, 23, 30),         # at start (inclusive)
               _t(2026, 9, 20, 3, 0),
               _t(2026, 9, 20, 7, 0),           # at end (inclusive)
               _t(2026, 9, 20, 8, 0)]           # after
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), sessions=[night], hrv=hrv)
        assert row["hrv_samples"] == 3

    def test_without_a_session_the_22_to_09_local_night(self):
        hrv = [_t(2026, 9, 19, 21, 59), _t(2026, 9, 19, 22, 0), _t(2026, 9, 20, 4, 0),
               _t(2026, 9, 20, 9, 0), _t(2026, 9, 20, 9, 1)]
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), hrv=hrv)
        assert row["hrv_samples"] == 3

    def test_fallback_night_across_the_dst_change(self):
        """Nov 1 2026: 22:00 CDT on Oct 31 → 09:00 CST on Nov 1 is 12 hours."""
        lo, hi = coverage.hrv_night_window(date(2026, 11, 1), CHI)
        # Subtract in UTC: same-tzinfo subtraction in Python is wall-clock.
        assert hi.astimezone(timezone.utc) - lo.astimezone(timezone.utc) == timedelta(hours=12)
        assert lo.utcoffset() == timedelta(hours=-5)
        assert hi.utcoffset() == timedelta(hours=-6)

    def test_unsorted_input_is_fine(self):
        hrv = [_t(2026, 9, 20, 4, 0), _t(2026, 9, 19, 23, 0), _t(2026, 9, 20, 2, 0)]
        [row] = _build(date(2026, 9, 20), date(2026, 9, 20), hrv=hrv)
        assert row["hrv_samples"] == 3


class TestCarried:
    D = date(2026, 9, 23)

    def _two(self, today_kw, prev_kw):
        return {self.D: _row(self.D, **today_kw), self.D - timedelta(days=1): _row(
            self.D - timedelta(days=1), **prev_kw)}

    def test_repeats_on_a_day_without_a_night_are_carried(self):
        s = self._two(
            {"resting_hr": 55.0, "hrv_avg": 17.2, "recovery_score": 61.0, "sleep_score": 80.0},
            {"resting_hr": 55.0, "hrv_avg": 17.2, "recovery_score": 61.0, "sleep_score": 75.0},
        )
        [row] = _build(self.D, self.D, summaries=s)
        assert row["carried"] == ["resting_hr", "hrv_avg", "recovery_score"]

    def test_a_day_with_a_night_carries_nothing_even_if_equal(self):
        s = self._two({"resting_hr": 55.0}, {"resting_hr": 55.0})
        night = (_t(2026, 9, 22, 23, 0), _t(2026, 9, 23, 6, 0))
        [row] = _build(self.D, self.D, summaries=s, sessions=[night])
        assert row["carried"] == []

    def test_nulls_and_missing_rows_are_not_carried(self):
        s = self._two({"resting_hr": None, "hrv_avg": 17.0}, {"resting_hr": None, "hrv_avg": None})
        [row] = _build(self.D, self.D, summaries=s)
        assert row["carried"] == []
        [row] = _build(self.D, self.D, summaries={self.D: _row(self.D, resting_hr=50.0)})
        assert row["carried"] == []

    def test_non_nightly_fields_are_never_reported(self):
        assert not {"weight_kg", "steps_total", "ctl", "atl", "tsb", "fasting_hours",
                    "bp_systolic_avg", "bp_diastolic_avg"} & set(coverage.CARRY_FIELDS)


class TestDays:
    def test_one_row_per_day_zero_filled(self):
        rows = _build(date(2026, 9, 6), date(2026, 9, 8),
                      hr={date(2026, 9, 7): (31680, 1320)})
        assert [r["date"] for r in rows] == ["2026-09-06", "2026-09-07", "2026-09-08"]
        assert [(r["hr_samples"], r["hr_wear_min"]) for r in rows] == [
            (0, 0), (31680, 1320), (0, 0)]

    def test_today_is_flagged_in_progress(self):
        rows = _build(TODAY - timedelta(days=1), TODAY)
        assert [r["in_progress"] for r in rows] == [False, True]

    def test_row_shape(self):
        [row] = _build(TODAY, TODAY)
        assert set(row) == {"date", "in_progress", "hr_samples", "hr_wear_min",
                            "main_session", "hrv_samples", "carried"}


# ── The query ───────────────────────────────────────────────────────────

def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.asyncpg.dialect())).lower()


class TestHeartRateQuery:
    def test_bounded_bucketed_and_grouped_in_the_database(self):
        start, end = coverage.local_bounds(date(2026, 1, 1), date(2026, 12, 31), CHI)
        sql = _sql(coverage.hr_by_day_stmt(start, end, "America/Chicago"))
        assert "from vitals_heartrate" in sql
        assert "vitals_heartrate.time >=" in sql and "vitals_heartrate.time <" in sql
        assert "time_bucket(" in sql
        assert sql.count("group by") == 2
        # Local-day grouping happens in SQL, keyed on the same bound tz param.
        local_day = "cast(timezone($1::varchar, per_minute.minute) as date)"
        assert local_day in sql
        assert sql.rstrip().endswith(f"group by {local_day}")

    def test_local_bounds_are_local_midnights(self):
        start, end = coverage.local_bounds(date(2026, 9, 20), date(2026, 9, 21), CHI)
        assert start == _t(2026, 9, 20) and end == _t(2026, 9, 22)


# ── The endpoint ────────────────────────────────────────────────────────

class _Res:
    def __init__(self, rows=None, scalars=None):
        self._rows, self._scalars = rows or [], scalars or []

    def all(self):
        return self._rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._scalars)


class _QueuedDb:
    """Hands back results in the order day_coverage queries: HR per day,
    sleep sessions, HRV times, daily_summary rows. Records every statement."""

    def __init__(self, *results):
        self._queue = list(results)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        assert self._queue, "more queries than expected"
        return self._queue.pop(0)


def _db(**kw):
    return _QueuedDb(
        _Res(rows=kw.get("hr", [])),
        _Res(rows=kw.get("sessions", [])),
        _Res(scalars=kw.get("hrv", [])),
        _Res(scalars=kw.get("summaries", [])),
    )


@pytest.fixture
def central(monkeypatch):
    monkeypatch.setattr("myvitals.config.settings.tz", "America/Chicago")


class TestEndpoint:
    async def test_happy_path(self, central):
        today = local_today()
        d = today - timedelta(days=2)
        night = (datetime.combine(d - timedelta(days=1), datetime.min.time(), tzinfo=CHI)
                 + timedelta(hours=23),
                 datetime.combine(d, datetime.min.time(), tzinfo=CHI) + timedelta(hours=7))
        db = _db(hr=[(d, 30000, 1300)], sessions=[night],
                 hrv=[night[0] + timedelta(hours=1)])
        rows = await summary.summary_coverage(since=d, until=d, db=db)
        assert rows == [{
            "date": d.isoformat(), "in_progress": False, "hr_samples": 30000,
            "hr_wear_min": 1300,
            "main_session": {"start": night[0].isoformat(), "end": night[1].isoformat(),
                             "hours": 8.0},
            "hrv_samples": 1, "carried": [],
        }]
        assert len(db.statements) == 4

    async def test_every_time_series_read_is_bounded(self, central):
        today = local_today()
        db = _db()
        await summary.summary_coverage(since=today - timedelta(days=30), until=today, db=db)
        sqls = [_sql(s) for s in db.statements]
        for table, col in (("vitals_heartrate", "time"), ("vitals_hrv", "time"),
                           ("sleep_sessions", "end_at"), ("daily_summary", "date")):
            [sql] = [s for s in sqls if f"from {table}" in s]
            assert f"{table}.{col} >=" in sql, table
            assert f"{table}.{col} <" in sql, table

    async def test_until_defaults_to_and_is_clamped_to_today(self, central):
        today = local_today()
        rows = await summary.summary_coverage(since=today - timedelta(days=1), until=None, db=_db())
        assert [r["date"] for r in rows] == [(today - timedelta(days=1)).isoformat(),
                                             today.isoformat()]
        rows = await summary.summary_coverage(
            since=today, until=today + timedelta(days=30), db=_db())
        assert [r["date"] for r in rows] == [today.isoformat()]
        assert rows[0]["in_progress"] is True

    @pytest.mark.parametrize("since_off,until_off", [
        (0, -1),        # since after until
        (5, None),      # since in the future
        (-400, 0),      # 401 days
    ])
    async def test_bad_ranges_are_422(self, central, since_off, until_off):
        today = local_today()
        until = None if until_off is None else today + timedelta(days=until_off)
        with pytest.raises(HTTPException) as ei:
            await summary.summary_coverage(
                since=today + timedelta(days=since_off), until=until, db=_db())
        assert ei.value.status_code == 422

    async def test_400_days_is_allowed(self, central):
        today = local_today()
        rows = await summary.summary_coverage(
            since=today - timedelta(days=399), until=today, db=_db())
        assert len(rows) == 400
