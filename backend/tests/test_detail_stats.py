"""UI-4 — the stat blocks the metric detail screens render verbatim.

These numbers used to be computed on both clients, differently. Each test
pins one rule that a client version got wrong or that is easy to lose.
"""
import ast
import pathlib
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

from myvitals.analytics import detail_stats as ds
from myvitals.analytics.cardio import zone_bounds

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "myvitals"


def _row(d, steps=None, goal=10000, rhr=None):
    return NS(date=d, steps_total=steps, steps_goal=goal, resting_hr=rhr)


# ── steps ────────────────────────────────────────────────────────────────

def test_steps_goal_days_judge_each_day_against_its_own_target():
    rows = [
        _row(date(2026, 9, 6), 6000, goal=5000),    # Sunday, lighter target: hit
        _row(date(2026, 9, 7), 9000, goal=10000),   # missed
        _row(date(2026, 9, 8), 12000, goal=10000),  # hit
    ]
    s = ds.steps_stats(rows, 3)
    assert s["goal_days"] == 2
    assert s["days_with_data"] == 3
    assert s["total"] == 27000
    assert s["avg"] == 9000
    assert (s["min"], s["max"]) == (6000, 12000)


def test_steps_day_without_reading_is_not_a_missed_goal_or_a_zero():
    rows = [_row(date(2026, 9, 7), 12000), _row(date(2026, 9, 8), None)]
    s = ds.steps_stats(rows, 2)
    assert s["days_with_data"] == 1
    assert s["goal_days"] == 1
    assert s["avg"] == 12000          # not 6000
    assert s["min"] == 12000          # not 0


def test_steps_empty_window_is_null_not_zero():
    s = ds.steps_stats([_row(date(2026, 9, 8), None)], 1)
    assert s["avg"] is None and s["total"] is None and s["max"] is None


def test_steps_weekday_means_sunday_first_and_null_for_missing():
    rows = [_row(date(2026, 9, 6), 4000), _row(date(2026, 9, 13), 6000)]  # two Sundays
    wm = ds.steps_stats(rows, 8)["weekday_means"]
    assert [w["dow"] for w in wm][0] == "Sun"
    assert wm[0]["mean"] == 5000 and wm[0]["n"] == 2
    assert wm[1]["mean"] is None      # no Monday reading: unknown, not 0


def test_steps_rolling_mean_skips_missing_days():
    base = date(2026, 9, 1)
    rows = [_row(base + timedelta(days=i), v) for i, v in enumerate([1000, None, 3000])]
    roll = ds.steps_stats(rows, 3)["rolling_7d"]
    assert [r["value"] for r in roll] == [1000, 1000, 2000]


# ── resting HR ───────────────────────────────────────────────────────────

def test_resting_hr_latest_vs_window_average():
    rows = [_row(date(2026, 9, 1), rhr=60), _row(date(2026, 9, 2), rhr=None),
            _row(date(2026, 9, 3), rhr=66)]
    s = ds.resting_hr_stats(rows)
    assert s["avg"] == 63.0 and s["latest"] == 66.0 and s["latest_vs_avg"] == 3.0
    assert s["days_with_data"] == 2


# ── sleep ────────────────────────────────────────────────────────────────

def test_sleep_stats_exclude_naps():
    nights = [NS(total_s=8 * 3600, kind="sleep"), NS(total_s=7 * 3600, kind="sleep"),
              NS(total_s=45 * 60, kind="nap")]
    s = ds.sleep_stats(nights)
    assert s["min_s"] == 7 * 3600          # the nap is not the shortest night
    assert s["avg_s"] == int(7.5 * 3600)
    assert (s["nights"], s["naps"]) == (2, 1)


def test_sleep_stats_empty_is_null():
    assert ds.sleep_stats([])["avg_s"] is None


# ── heart rate zones ─────────────────────────────────────────────────────

def test_hr_zones_use_the_cardio_bounds_and_cap_gaps():
    t0 = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    max_hr = 180.0
    pts = [
        (t0, 90.0),                               # Z1 (50%)
        (t0 + timedelta(minutes=2), 150.0),       # Z4 (83%)
        (t0 + timedelta(minutes=4), 150.0),
        (t0 + timedelta(hours=3), 90.0),          # 3h gap: not credited
    ]
    s = ds.hr_zone_stats(pts, max_hr, bucket_seconds=120)
    by = {z["zone"]: z for z in s["time_in_zone"]}
    assert by["Z1"]["seconds"] == 120
    assert by["Z4"]["seconds"] == 120
    assert by["Z5"]["seconds"] == 0
    assert s["tracked_s"] == 240
    # Boundaries are cardio.zone_bounds verbatim, not a client copy.
    assert [(z["lo_bpm"], z["hi_bpm"]) for z in s["time_in_zone"]] == [
        (b["lo_bpm"], b["hi_bpm"]) for b in zone_bounds(max_hr)]


