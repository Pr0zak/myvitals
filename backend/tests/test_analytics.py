"""Pearson correlation helper — the math behind the AI 'correlations' card and
the /analytics/correlate endpoint. Previously untested.
"""
from __future__ import annotations

import math

from myvitals.api.analytics import _pearson


def test_perfect_positive():
    r = _pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
    assert r is not None and math.isclose(r, 1.0, abs_tol=1e-9)


def test_perfect_negative():
    r = _pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2])
    assert r is not None and math.isclose(r, -1.0, abs_tol=1e-9)


def test_known_moderate():
    # num=10, dx2=10, dy2=14.8 → r = 10/sqrt(148) ≈ 0.8219949365
    r = _pearson([1, 2, 3, 4, 5], [2, 1, 4, 3, 6])
    assert r is not None and math.isclose(r, 0.8219949365, abs_tol=1e-6)


def test_too_few_points_returns_none():
    assert _pearson([1, 2], [3, 4]) is None


def test_zero_variance_returns_none():
    # Constant y → denominator 0 → undefined correlation, not a crash.
    assert _pearson([1, 2, 3], [5, 5, 5]) is None
    assert _pearson([7, 7, 7], [1, 2, 3]) is None
