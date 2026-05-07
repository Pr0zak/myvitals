"""Micro-loader-aware weight rounder.

The user owns 5–45 lb DB pairs in 5s plus wrist weights 1/1.5/2/3 lb.
Combinations of wrist weights stack: e.g. 1+2 = 3, 1.5+2 = 3.5, 1+1.5+2 = 4.5.
"""
from __future__ import annotations

import pytest

from myvitals.analytics.strength import (
    round_weight, valid_dumbbell_loads, progress_from_rating,
)


class TestValidDumbbellLoads:
    def test_no_dumbbells_returns_empty(self):
        assert valid_dumbbell_loads([], [1, 2, 3]) == []

    def test_no_wrist_weights_returns_pairs_only(self):
        loads = valid_dumbbell_loads([5, 10, 15], [])
        assert loads == [5.0, 10.0, 15.0]

    def test_user_inventory_has_micro_resolution_between_pairs(self):
        """5 lb + (subsets of {1, 1.5, 2, 3}) covers fine increments
        between 5 and 10 lb."""
        loads = valid_dumbbell_loads(
            [5, 10, 15, 20, 25, 30, 35, 40, 45],
            [1, 1.5, 2, 3],
        )
        # Between 5 and 10 lb, the user can hit:
        # 5, 6 (5+1), 6.5 (5+1.5), 7 (5+2), 7.5 (5+1+1.5),
        # 8 (5+3 or 5+1+2), 8.5 (5+1.5+2), 9 (5+1+3 or 5+1.5+2.5? no),
        # 9.5 (5+1.5+3), 10 (5+2+3, but also next pair)
        between_5_and_10 = sorted([v for v in loads if 5 < v < 10])
        # Should have at least 5 distinct half-pound steps
        assert len(between_5_and_10) >= 5
        # Spot-check known sums
        for expected in (6, 6.5, 7, 7.5, 8, 9, 9.5):
            assert expected in loads, f"{expected} should be loadable"

    def test_max_load_is_top_pair_plus_all_wrist_weights(self):
        """45 lb DB + 1 + 1.5 + 2 + 3 = 52.5 lb is the absolute ceiling."""
        loads = valid_dumbbell_loads([45], [1, 1.5, 2, 3])
        assert max(loads) == pytest.approx(52.5)


class TestRoundWeight:
    def test_no_dumbbells_returns_none(self):
        assert round_weight(20, [], []) is None

    def test_target_below_lightest_clamps_to_lightest(self, user_equipment):
        """Asking for 3 lb on a setup whose lightest pair is 5 lb."""
        e = user_equipment
        result = round_weight(3, e["dumbbells"]["pairs_lb"], e["wrist_weights_lb"])
        assert result == 5.0

    def test_target_above_heaviest_clamps_to_heaviest(self, user_equipment):
        """Asking for 200 lb returns 52.5 (the absolute max)."""
        e = user_equipment
        result = round_weight(
            200, e["dumbbells"]["pairs_lb"], e["wrist_weights_lb"],
        )
        assert result == pytest.approx(52.5)

    def test_exact_pair_returns_pair(self, user_equipment):
        e = user_equipment
        for pair in e["dumbbells"]["pairs_lb"]:
            assert round_weight(pair, e["dumbbells"]["pairs_lb"],
                                e["wrist_weights_lb"]) == pair

    def test_27_lb_target_picks_loadable_27(self, user_equipment):
        """The marquee case: 25 lb DB + 2 lb wrist = 27 lb. The whole
        point of the micro-loader feature."""
        e = user_equipment
        result = round_weight(
            27, e["dumbbells"]["pairs_lb"], e["wrist_weights_lb"],
        )
        assert result == pytest.approx(27.0)

    def test_265_lb_target_picks_265(self, user_equipment):
        """25 + 1.5 = 26.5 — bridges the gap with sub-pound resolution."""
        e = user_equipment
        result = round_weight(
            26.5, e["dumbbells"]["pairs_lb"], e["wrist_weights_lb"],
        )
        assert result == pytest.approx(26.5)

    def test_prefers_lighter_on_tie(self, user_equipment):
        """Target equidistant between two valid loads → prefer lighter
        (don't recommend heavier than the user asked for)."""
        e = user_equipment
        # Between 25 and 26 (one wrist-weight away), exactly 25.5
        # 25.5 is loadable (25 + 1.5? wait no — 25 isn't a pair, ah yes it is)
        # 25 is a pair. 25 + 0.5 not loadable. Closest is 25 (0.5 away)
        # or 26 (25+1, also 0.5 away). Prefer 25 (lighter).
        result = round_weight(
            25.5, e["dumbbells"]["pairs_lb"], e["wrist_weights_lb"],
        )
        assert result == pytest.approx(25.5) or result == pytest.approx(25.0)

    def test_no_wrist_weights_falls_back_to_pair_resolution(self):
        """Without micro-loaders the target snaps to nearest 5 lb pair."""
        result = round_weight(27, [5, 10, 15, 20, 25, 30, 35], [])
        assert result == 25.0  # closer to 25 (2 away) than 30 (3 away)


class TestProgressFromRating:
    def test_failed_set_drops_75pct(self):
        assert progress_from_rating(100, 1.5, is_compound=True) == pytest.approx(92.5)
        assert progress_from_rating(100, 2.0, is_compound=False) == pytest.approx(92.5)

    def test_hard_holds_weight(self):
        assert progress_from_rating(50, 3.0, is_compound=True) == 50
        assert progress_from_rating(50, 4.0, is_compound=False) == 50

    def test_easy_compound_adds_10pct(self):
        assert progress_from_rating(100, 5.0, is_compound=True) == pytest.approx(110)

    def test_easy_isolation_adds_5pct(self):
        assert progress_from_rating(20, 5.0, is_compound=False) == pytest.approx(21)

    def test_threshold_at_4_5(self):
        """Avg rating of 4.4 = hold (still moderate); 4.5 = bump."""
        assert progress_from_rating(100, 4.4, is_compound=True) == 100
        assert progress_from_rating(100, 4.5, is_compound=True) == pytest.approx(110)
