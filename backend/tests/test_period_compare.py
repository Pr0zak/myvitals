"""Period-over-period comparison (CMP-1).

The interesting cases here are all about *not* lying with an average:
missing days, inverted metrics, and the weekday alignment of a
year-ago comparison.
"""

from __future__ import annotations

from datetime import date

import pytest

from myvitals.analytics import compare


def _rows(start: date, n: int, **series):
    """Build n consecutive daily rows; series values may contain None."""
    out = []
    for i in range(n):
        row = {"date": str(start.fromordinal(start.toordinal() + i))}
        for k, vals in series.items():
            row[k] = vals[i]
        out.append(row)
    return out


class TestBaselineWindow:
    def test_previous_is_the_adjacent_block_of_equal_length(self):
        since, until = date(2026, 8, 15), date(2026, 8, 21)
        b_since, b_until = compare.baseline_window(since, until, "previous")
        assert b_until == date(2026, 8, 14), "baseline must end the day before"
        assert (b_until - b_since).days == (until - since).days
        assert b_since == date(2026, 8, 8)

    def test_previous_windows_do_not_overlap(self):
        since, until = date(2026, 8, 15), date(2026, 8, 21)
        b_since, b_until = compare.baseline_window(since, until, "previous")
        assert b_until < since, "an overlapping baseline double-counts days"

    def test_last_year_preserves_weekday(self):
        """364 days, not 365 — this is the whole point.

        A 365-day shift moves the window by one weekday, so a Mon-Sun
        window lands on Sun-Sat and the comparison silently swaps a
        weekday for a weekend day. For steps and training load that is a
        systematic bias, not noise.
        """
        since, until = date(2026, 8, 17), date(2026, 8, 23)  # Mon-Sun
        assert since.weekday() == 0 and until.weekday() == 6
        b_since, b_until = compare.baseline_window(since, until, "last_year")
        assert b_since.weekday() == 0, "baseline must start on the same weekday"
        assert b_until.weekday() == 6
        assert (until - b_until).days == 364

    def test_last_year_keeps_window_length(self):
        since, until = date(2026, 8, 1), date(2026, 8, 30)
        b_since, b_until = compare.baseline_window(since, until, "last_year")
        assert (b_until - b_since).days == (until - since).days


class TestDirection:
    def test_falling_resting_hr_is_an_improvement(self):
        """The inversion that client-side code kept getting wrong."""
        cur = _rows(date(2026, 8, 15), 7, rhr=[55] * 7)
        base = _rows(date(2026, 8, 8), 7, rhr=[60] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("rhr",))
        assert out["rhr"]["delta"] == -5.0
        assert out["rhr"]["direction"] == "improved"
        assert out["rhr"]["better"] == "lower"

    def test_falling_hrv_is_not_an_improvement(self):
        cur = _rows(date(2026, 8, 15), 7, hrv=[40] * 7)
        base = _rows(date(2026, 8, 8), 7, hrv=[50] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("hrv",))
        assert out["hrv"]["direction"] == "worse"

    def test_rising_fatigue_is_worse(self):
        cur = _rows(date(2026, 8, 15), 7, atl=[80] * 7)
        base = _rows(date(2026, 8, 8), 7, atl=[60] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("atl",))
        assert out["atl"]["direction"] == "worse"

    def test_change_invisible_at_display_precision_reads_flat(self):
        cur = _rows(date(2026, 8, 15), 7, rhr=[60.02] * 7)
        base = _rows(date(2026, 8, 8), 7, rhr=[60.0] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("rhr",))
        assert out["rhr"]["direction"] == "flat"


