"""UI-F1 — the detail-screen extras UI-4 removed because they were computed
in the browser: resting HR vs the previous window, HR by activity type, the
weight distribution and days-at-min. Each now comes from
analytics/detail_stats.py and is rendered verbatim on both clients.
"""
import ast
import pathlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from myvitals.analytics import detail_stats as ds

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"
T = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


# ── resting HR vs the previous window ────────────────────────────────────

def test_lower_resting_hr_than_before_is_positive():
    c = ds.window_change([55, 57, None], [60, 60], better="down")
    assert c["avg_now"] == 56.0 and c["avg_before"] == 60.0
    assert c["delta"] == -4.0
    assert c["better"] == "down" and c["tone"] == "positive"
    assert (c["days_now"], c["days_before"]) == (2, 2)   # the None is not a zero


def test_higher_resting_hr_is_caution_never_a_crisis_tone():
    c = ds.window_change([64], [60], better="down")
    assert c["tone"] == "caution"


def test_change_inside_the_band_is_neutral():
    c = ds.window_change([60.5], [60.0])
    assert c["delta"] == 0.5 and c["tone"] == "neutral"


def test_empty_previous_window_is_null_not_zero():
    c = ds.window_change([60, 62], [None, None])
    assert c["avg_now"] == 61.0
    assert c["avg_before"] is None and c["delta"] is None
    assert c["tone"] == "neutral"


def test_better_up_flips_the_verdict():
    assert ds.window_change([70], [60], better="up")["tone"] == "positive"


# ── HR by activity type ──────────────────────────────────────────────────

def test_category_mapping_order_is_load_bearing():
    assert ds.activity_category("VirtualRide")[0] == "ride"
    assert ds.activity_category("vr_fitness")[0] == "vr"
    assert ds.activity_category("MountainBikeRide")[0] == "ride"
    assert ds.activity_category("TrailRun")[0] == "run"
    assert ds.activity_category("running")[0] == "run"
    assert ds.activity_category("Hike")[0] == "hike"
    assert ds.activity_category("rower")[0] == "row"
    assert ds.activity_category("WeightTraining")[0] == "strength"
    assert ds.activity_category("manual_cardio")[0] == "cardio"
    assert ds.activity_category("yard_work") == ds.OTHER_CATEGORY
    assert ds.activity_category(None) == ds.OTHER_CATEGORY


def test_hr_by_type_groups_by_category_and_reports_n():
    out = ds.hr_by_activity_type([
        ("Ride", 130), ("VirtualRide", 140), ("Run", 150), ("Run", 160),
        ("Run", None), ("Hike", 110),
    ])
    assert out["types"] == [
        {"category": "run", "label": "Run", "n": 2, "avg_bpm": 155},
        {"category": "ride", "label": "Ride", "n": 2, "avg_bpm": 135},
    ]
    # One hike is one session, not an average: listed with its count only.
    assert out["sparse"] == [{"category": "hike", "label": "Hike", "n": 1}]
    assert out["min_n"] == 2


def test_hr_by_type_with_nothing_is_empty_not_zero():
    out = ds.hr_by_activity_type([("Ride", None)])
    assert out["types"] == [] and out["sparse"] == []


# ── weight histogram ─────────────────────────────────────────────────────

def test_weight_histogram_half_kg_bins_zero_filled():
    h = ds.weight_histogram([80.0, 80.4, 81.2, 80.1])
    assert h["bin_kg"] == 0.5
    assert h["bins"] == [
        {"lo_kg": 80.0, "hi_kg": 80.5, "count": 3},
        {"lo_kg": 80.5, "hi_kg": 81.0, "count": 0},   # gap stays visible
        {"lo_kg": 81.0, "hi_kg": 81.5, "count": 1},
    ]
    assert sum(b["count"] for b in h["bins"]) == 4


def test_weight_histogram_widens_bins_for_a_wild_span():
    h = ds.weight_histogram([60.0, 110.0])
    assert h["bin_kg"] == 2.0
    assert len(h["bins"]) <= ds.WEIGHT_HIST_MAX_BINS


def test_weight_histogram_empty_is_none():
    assert ds.weight_histogram([]) is None


# ── days at min ──────────────────────────────────────────────────────────

def test_days_at_min_counts_days_not_readings():
    pts = [
        (T, 80.0), (T + timedelta(hours=2), 80.04),      # same day, twice at the low
        (T + timedelta(days=1), 81.0),
        (T + timedelta(days=5), 80.0),                   # the low again, not consecutive
        (T + timedelta(days=6), 80.1),                   # 0.1 above: not at the low
    ]
    assert ds.days_at_min(pts) == 2


def test_days_at_min_uses_the_local_day():
    # 01:00 UTC and 23:00 UTC the previous day are the SAME Central day.
    a = datetime(2026, 9, 2, 1, 0, tzinfo=timezone.utc)
    b = datetime(2026, 9, 1, 23, 0, tzinfo=timezone.utc)
    pts = [(a, 70.0), (b, 70.0)]
    assert ds.days_at_min(pts) == 2
    assert ds.days_at_min(pts, ZoneInfo("America/Chicago")) == 1


def test_days_at_min_empty_is_none_not_zero():
    assert ds.days_at_min([]) is None


def test_weight_stats_carries_the_new_fields():
    s = ds.weight_stats([(T, 80.0), (T + timedelta(days=1), 80.6)], None)
    assert s["days_at_min"] == 1
    assert s["histogram"]["bins"][0]["count"] == 1
    empty = ds.weight_stats([], None)
    assert empty["histogram"] is None and empty["days_at_min"] is None


# ── wiring ───────────────────────────────────────────────────────────────

def _fn_src(path, name):
    text = path.read_text()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{name} not found")


def test_range_stats_serves_the_hr_extras_from_the_server():
    src = _fn_src(SRC / "api" / "summary.py", "summary_range_stats")
    assert "window_change(" in src and 'better="down"' in src
    assert "hr_by_activity_type(" in src
    # The previous window is read through the same /summary/range path.
    assert src.count("await summary_range(") == 2


def test_weight_endpoint_resolves_days_in_local_time():
    src = _fn_src(SRC / "api" / "query.py", "get_weight")
    assert "tz=local_tz()" in src
