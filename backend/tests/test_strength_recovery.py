"""Recovery-aware adjustment: rest-day gate, deload factor."""
from __future__ import annotations

import pytest

from myvitals.analytics.strength import RecoveryInputs


class TestIsBlocking:
    def test_no_signals_does_not_block(self):
        r = RecoveryInputs()
        assert r.is_blocking() == (False, None)

    def test_very_low_recovery_blocks(self):
        blocked, reason = RecoveryInputs(recovery_score=20).is_blocking()
        assert blocked is True
        assert "recovery" in reason.lower()

    def test_borderline_recovery_does_not_block(self):
        """40 is below the deload threshold but not the rest-day threshold."""
        assert RecoveryInputs(recovery_score=40).is_blocking()[0] is False

    def test_sleep_deficit_no_longer_blocks(self):
        """v0.7.269: sleep was removed as a rest-day driver — Pixel Watch
        sleep duration was unreliable enough to flip legitimate strength
        days into yoga. Even a severe deficit is informational only now."""
        assert RecoveryInputs(sleep_h=3.5).is_blocking() == (False, None)

    def test_5h_sleep_does_not_block(self):
        """Sleep drives neither a block nor a deload post-v0.7.269."""
        assert RecoveryInputs(sleep_h=5.0).is_blocking()[0] is False


class TestDeloadFactor:
    def test_no_signals_means_no_deload(self):
        assert RecoveryInputs().deload_factor() == 1.0

    def test_recovery_below_40_drops_15pct(self):
        f = RecoveryInputs(recovery_score=35).deload_factor()
        assert f == pytest.approx(0.85)

    def test_recovery_below_60_drops_8pct(self):
        f = RecoveryInputs(recovery_score=55).deload_factor()
        assert f == pytest.approx(0.92)

    def test_sleep_no_longer_affects_deload(self):
        """v0.7.269: sleep dropped as a deload input. A recovery-only
        deload (55 → 0.92) is unchanged by any sleep_h value."""
        f = RecoveryInputs(recovery_score=55, sleep_h=4.5).deload_factor()
        assert f == pytest.approx(0.92, abs=0.001)

    def test_low_readiness_drops_10pct(self):
        f = RecoveryInputs(readiness_score=25).deload_factor()
        assert f == pytest.approx(0.90)

    def test_all_three_compound(self):
        """Worst case: low recovery + low sleep + low readiness."""
        f = RecoveryInputs(
            recovery_score=35, sleep_h=4.5, readiness_score=25,
        ).deload_factor()
        # Note: rest-day threshold (recovery<25, sleep<4) wouldn't fire
        # at these values, so deload still applies
        assert 0.6 < f < 0.85
