"""UI-F2 — personal records, the period banner's window/filter, month totals.

The records card used to be computed in the browser from whichever rows the
page had fetched, and the phone never had one. These pin the server answer:
null (never 0) when nothing qualifies, the clients' category mapping, a
fastest effort only where pace means something, and a stats banner that
describes exactly the window and chip on screen.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from myvitals.analytics.activity_records import (
    Row, category_for_type, personal_records,
)
from myvitals.analytics.activity_ytd import Entry, ytd_compare
from myvitals.api import strava

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _row(sid, type_="Ride", *, dist=None, dur=3600, elev=None, suffer=None,
         at=T0, name=None):
    return Row(source="strava", source_id=str(sid), name=name or f"a{sid}",
               type=type_, start_at=at, day=at.date(), duration_s=dur,
               distance_m=dist, elevation_m=elev, suffer_score=suffer)


def _rec(out, key):
    return next(r for r in out["records"] if r["key"] == key)


# ── category mapping mirrors activityCategory.ts / ActivityCategory.kt ──

@pytest.mark.parametrize("t,cat", [
    ("Ride", "ride"), ("VirtualRide", "ride"), ("EBikeRide", "ride"),
    ("mountain_biking", "ride"), ("Run", "run"), ("TrailRun", "run"),
    ("Hike", "walk"), ("Walk", "walk"), ("Rowing", "row"), ("Kayaking", "row"),
    ("WeightTraining", "strength"), ("Yoga", "yoga"), ("", "other"),
    (None, "other"), ("Elliptical", "other"),
    # "run" is tested before "walk": MyFitnessPal labels carry both words.
    ("walking_or_running_mixed", "run"),
])
def test_category_mapping_matches_the_clients(t, cat):
    assert category_for_type(t) == cat


# ── records ──

def test_no_qualifying_activity_is_null_never_zero():
    out = personal_records([_row(1, dist=None, elev=None, suffer=None)], "ride")
    for key in ("longest_distance", "most_elevation", "highest_suffer", "fastest"):
        r = _rec(out, key)
        assert r["value"] is None and r["activity"] is None
    # Duration exists, so that one record is real.
    assert _rec(out, "longest_duration")["value"] == 3600


def test_zero_valued_fields_do_not_set_records():
    out = personal_records([_row(1, dist=0.0, elev=0.0, suffer=0.0)], None)
    assert _rec(out, "longest_distance")["value"] is None
    assert _rec(out, "most_elevation")["value"] is None
    assert _rec(out, "highest_suffer")["value"] is None


def test_records_link_to_their_activity_and_respect_category():
    rows = [
        _row(1, "Ride", dist=40_000, elev=300, suffer=80, name="Long ride"),
        _row(2, "Run", dist=50_000, elev=900, suffer=200, name="Ultra"),
    ]
    out = personal_records(rows, "ride")
    assert out["category"] == "ride" and out["n_considered"] == 1
    d = _rec(out, "longest_distance")
    assert d["value"] == 40_000
    assert d["activity"]["source_id"] == "1"
    assert d["activity"]["name"] == "Long ride"
    assert d["activity"]["date"] == "2026-09-01"
    # "all" crosses categories.
    assert _rec(personal_records(rows, "all"), "longest_distance")["activity"]["source_id"] == "2"


def test_fastest_only_for_ride_and_run_and_ignores_short_blips():
    rows = [
        _row(1, "Ride", dist=150, dur=10),         # 15 m/s blip, too short
        _row(2, "Ride", dist=30_000, dur=3600),    # 8.33 m/s
        _row(3, "Ride", dist=20_000, dur=3000),    # 6.67 m/s
    ]
    f = _rec(personal_records(rows, "ride"), "fastest")
    assert f["activity"]["source_id"] == "2"
    assert f["value"] == pytest.approx(30_000 / 3600, abs=1e-3)
    assert f["display"] == "speed"
    run = _rec(personal_records([_row(4, "Run", dist=5000, dur=1500)], "run"), "fastest")
    assert run["display"] == "pace"
    for cat in (None, "all", "walk", "row"):
        assert all(r["key"] != "fastest" for r in personal_records(rows, cat)["records"])


def test_tie_goes_to_the_earlier_effort():
    rows = [
        _row(2, dist=10_000, at=T0 + timedelta(days=3)),
        _row(1, dist=10_000, at=T0),
    ]
    assert _rec(personal_records(rows, None), "longest_distance")["activity"]["source_id"] == "1"


def test_records_endpoint_rejects_unknown_category():
    with pytest.raises(HTTPException):
        asyncio.run(strava.activities_records(category="skiing", since=None,
                                              until=None, db=None))


# ── month totals (group-by-month headers) ──

def test_months_are_newest_first_and_count_every_session():
    today = date(2026, 9, 24)
    out = ytd_compare([
        Entry(date(2026, 9, 2), 1800, 10_000.0),
        Entry(date(2026, 9, 20), 600),          # a strength day: no distance
        Entry(date(2026, 8, 31), 1200, 5_000.0),
        Entry(date(2026, 9, 25), 999),          # tomorrow: excluded
    ], today)
    assert out["months"] == [
        {"month_start": "2026-09-01", "sessions": 2, "duration_s": 2400},
        {"month_start": "2026-08-01", "sessions": 1, "duration_s": 1200},
    ]


# ── /activities/stats with the feed's window + chip ──

class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Queue:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        return self._results.pop(0)


def _act(type_, days_ago, dist=None, dur=600, elev=None, kcal=None):
    return SimpleNamespace(
        type=type_, start_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        distance_m=dist, duration_s=dur, elevation_gain_m=elev, kcal=kcal,
    )


def _stats(results, **kw):
    params = dict(days=30, since=None, until=None, category=None, include_strength=False)
    params.update(kw)
    return asyncio.run(strava.activities_stats(db=_Queue(results), **params))


def test_stats_category_filters_with_the_feed_mapping():
    acts = [_act("Ride", 1, dist=20_000), _act("VirtualRide", 2, dist=10_000),
            _act("Run", 3, dist=5_000)]
    out = _stats([_Res(acts), _Res([a.start_at for a in acts])], category="ride")
    assert out.n_activities == 2
    assert out.total_distance_m == 30_000
    assert out.category == "ride"


def test_stats_reports_what_the_totals_are_made_of():
    acts = [_act("WeightTraining", 1), _act("Yoga", 2)]
    out = _stats([_Res(acts), _Res([a.start_at for a in acts])])
    # Nothing carried a distance: the client must print "—", not "0 km".
    assert out.n_with_distance == 0 and out.n_with_elevation == 0 and out.n_with_kcal == 0


def test_stats_since_window_and_strength_inclusion():
    today = datetime.now(timezone.utc).date()
    acts = [_act("Ride", 1, dist=1000, dur=600), _act("Ride", 40, dist=1000, dur=600)]
    wo = SimpleNamespace(
        date=today - timedelta(days=1), split_focus="push",
        completed_by_activity_source=None,
        started_at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 11, tzinfo=timezone.utc), total_paused_s=600,
    )
    auto = SimpleNamespace(
        date=today - timedelta(days=1), split_focus="cardio",
        completed_by_activity_source="strava",
        started_at=None, completed_at=None, total_paused_s=0,
    )
    out = _stats(
        [_Res(acts), _Res([wo, auto]), _Res([a.start_at for a in acts])],
        since=today - timedelta(days=6), include_strength=True,
    )
    assert out.n_activities == 2          # one ride in window + one lift
    assert out.n_strength == 1            # the auto-completed cardio day is not double counted
    assert out.total_duration_s == 600 + 3000
    assert out.window_since == (today - timedelta(days=6)).isoformat()
    assert out.period_label.startswith("Since ")


def test_stats_strength_chip_counts_only_workouts():
    today = datetime.now(timezone.utc).date()
    wo = SimpleNamespace(date=today, split_focus="legs", completed_by_activity_source=None,
                         started_at=None, completed_at=None, total_paused_s=0)
    # No activity query at all for the strength chip.
    out = _stats([_Res([wo]), _Res([])], category="strength", include_strength=True)
    assert out.n_activities == 1 and out.n_strength == 1
    assert out.total_distance_m == 0 and out.n_with_distance == 0


def test_stats_rejects_unknown_category():
    with pytest.raises(HTTPException):
        _stats([], category="skiing")
