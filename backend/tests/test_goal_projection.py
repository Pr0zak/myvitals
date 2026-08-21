"""Goal projection (GOAL-1).

Most of these test the *refusals*. A projection is a claim about someone's
future health made from a few weeks of noisy measurements, and the ways it
can be confidently wrong are more interesting than the happy path.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from myvitals.analytics import projection

TODAY = date(2026, 8, 21)


def series(values: list[float | None], end: date = TODAY) -> list[tuple[date, float]]:
    """(date, value) pairs ending today; None entries are omitted (sparse)."""
    n = len(values)
    out = []
    for i, v in enumerate(values):
        if v is None:
            continue
        out.append((end - timedelta(days=n - 1 - i), float(v)))
    return out


class TestRefusals:
    def test_no_data_at_all(self):
        p = projection.project([], target=70.0, today=TODAY)
        assert p.is_fallback is True
        assert p.eta_date is None
        assert "No data" in (p.fallback_reason or "")

    def test_too_few_points_to_fit(self):
        p = projection.project(
            series([80.0] * 5), target=70.0, today=TODAY,
        )
        assert p.is_fallback is True
        assert p.eta_date is None
        assert "need" in (p.fallback_reason or "").lower()

    def test_flat_trend_refuses_a_date(self):
        """A near-zero slope produces an ETA in the thousands of days.

        Reporting "you will reach your goal in the year 2071" is worse
        than saying the trend is flat, and dividing by an exactly-zero
        slope would raise.
        """
        p = projection.project(
            series([80.0] * 28), target=70.0, today=TODAY,
        )
        assert p.is_fallback is True
        assert p.eta_date is None
        assert "steady" in (p.fallback_reason or "").lower()

    def test_trending_away_from_target_refuses(self):
        """The arithmetic yields a NEGATIVE eta here — a date in the past.

        Gaining weight while targeting a loss must not render as "on track
        for [some date last month]".
        """
        rising = [80.0 + i * 0.1 for i in range(28)]
        p = projection.project(series(rising), target=70.0, today=TODAY)
        assert p.is_fallback is True
        assert p.eta_date is None
        assert "away" in (p.fallback_reason or "").lower()
        # The rate itself is still reported — it is real and useful.
        assert p.per_week is not None and p.per_week > 0

    def test_noisy_scatter_refuses(self):
        """A poor fit means the 'trend' is mostly noise."""
        noisy = [80.0 + (3.0 if i % 2 else -3.0) for i in range(28)]
        p = projection.project(series(noisy), target=70.0, today=TODAY)
        assert p.is_fallback is True
        assert p.eta_date is None

    def test_absurdly_distant_eta_refuses(self):
        """Two years of linear extrapolation is not a forecast."""
        crawl = [80.0 - i * 0.0005 for i in range(28)]
        p = projection.project(series(crawl), target=70.0, today=TODAY)
        assert p.eta_date is None
        assert p.is_fallback is True

    def test_refusal_always_carries_a_reason(self):
        """A projection that vanishes silently reads as a loading bug."""
        for pts, target in [
            ([], 70.0),
            (series([80.0] * 5), 70.0),
            (series([80.0] * 28), 70.0),
        ]:
            p = projection.project(pts, target=target, today=TODAY)
            assert p.is_fallback
            assert p.fallback_reason, "every refusal must explain itself"


class TestHappyPath:
    def test_steady_loss_projects_a_date(self):
        losing = [80.0 - i * 0.05 for i in range(28)]
        p = projection.project(series(losing), target=78.0, today=TODAY)
        assert p.is_fallback is False
        assert p.eta_date is not None
        assert p.per_day is not None and p.per_day < 0
        # per_day and per_week are rounded independently (4dp and 3dp), so
        # they agree to display precision rather than exactly.
        assert p.per_week == pytest.approx(p.per_day * 7, abs=1e-3)

    def test_already_at_target_is_zero_days(self):
        flat_at_target = [70.0 + (0.01 if i % 2 else -0.01) for i in range(28)]
        p = projection.project(series(flat_at_target), target=70.0, today=TODAY)
        # Either it reads as flat (no trend) or as already-there; both are
        # honest. What it must never do is name a future date.
        assert p.eta_days in (None, 0)

    def test_no_target_still_reports_the_rate(self):
        """The slope is useful even with no goal set."""
        losing = [80.0 - i * 0.05 for i in range(28)]
        p = projection.project(series(losing), target=None, today=TODAY)
        assert p.is_fallback is False
        assert p.per_week is not None
        assert p.eta_date is None, "no target means no date, not a guessed one"

    def test_confidence_scales_with_fit_and_sample_size(self):
        """A tight fit over 12 points is a weaker claim than over 28."""
        clean = [80.0 - i * 0.05 for i in range(28)]
        long_p = projection.project(series(clean), target=78.0, today=TODAY)
        short_p = projection.project(
            series(clean[-12:]), target=78.0, today=TODAY,
        )
        assert long_p.confidence == "high"
        assert short_p.confidence in ("medium", "low")


class TestSparseData:
    def test_missing_days_are_not_interpolated(self):
        """Sparse weigh-ins are normal and must not be filled in."""
        vals: list[float | None] = []
        for i in range(28):
            vals.append(80.0 - i * 0.05 if i % 3 == 0 else None)
        pts = series(vals)
        assert len(pts) < 28
        p = projection.project(pts, target=78.0, today=TODAY)
        assert p.n_points == len(pts)

    def test_points_outside_the_window_are_excluded(self):
        old = [(TODAY - timedelta(days=200 + i), 100.0) for i in range(30)]
        recent = series([80.0 - i * 0.05 for i in range(28)])
        p = projection.project(old + recent, target=78.0, today=TODAY)
        assert p.n_points == 28, "a 200-day-old cluster must not enter the fit"


class TestDeterministic:
    def test_streak_goal_uses_arithmetic_not_regression(self):
        """A sober streak gains exactly one day per day.

        Fitting a regression to it returns slope 1.0 and r² 1.0, which
        would dress arithmetic up as a statistical forecast.
        """
        p = projection.project_deterministic(30.0, 100.0, TODAY, per_day=1.0)
        assert p.method == "deterministic"
        assert p.eta_days == 70
        assert p.eta_date == (TODAY + timedelta(days=70)).isoformat()

    def test_already_past_target(self):
        p = projection.project_deterministic(120.0, 100.0, TODAY)
        assert p.eta_days == 0

    def test_no_target_declines(self):
        p = projection.project_deterministic(30.0, None, TODAY)
        assert p.is_fallback is True


class TestSmoothing:
    def test_moving_average_shortens_nothing(self):
        pts = series([float(i) for i in range(10)])
        sm = projection.moving_average(pts, 7)
        assert len(sm) == len(pts)

    def test_moving_average_damps_a_single_spike(self):
        clean = [70.0] * 20
        spiked = list(clean)
        spiked[10] = 90.0
        sm = projection.moving_average(series(spiked), 7)
        peak = max(v for _, v in sm)
        assert peak < 90.0, "a one-day water-weight spike must not dominate"

    def test_smoothing_makes_the_slope_stable_across_end_days(self):
        """Fitting raw values lets the slope swing with the final day.

        This is the reason smoothing exists here: a weekend step count or
        a post-meal weigh-in should not move the projected date.
        """
        base = [80.0 - i * 0.05 for i in range(28)]
        with_spike = list(base)
        with_spike[-1] += 1.5
        a = projection.project(series(base), target=78.0, today=TODAY)
        b = projection.project(series(with_spike), target=78.0, today=TODAY)
        assert a.per_day is not None and b.per_day is not None
        assert abs(a.per_day - b.per_day) < 0.02, (
            "one anomalous final reading moved the trend too much"
        )
