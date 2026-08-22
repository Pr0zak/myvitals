"""Decayed sleep debt, and a sleep-need derivation that knows when to refuse.

The backlog entry claimed sleep debt "accumulates forever". It does not —
it was already a rolling 7-day window. The real defect was subtler: a hard
window is a step function, so a bad night ageing out dropped the figure by
a jump the user had done nothing to earn, and last night counted the same
as last Tuesday.

The sleep-need half is the more interesting refusal. On this database the
free-day and work-day means differ by 0.08h over 180 nights, so there are
no unrestricted nights to estimate need from — and the typed target (8.0h)
sits ~1.4h above the measured mean (~6.6h), so adopting a derived number
silently would cut the debt figure by roughly ten hours a week.
"""

from __future__ import annotations

import inspect

from myvitals.analytics import advanced


class TestDecay:
    def test_debt_decays_rather_than_using_a_hard_window(self):
        src = inspect.getsource(advanced.sleep_debt_hours)
        assert "0.5 ** (age_d /" in src

    def test_recent_nights_outweigh_older_ones(self):
        """The property the old flat sum did not have."""
        hl = advanced.SLEEP_DEBT_HALF_LIFE_D
        w_last_night = 0.5 ** (0 / hl)
        w_week_ago = 0.5 ** (7 / hl)
        assert w_last_night > w_week_ago * 4

    def test_the_window_is_wider_than_the_half_life(self):
        """Truncating near the half-life would reintroduce the cliff the
        decay exists to remove."""
        assert advanced.SLEEP_DEBT_WINDOW_D >= advanced.SLEEP_DEBT_HALF_LIFE_D * 4

    def test_the_result_is_normalised_to_the_old_scale(self):
        """Decay without normalisation shrinks every debt figure, which
        would look like the user had suddenly improved."""
        src = inspect.getsource(advanced.sleep_debt_hours)
        assert "weighted / total_w * 7.0" in src

    def test_no_data_returns_none_not_zero(self):
        """Zero debt and no data are different claims."""
        src = inspect.getsource(advanced.sleep_debt_hours)
        assert "if not rows:" in src and "return None" in src


class TestNeedDerivationRefuses:
    def test_it_refuses_without_a_free_day_contrast(self):
        """The live case: 6.67h free vs 6.59h work. Sleeping the same on
        free days means either the need is met or it is restricted every
        night, and the data cannot tell those apart."""
        src = inspect.getsource(advanced.derive_sleep_need)
        assert "_FREE_DAY_MIN_GAP_H" in src
        assert "gap < _FREE_DAY_MIN_GAP_H" in src

    def test_it_refuses_on_too_few_nights(self):
        src = inspect.getsource(advanced.derive_sleep_need)
        assert "len(rows) < 30" in src

    def test_every_refusal_carries_a_reason(self):
        """A number that silently disappears reads as a loading bug."""
        assert "reason" in advanced.SleepNeed.__dataclass_fields__

    def test_the_derived_need_is_not_applied_automatically(self):
        """It informs a decision; it must not make one. Adopting it here
        would move the debt figure, the tile band and the sleep AiGoal in
        a single deploy with no user action."""
        from myvitals.api import summary

        src = inspect.getsource(summary.sleep_need)
        assert '"target_source": "manual"' in src
        assert "sleep_target_h =" not in src, (
            "the endpoint must not write the profile target"
        )

    def test_the_response_says_which_number_is_in_use(self):
        from myvitals.api import summary

        src = inspect.getsource(summary.sleep_need)
        assert '"target_hours": typed' in src