def test_hr_histogram_counts_time_with_empty_bins_filled():
    t0 = datetime(2026, 9, 8, tzinfo=timezone.utc)
    pts = [(t0, 61.0), (t0 + timedelta(minutes=2), 72.0)]
    h = ds.hr_zone_stats(pts, 180.0, bucket_seconds=120)["histogram"]
    assert [b["lo"] for b in h] == [60, 65, 70]
    assert [b["minutes"] for b in h] == [2.0, 0.0, 2.0]


def test_hr_empty_trace_has_null_pct():
    s = ds.hr_zone_stats([], 180.0, 120)
    assert all(z["pct"] is None for z in s["time_in_zone"])
    assert s["histogram"] == []


# ── weight ───────────────────────────────────────────────────────────────

T = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _w(*kgs):
    return [(T + timedelta(days=i), kg) for i, kg in enumerate(kgs)]


def test_weight_no_goal_is_neutral_whatever_the_direction():
    assert ds.weight_stats(_w(100, 95), None)["tone"] == "neutral"
    assert ds.weight_stats(_w(95, 100), None)["tone"] == "neutral"


def test_weight_toward_goal_positive_away_caution():
    assert ds.weight_stats(_w(100, 97), 90)["tone"] == "positive"
    assert ds.weight_stats(_w(97, 100), 90)["tone"] == "caution"
    # A gain goal flips it.
    assert ds.weight_stats(_w(60, 63), 70)["tone"] == "positive"


def test_weight_inside_noise_band_is_neutral():
    assert ds.weight_stats(_w(100, 99.5), 90)["tone"] == "neutral"


def test_weight_caution_never_uses_a_crisis_word():
    tones = {ds.weight_tone(d, 100, 90) for d in (-5, -0.5, 0, 0.5, 5)}
    assert tones <= {"positive", "caution", "neutral"}


def test_weight_trend_is_fitted_against_time_not_index():
    # Two readings on day 0, one on day 10: evenly spaced by index this
    # would put the fitted end at a different value.
    pts = [(T, 100.0), (T + timedelta(hours=1), 100.0), (T + timedelta(days=10), 90.0)]
    tr = ds.weight_stats(pts, None)["trend"]
    assert tr["end_kg"] < 91.0 and tr["start_kg"] > 99.0
    assert tr["per_week_kg"] < 0


def test_weight_stats_are_kilograms_and_signed_goal_gap():
    s = ds.weight_stats(_w(100, 98), 90)
    assert s["latest_kg"] == 98 and s["delta_kg"] == -2 and s["goal_gap_kg"] == 8
    assert s["count"] == 2 and s["avg_kg"] == 99


def test_weight_empty_window():
    s = ds.weight_stats([], 90)
    assert s["count"] == 0 and s["latest_kg"] is None and s["tone"] == "neutral"


# ── wiring ───────────────────────────────────────────────────────────────

def _fn_src(path: pathlib.Path, name: str) -> str:
    text = path.read_text()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{name} not found in {path.name}")


def test_range_stats_reuses_summary_range_and_local_days():
    src = _fn_src(SRC / "api" / "summary.py", "summary_range_stats")
    assert "await summary_range(" in src, "stats must read the rows the chart draws"
    assert "local_today()" in src and "timezone.utc" not in src


def test_endpoints_attach_the_stat_blocks():
    q = SRC / "api" / "query.py"
    assert "hr_zone_stats(" in _fn_src(q, "get_heartrate")
    assert "hourly=hourly" in _fn_src(q, "get_steps")
    assert "weight_stats(" in _fn_src(q, "get_weight")


def test_weight_7d_and_30d_deltas_are_toned_by_the_goal():
    pts = [(T + timedelta(days=d), kg) for d, kg in [(0, 104), (25, 101), (31, 100)]]
    s = ds.weight_stats(pts, 90)
    assert s["delta_30d"]["delta_kg"] == -1 and s["delta_30d"]["tone"] == "positive"
    assert s["delta_7d"]["delta_kg"] == -1  # from day 25


def test_weight_rolling_mean_is_by_time():
    pts = [(T, 100.0), (T + timedelta(days=1), 102.0), (T + timedelta(days=20), 90.0)]
    r = ds.weight_stats(pts, None)["rolling_7d"]
    assert [x["kg"] for x in r] == [100.0, 101.0, 90.0]


def test_recomp_fat_gain_is_caution_not_a_crisis():
    bf = [(T + timedelta(days=i), 80.0 + i * 0.2, 20.0 + i * 0.3) for i in range(6)]
    rc = ds.weight_stats([(t, w) for t, w, _ in bf], None, body_fat=bf)["recomp"]
    assert rc["label"] == "Fat gain" and rc["tone"] == "caution"


def test_recomp_needs_five_readings():
    bf = [(T + timedelta(days=i), 80.0, 20.0) for i in range(4)]
    assert ds.weight_stats([(t, w) for t, w, _ in bf], None, body_fat=bf)["recomp"] is None
