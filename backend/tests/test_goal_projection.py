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


class TestNoiseGate:
    """SA-N5: the "fit is mostly noise" refusal has to look at the real
    measurements, not at the smoother built on top of them.

    ``project()`` used to compute R² on the 7-day moving average it had
    just built *from* the window — a trailing average is autocorrelated
    by construction, so that R² was scoring the smoother, not the data,
    and the refusal could not fire on real noisy data. See
    ``analytics/projection.py``'s ``_r2_against`` and the ``MIN_R2``
    derivation comment for the fix and the measurement behind the new
    threshold.
    """

    def test_smoothed_r2_no_longer_masks_real_scatter(self):
        """The production weight goal, reproduced verbatim (SA-N5 evidence).

        11 real weigh-ins spanning 17 days with a 4-day gap. Fit on the
        smoothed series alone reports R²=0.887 and a confident ETA; the
        same line explains only ~6% of the RAW measurements. Before the
        fix this returned ``is_fallback=False`` with an ETA around
        2028-01. This test fails without the fix.
        """
        today = date(2026, 9, 18)
        real_weigh_ins = [
            (date(2026, 8, 23), 115.439), (date(2026, 8, 24), 115.33),
            (date(2026, 8, 25), 115.338), (date(2026, 8, 26), 115.638),
            (date(2026, 8, 27), 115.15), (date(2026, 8, 31), 113.58),
            (date(2026, 9, 1), 113.37), (date(2026, 9, 2), 115.33),
            (date(2026, 9, 3), 115.848), (date(2026, 9, 4), 115.16),
            (date(2026, 9, 9), 114.629),
        ]
        p = projection.project(real_weigh_ins, target=None, today=today)
        assert p.is_fallback is True, (
            "a fit that explains ~6% of the raw measurements must refuse, "
            "not name a date four hundred-odd days out"
        )
        assert p.r2 is not None and p.r2 < 0.10
        assert "variation" in (p.fallback_reason or "").lower()

    def test_raw_r2_is_what_gets_reported(self):
        """The published ``r2`` must be the raw-data figure, not the
        smoothed-series figure — the same number feeds ``_confidence``,
        so an inflated r2 here would also mislabel a noisy fit "medium".
        """
        today = date(2026, 9, 18)
        real_weigh_ins = [
            (date(2026, 8, 23), 115.439), (date(2026, 8, 24), 115.33),
            (date(2026, 8, 25), 115.338), (date(2026, 8, 26), 115.638),
            (date(2026, 8, 27), 115.15), (date(2026, 8, 31), 113.58),
            (date(2026, 9, 1), 113.37), (date(2026, 9, 2), 115.33),
            (date(2026, 9, 3), 115.848), (date(2026, 9, 4), 115.16),
            (date(2026, 9, 9), 114.629),
        ]
        p = projection.project(real_weigh_ins, target=None, today=today)
        # The smoothed-series r2 for this exact input is ~0.89 (that is
        # the bug this finding is about); the raw one is under 0.10.
        assert p.r2 is not None and p.r2 < 0.15

    def test_real_1lb_per_week_loss_still_projects_at_measured_noise(self):
        """The gate must not over-correct into refusing everything.

        A genuine 1 lb/week loss, over a full 28-point daily window, with
        noise sampled at this project's own measured day-to-day weight
        scatter (~0.87 kg). This fit's raw R² lands at ~0.20 — comfortably
        past the re-derived MIN_R2=0.10, and (by design of this fixture)
        BELOW the old MIN_R2=0.30. If MIN_R2 is ever reverted to 0.30
        without re-deriving it, this genuine trend gets refused again —
        the same failure this fix exists to remove, just with the sign
        flipped. That is exactly the outcome SA-N5's correction warned
        against, so this is the test that catches it.
        """
        today = date(2026, 9, 18)
        slope_kg_per_day = -(0.45359237 / 7)  # -1 lb/week
        start = 115.0
        # Fixed noise draw (not random.random — must be reproducible),
        # amplitude tuned to this project's measured ~0.87 kg scatter.
        noise_kg = [
            -0.486, -0.792, -0.803, -0.321, 1.014, -0.104, 0.459, 0.126,
            -0.226, -1.908, 0.679, 0.687, 0.714, -0.84, 1.049, 0.115,
            -0.145, 0.585, 0.379, -0.159, 0.699, -1.276, -0.644, -0.425,
            1.122, 0.643, 0.53, -0.139,
        ]
        points = [
            (today - timedelta(days=27 - i),
             round(start + slope_kg_per_day * i + noise_kg[i], 3))
            for i in range(28)
        ]
        p = projection.project(points, target=None, today=today)
        assert p.is_fallback is False, (
            f"a real 1 lb/week loss at this project's own measured noise "
            f"level was refused (r2={p.r2}); MIN_R2 is too strict again"
        )
        assert p.r2 is not None and 0.10 <= p.r2 < 0.30
        assert p.per_week is not None and p.per_week < 0

    def test_pure_flat_noise_still_refuses_after_the_fix(self):
        """The original proposal's ask: a flat scatter must refuse even
        after smoothing papers over it. ``test_noisy_scatter_refuses``
        above already covers a clean alternating series; this uses the
        same amplitude but an irregular (non-alternating) pattern so
        smoothing cannot average it back toward a straight line either.
        """
        today = date(2026, 9, 18)
        wobble = [3.0, -2.0, 2.5, -3.0, 1.5, -2.5, 3.0, -1.5, 2.0, -3.0,
                  2.5, -2.0, 1.5, -3.0, 2.0, -2.5, 3.0, -1.5, 2.5, -2.0,
                  1.5, -3.0, 2.0, -2.5, 3.0, -1.5, 2.5, -2.0]
        points = [
            (today - timedelta(days=27 - i), 80.0 + wobble[i])
            for i in range(28)
        ]
        p = projection.project(points, target=None, today=today)
        assert p.is_fallback is True
        assert p.r2 is not None and p.r2 < projection.MIN_R2


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
