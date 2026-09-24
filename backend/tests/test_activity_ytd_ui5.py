"""UI-5 — server-owned YTD comparison, trail status summary, list routes.

The YTD card used to be computed on three clients that disagreed; these
pin the one server answer, and in particular the two things every client
copy got wrong: "+100%" invented when last year is zero, and a shortfall
treated as an alarm rather than as information.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import polyline as polyline_lib

from myvitals.analytics.activity_ytd import Entry, same_day_last_year, week_start, ytd_compare
from myvitals.api import strava
from myvitals.api.trails import status_summary
from myvitals.db import models

TODAY = date(2026, 9, 24)  # a Thursday


def _m(out, key):
    return next(m for m in out["metrics"] if m["key"] == key)


def test_no_invented_percentage_when_last_year_is_zero():
    out = ytd_compare([Entry(date(2026, 3, 1), 3600, 20_000.0, 100.0)], TODAY)
    d = _m(out, "distance_m")
    assert d["prior"] == 0
    assert d["pct_change"] is None          # not "+100%"
    assert d["direction"] == "new" and d["note"] == "new"
    assert d["tone"] == "positive"


def test_nothing_either_year_is_flat_not_new():
    out = ytd_compare([], TODAY)
    for m in out["metrics"]:
        assert m["pct_change"] is None
        assert m["direction"] == "flat" and m["tone"] == "neutral"


def test_shortfall_is_caution_never_a_crisis_tone():
    entries = [
        Entry(date(2025, 2, 1), 3600, 30_000.0),
        Entry(date(2025, 3, 1), 3600, 30_000.0),
        Entry(date(2026, 2, 1), 3600, 30_000.0),
    ]
    d = _m(ytd_compare(entries, TODAY), "distance_m")
    assert d["direction"] == "worse"
    assert d["tone"] == "caution"
    assert d["pct_change"] == -50.0
    assert all(m["tone"] in {"positive", "neutral", "caution"}
               for m in ytd_compare(entries, TODAY)["metrics"])


def test_last_year_is_cut_at_the_same_day():
    entries = [
        Entry(date(2025, 9, 24), 600, 1000.0),   # same day last year: counts
        Entry(date(2025, 9, 25), 600, 1000.0),   # the day after: does not
        Entry(date(2026, 9, 25), 600, 1000.0),   # tomorrow: does not
    ]
    out = ytd_compare(entries, TODAY)
    assert _m(out, "sessions")["prior"] == 1
    assert _m(out, "sessions")["current"] == 0


def test_leap_day_falls_back_to_the_28th():
    assert same_day_last_year(date(2028, 2, 29)) == date(2027, 2, 28)


def test_null_distance_is_not_zero_in_the_cumulative_line_or_sessions():
    entries = [Entry(date(2026, 1, 3), 1800, None), Entry(date(2026, 1, 5), 1800, 5000.0)]
    out = ytd_compare(entries, TODAY)
    this = out["cumulative_distance_m"]["this_year"]
    assert len(this) == (TODAY - date(2026, 1, 1)).days + 1
    assert this[2] == 0 and this[4] == 5000 and this[-1] == 5000
    assert _m(out, "sessions")["current"] == 2
    assert len(out["cumulative_distance_m"]["last_year"]) == 365


def test_weeks_are_local_mondays_newest_first_with_this_week():
    entries = [
        Entry(date(2026, 9, 21), 1800),   # Monday this week
        Entry(date(2026, 9, 24), 1200),   # today
        Entry(date(2026, 9, 20), 600),    # Sunday last week
    ]
    out = ytd_compare(entries, TODAY)
    assert week_start(TODAY) == date(2026, 9, 21)
    assert out["this_week"] == {"week_start": "2026-09-21", "sessions": 2, "duration_s": 3000}
    assert [w["week_start"] for w in out["weeks"]] == ["2026-09-21", "2026-09-14"]
    assert out["weeks"][1]["sessions"] == 1


def test_trail_status_summary_counts_unknown_as_other_not_closed():
    t1 = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 24, 12, 5, tzinfo=timezone.utc)
    rows = [
        {"status": "open", "fetched_at": t1},
        {"status": "open", "fetched_at": t2},
        {"status": "delayed", "fetched_at": None},
        {"status": "closed", "fetched_at": t1},
        {"status": None, "fetched_at": None},
    ]
    s = status_summary(rows)
    assert s["status_counts"] == {"open": 2, "delayed": 1, "closed": 1, "other": 1}
    assert s["synced_at"] == t2
    assert status_summary([]) == {
        "status_counts": {"open": 0, "delayed": 0, "closed": 0, "other": 0},
        "synced_at": None,
    }


def _act(**kw):
    d = dict(source="strava", source_id="1", type="Ride",
             start_at=datetime(2026, 9, 1, tzinfo=timezone.utc), duration_s=60)
    d.update(kw)
    return models.Activity(**d)


def test_list_route_modes():
    pts = [(39.0 + i * 0.0001, -94.0 + (i % 2) * 0.00001) for i in range(200)]
    full = polyline_lib.encode(pts)
    a = _act(polyline=full, polyline_simple=None)
    assert strava._route_for(a, "full") == full
    assert strava._route_for(a, "none") is None
    simple = strava._route_for(a, "simple")
    assert simple and len(polyline_lib.decode(simple)) < len(pts)
    # A stored simplification wins and is not recomputed.
    assert strava._route_for(_act(polyline=full, polyline_simple="abc"), "simple") == "abc"
    assert strava._route_for(_act(polyline=None), "simple") is None


def test_list_never_loads_raw_and_skips_unsent_routes():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    def cols(mode):
        stmt = select(models.Activity).options(*strava._list_deferrals(mode))
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        head = sql.split(" FROM ")[0]
        return {c.strip().split(".")[-1] for c in head[len("SELECT "):].split(",")}
    for mode in ("full", "simple", "none"):
        assert "raw" not in cols(mode)
    assert "polyline" in cols("full") and "polyline_simple" not in cols("full")
    assert "polyline" not in cols("none") and "polyline_simple" not in cols("none")
    assert {"polyline", "polyline_simple"} <= cols("simple")
