"""Epley estimated-1RM helper (e1RM-1)."""
from __future__ import annotations

from myvitals.analytics.strength import estimate_1rm


def test_single_rep_returns_weight():
    assert estimate_1rm(185.0, 1) == 185.0


def test_epley_multi_rep():
    # 100 * (1 + 5/30) = 116.666… -> 116.7
    assert estimate_1rm(100.0, 5) == 116.7
    # 100 * (1 + 12/30) = 140.0
    assert estimate_1rm(100.0, 12) == 140.0


def test_reps_capped_at_12():
    # 20 reps is capped to 12, so same as 12 reps
    assert estimate_1rm(100.0, 20) == estimate_1rm(100.0, 12) == 140.0


def test_monotonic_in_reps_up_to_cap():
    seq = [estimate_1rm(100.0, r) for r in range(1, 13)]
    assert seq == sorted(seq)


def test_invalid_inputs_return_none():
    assert estimate_1rm(None, 5) is None
    assert estimate_1rm(100.0, None) is None
    assert estimate_1rm(0.0, 5) is None
    assert estimate_1rm(-10.0, 5) is None
    assert estimate_1rm(100.0, 0) is None
    assert estimate_1rm(100.0, -3) is None


def test_returns_one_decimal():
    v = estimate_1rm(102.5, 7)
    assert v == round(102.5 * (1 + 7 / 30), 1)
