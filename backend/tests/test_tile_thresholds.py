"""Tile status semantics.

The tiles tell the user whether a number is good. That judgement has to be
pinned, because the failure mode is silent: a direction flipped on resting
HR would colour a *rising* resting heart rate green and nobody would notice
from the code alone.
"""
import pytest

from myvitals.analytics.tiles import (
    GOOD,
    TYPICAL,
    WATCH,
    Z_NOTABLE,
    _band_from_z,
    _pct_of_target,
)


# ── direction ─────────────────────────────────────────────────────────

def test_higher_is_better_metrics_reward_a_positive_z():
    status, reason = _band_from_z(1.5, higher_is_better=True)
    assert status == GOOD
    assert "above" in reason


def test_lower_is_better_metrics_reward_a_negative_z():
    """Resting HR: dropping below baseline is the GOOD outcome.

    This is the assertion that matters most in the file — get it backwards
    and a climbing resting heart rate reads as an improvement.
    """
    status, reason = _band_from_z(-1.5, higher_is_better=False)
    assert status == GOOD
    assert "below" in reason

    status, _ = _band_from_z(1.5, higher_is_better=False)
    assert status == WATCH


def test_the_middle_is_typical_for_both_directions():
    for higher in (True, False):
        assert _band_from_z(0.0, higher_is_better=higher)[0] == TYPICAL
        assert _band_from_z(0.9, higher_is_better=higher)[0] == TYPICAL
        assert _band_from_z(-0.9, higher_is_better=higher)[0] == TYPICAL


@pytest.mark.parametrize("z,higher,expected", [
    (Z_NOTABLE, True, GOOD),
    (Z_NOTABLE - 0.01, True, TYPICAL),
    (-Z_NOTABLE, True, WATCH),
    (-Z_NOTABLE, False, GOOD),
    (Z_NOTABLE, False, WATCH),
])
def test_boundaries_are_inclusive_on_the_notable_side(z, higher, expected):
    assert _band_from_z(z, higher_is_better=higher)[0] == expected


def test_reason_reports_the_magnitude_unsigned():
    # The word already carries the direction; a "-1.5σ below" reason reads
    # as a double negative.
    _, reason = _band_from_z(-1.5, higher_is_better=False)
    assert "1.5σ" in reason and "-1.5" not in reason


# ── targets ───────────────────────────────────────────────────────────

def test_pct_of_target_is_safe_when_no_target_is_set():
    # A user with the goal cleared must not crash the whole grid.
    assert _pct_of_target(5000, 0) == 0.0


def test_pct_of_target_is_a_percentage():
    assert _pct_of_target(5000, 10000) == pytest.approx(50.0)
    assert _pct_of_target(12000, 10000) == pytest.approx(120.0)