class TestMissingData:
    def test_missing_days_are_skipped_not_zero_filled(self):
        """A day the watch was not worn must not be averaged in as zero.

        Zero-filling four missing days here would put the mean at 25.7
        instead of 60, inventing a dramatic 'improvement' in resting HR
        out of nothing but a charger.
        """
        cur = _rows(
            date(2026, 8, 15), 7,
            rhr=[60, None, None, 60, None, None, 60],
        )
        base = _rows(date(2026, 8, 8), 7, rhr=[60] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("rhr",))
        assert out["rhr"]["current"] == 60.0
        assert out["rhr"]["n_current"] == 3

    def test_thin_coverage_is_reported_as_insufficient(self):
        cur = _rows(
            date(2026, 8, 15), 7,
            rhr=[60, None, None, None, None, None, 60],
        )
        base = _rows(date(2026, 8, 8), 7, rhr=[62] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("rhr",))
        assert out["rhr"]["sufficient"] is False, (
            "2 of 7 days should not be presented as a comparable week"
        )
        # ...but the number is still returned, so the client can show it muted
        # rather than the row vanishing.
        assert out["rhr"]["current"] == 60.0

    def test_full_coverage_is_sufficient(self):
        cur = _rows(date(2026, 8, 15), 7, rhr=[60] * 7)
        base = _rows(date(2026, 8, 8), 7, rhr=[62] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("rhr",))
        assert out["rhr"]["sufficient"] is True

    def test_metric_absent_entirely_still_emits_a_stable_row(self):
        """The row must exist with nulls, not disappear.

        If metrics vanish from the response the client's table reflows as
        data arrives, which reads as a rendering bug.
        """
        cur = _rows(date(2026, 8, 15), 7, rhr=[None] * 7)
        base = _rows(date(2026, 8, 8), 7, rhr=[None] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("rhr",))
        assert "rhr" in out
        assert out["rhr"]["current"] is None
        assert out["rhr"]["direction"] is None
        assert out["rhr"]["sufficient"] is False

    def test_empty_baseline_does_not_divide_by_zero(self):
        cur = _rows(date(2026, 8, 15), 7, rhr=[60] * 7)
        out = compare.compare_windows(cur, [], window_days=7, keys=("rhr",))
        assert out["rhr"]["pct_change"] is None
        assert out["rhr"]["delta"] is None

    def test_zero_baseline_does_not_divide_by_zero(self):
        cur = _rows(date(2026, 8, 15), 7, steps=[5000] * 7)
        base = _rows(date(2026, 8, 8), 7, steps=[0] * 7)
        out = compare.compare_windows(cur, base, window_days=7, keys=("steps",))
        assert out["steps"]["pct_change"] is None
        assert out["steps"]["delta"] == 5000


class TestShape:
    def test_every_metric_declares_a_direction_sense(self):
        for spec in compare.COMPARE_METRICS:
            assert spec.better in ("higher", "lower", "context"), (
                f"{spec.key} declares an unknown 'better' value, so no client "
                "can decide how to colour it"
            )

    def test_steps_round_to_whole_numbers(self):
        cur = _rows(date(2026, 8, 15), 3, steps=[5000, 5001, 5002])
        base = _rows(date(2026, 8, 12), 3, steps=[4000] * 3)
        out = compare.compare_windows(cur, base, window_days=3, keys=("steps",))
        assert out["steps"]["current"] == 5001, "steps must not carry decimals"

    def test_unknown_keys_are_ignored_rather_than_raising(self):
        cur = _rows(date(2026, 8, 15), 3, rhr=[60] * 3)
        out = compare.compare_windows(
            cur, cur, window_days=3, keys=("rhr", "not_a_metric"),
        )
        assert set(out) == {"rhr"}

    @pytest.mark.parametrize("vs", ["previous", "last_year"])
    def test_baseline_window_is_always_strictly_before_current(self, vs):
        since, until = date(2026, 8, 15), date(2026, 8, 21)
        b_since, b_until = compare.baseline_window(since, until, vs)
        assert b_until < since


class TestContextualMetrics:
    """Bodyweight has no universal good direction.

    Colouring a weight change green or red requires knowing whether the
    user is cutting or bulking. The app does not know, so it must not
    guess — it reports the delta and stays neutral. Getting this wrong is
    worse than showing nothing: it tells a user gaining muscle that they
    are failing.
    """

    def test_weight_change_is_neutral_not_good_or_bad(self):
        cur = _rows(date(2026, 8, 15), 7, weight_kg=[82.0] * 7)
        base = _rows(date(2026, 8, 8), 7, weight_kg=[80.0] * 7)
        out = compare.compare_windows(
            cur, base, window_days=7, keys=("weight_kg",),
        )
        assert out["weight_kg"]["direction"] == "neutral"
        assert out["weight_kg"]["better"] == "context"
        assert out["weight_kg"]["delta"] == 2.0, "the number is still reported"

    def test_weight_loss_is_also_neutral(self):
        cur = _rows(date(2026, 8, 15), 7, weight_kg=[78.0] * 7)
        base = _rows(date(2026, 8, 8), 7, weight_kg=[80.0] * 7)
        out = compare.compare_windows(
            cur, base, window_days=7, keys=("weight_kg",),
        )
        assert out["weight_kg"]["direction"] == "neutral"

    def test_unchanged_contextual_metric_is_still_flat(self):
        """Flat wins over neutral — no change is no change either way."""
        cur = _rows(date(2026, 8, 15), 7, weight_kg=[80.0] * 7)
        base = _rows(date(2026, 8, 8), 7, weight_kg=[80.0] * 7)
        out = compare.compare_windows(
            cur, base, window_days=7, keys=("weight_kg",),
        )
        assert out["weight_kg"]["direction"] == "flat"

    def test_only_bodyweight_metrics_are_contextual(self):
        """Everything else must commit to a direction.

        If a physiological metric drifts into "context" it stops being
        colourable, which is a silent downgrade of the page.
        """
        contextual = {s.key for s in compare.COMPARE_METRICS if s.better == "context"}
        assert contextual == {"weight_kg", "body_fat_pct"}
