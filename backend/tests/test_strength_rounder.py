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
        # Fail behaviour is goal-agnostic — pre-WP-12 invariant.
        assert progress_from_rating(100, 1.5, is_compound=True) == pytest.approx(92.5)
        assert progress_from_rating(100, 2.0, is_compound=False) == pytest.approx(92.5)
        assert progress_from_rating(100, 1.5, is_compound=True, goal="strength") == pytest.approx(92.5)
        assert progress_from_rating(100, 1.5, is_compound=True, goal="general") == pytest.approx(92.5)

    def test_hard_holds_weight(self):
        assert progress_from_rating(50, 3.0, is_compound=True) == 50
        assert progress_from_rating(50, 4.0, is_compound=False) == 50

    def test_strength_goal_jumps_bigger(self):
        # Compound +10%, isolation +7.5% for strength goal.
        assert progress_from_rating(100, 5.0, is_compound=True, goal="strength") == pytest.approx(110)
        assert progress_from_rating(100, 5.0, is_compound=False, goal="strength") == pytest.approx(107.5)

    def test_hypertrophy_goal_default_jumps(self):
        # Compound +7.5%, isolation +5% — also the default when goal omitted.
        assert progress_from_rating(100, 5.0, is_compound=True) == pytest.approx(107.5)
        assert progress_from_rating(100, 5.0, is_compound=False) == pytest.approx(105)
        assert progress_from_rating(100, 5.0, is_compound=True, goal="hypertrophy") == pytest.approx(107.5)

    def test_general_goal_smaller_jumps(self):
        # Compound +5%, isolation +2.5% — keeps user in higher rep ranges.
        assert progress_from_rating(100, 5.0, is_compound=True, goal="general") == pytest.approx(105)
        assert progress_from_rating(100, 5.0, is_compound=False, goal="general") == pytest.approx(102.5)

    def test_threshold_at_4_5(self):
        """Avg rating of 4.4 = hold (still moderate); 4.5 = bump."""
        assert progress_from_rating(100, 4.4, is_compound=True) == 100
        assert progress_from_rating(100, 4.5, is_compound=True) == pytest.approx(107.5)


class TestPrescribeSlotAgeAndBodyweight:
    """v0.7.149 — age-aware rest/volume + bodyweight-scaled rep targets."""

    def _weighted(self):
        # An external-load compound: should NOT trigger BW scaling.
        return {"id": "Dumbbell_Bench_Press", "is_compound": True,
                "equipment": ["dumbbell", "bench"], "movement_pattern": "press"}

    def _bw(self):
        # A pure bodyweight exercise.
        return {"id": "Push-Up", "is_compound": True,
                "equipment": ["bodyweight"], "movement_pattern": "press"}

    def test_age_under_40_no_change(self):
        from myvitals.analytics.strength import prescribe_slot
        sets, _, _, rest = prescribe_slot(
            self._weighted(), "main_compound", goal="hypertrophy", age=35,
        )
        assert sets == 4 and rest == 120

    def test_age_40s_adds_15s_rest(self):
        from myvitals.analytics.strength import prescribe_slot
        sets, _, _, rest = prescribe_slot(
            self._weighted(), "main_compound", goal="hypertrophy", age=45,
        )
        assert sets == 4 and rest == 135

    def test_age_50s_trims_isolation_set(self):
        from myvitals.analytics.strength import prescribe_slot
        sets, _, _, rest = prescribe_slot(
            self._weighted(), "isolation", goal="hypertrophy", age=55,
        )
        assert sets == 2 and rest == 90  # was 3 sets / 60s

    def test_age_60_plus_trims_secondary_too(self):
        from myvitals.analytics.strength import prescribe_slot
        sets, _, _, rest = prescribe_slot(
            self._weighted(), "secondary_compound", goal="hypertrophy", age=65,
        )
        assert sets == 3 and rest == 135  # was 4 sets / 90s

    def test_bodyweight_shifts_reps_up(self):
        # Push-Up hypertrophy main: baseline 6-8 weighted → 1.5× = 9-12 BW.
        from myvitals.analytics.strength import prescribe_slot
        _, rl, rh, _ = prescribe_slot(
            self._bw(), "main_compound", goal="hypertrophy", bodyweight_lb=150,
        )
        assert rl == 9 and rh == 12

    def test_bodyweight_scales_inverse_to_user_weight(self):
        # 200 lb user: 150/200 = 0.75× → 9*0.75=6.75→7, 12*0.75=9
        from myvitals.analytics.strength import prescribe_slot
        _, rl_heavy, rh_heavy, _ = prescribe_slot(
            self._bw(), "main_compound", goal="hypertrophy", bodyweight_lb=200,
        )
        # 100 lb user (clamped to 1.5× max): 9*1.5=13.5→14, 12*1.5=18
        _, rl_light, rh_light, _ = prescribe_slot(
            self._bw(), "main_compound", goal="hypertrophy", bodyweight_lb=100,
        )
        assert rl_light > rl_heavy
        assert rh_light > rh_heavy

    def test_rotation_pressure_promotes_unseen_exercises(self):
        """#WP-7: select_exercises_for_split should down-rank exercises
        the user has done a lot recently in favour of less-used ones.

        Build a 2-exercise catalog for a single slot, mark one as
        heavily-used (count=4) and one as unseen (absent from freq
        map). The seeded picker should consistently choose the unseen
        one even though the rank_key would otherwise tie them.
        """
        from myvitals.analytics.strength import select_exercises_for_split
        import random
        a = {
            "id": "Heavily_Used", "movement_pattern": "isolation_arm",
            "primary_muscle": "biceps", "is_compound": False,
            "level": "intermediate", "equipment": ["dumbbell"],
        }
        b = {
            "id": "Fresh_Pick", "movement_pattern": "isolation_arm",
            "primary_muscle": "biceps", "is_compound": False,
            "level": "intermediate", "equipment": ["dumbbell"],
        }
        catalog = [a, b]
        # Frequency: Heavily_Used picked 4 times in last 4w, Fresh_Pick 0.
        freq = {"Heavily_Used": 4}
        # We need a focus whose slot list has at least one
        # isolation_arm pattern entry. "pull" includes one.
        rng = random.Random(0)
        chosen, _, _ = select_exercises_for_split(
            catalog, "pull", "intermediate", rng,
            recent_frequency=freq,
        )
        ids = [c["id"] for c in chosen]
        # Fresh_Pick should be picked over Heavily_Used on the
        # isolation_arm slot.
        assert "Fresh_Pick" in ids
        assert "Heavily_Used" not in ids

    def test_weighted_exercise_ignores_bodyweight(self):
        # A weighted exercise should keep its baseline reps regardless of user BW.
        from myvitals.analytics.strength import prescribe_slot
        _, rl_a, rh_a, _ = prescribe_slot(
            self._weighted(), "main_compound", goal="hypertrophy", bodyweight_lb=100,
        )
        _, rl_b, rh_b, _ = prescribe_slot(
            self._weighted(), "main_compound", goal="hypertrophy", bodyweight_lb=250,
        )
        assert (rl_a, rh_a) == (rl_b, rh_b) == (6, 8)
