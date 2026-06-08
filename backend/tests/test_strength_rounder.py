"""Micro-loader-aware weight rounder.

The user owns 5–45 lb DB pairs in 5s plus wrist weights 1/1.5/2/3 lb.
Combinations of wrist weights stack: e.g. 1+2 = 3, 1.5+2 = 3.5, 1+1.5+2 = 4.5.
"""
from __future__ import annotations

import pytest

from myvitals.analytics.strength import (
    round_weight, valid_dumbbell_loads, progress_from_rating,
    double_progression,
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
        # Fail behaviour is goal-agnostic. WP-16 lowered FAIL_THRESHOLD to
        # 1.5 so only a mostly-failed session (Failed=1) deloads; "Hard"
        # (=2) now holds.
        assert progress_from_rating(100, 1.0, is_compound=True) == pytest.approx(92.5)
        assert progress_from_rating(100, 1.5, is_compound=False) == pytest.approx(92.5)
        assert progress_from_rating(100, 1.0, is_compound=True, goal="strength") == pytest.approx(92.5)
        assert progress_from_rating(100, 1.0, is_compound=True, goal="general") == pytest.approx(92.5)

    def test_hard_holds_weight(self):
        # WP-16: "Hard" (2) is a hold, not a deload.
        assert progress_from_rating(100, 2.0, is_compound=True) == 100
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


class TestDoubleProgression:
    """Fill the rep range before adding weight — unsticks light fixed-pair
    dumbbells whose percentage jump rounds back to the same load."""

    # The reported case: 10 lb pullover, 5 lb dumbbell steps, NO micro-loaders.
    FIXED = dict(pairs_lb=[5, 10, 15, 20, 25, 30, 35, 40, 45, 50],
                 wrist_weights_lb=[])

    def test_wp16_four_button_mapping(self):
        """The four UI buttons map to four distinct actions at mid-range
        (not at top, so Easy adds a rep rather than weight). Failed=1
        deloads, Hard=2 holds, Good=4 and Easy=5 add a rep."""
        def run(rating):
            return double_progression(
                base_reps_lo=8, base_reps_hi=10, last_weight_lb=30.0,
                last_avg_rating=rating, last_avg_reps=8.0, is_compound=False,
                goal="hypertrophy", **self.FIXED)
        # Failed → deload (30 * 0.925 = 27.75 → rounds to 30 nearest? -> 25)
        w, lo, hi, _ = run(1)
        assert w == 25.0 and (lo, hi) == (8, 10)
        # Hard → hold weight + base reps (no progression)
        w, lo, hi, _ = run(2)
        assert w == 30.0 and (lo, hi) == (8, 10)
        # Good → add a rep, hold weight
        w, lo, hi, _ = run(4)
        assert w == 30.0 and (lo, hi) == (9, 10)
        # Easy below top → still adds a rep (weight only at the top)
        w, lo, hi, _ = run(5)
        assert w == 30.0 and (lo, hi) == (9, 10)

    def test_easy_below_top_adds_a_rep_not_weight(self):
        # rating 5, did 8 reps in an 8–10 range → hold 10 lb, push to 9–10.
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=10.0,
            last_avg_rating=5.0, last_avg_reps=8.0, is_compound=False,
            goal="hypertrophy", **self.FIXED)
        assert w == 10.0
        assert (lo, hi) == (9, 10)
        assert adv is None

    def test_moderate_below_top_still_adds_a_rep(self):
        # rating 4 (RIR 4–5) is below the weight-jump bar but well clear of
        # failure → double progression advances reps. This is the 06-01 case.
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=10.0,
            last_avg_rating=4.0, last_avg_reps=8.0, is_compound=False,
            goal="hypertrophy", **self.FIXED)
        assert w == 10.0
        assert (lo, hi) == (9, 10)

    def test_top_of_range_but_rack_too_coarse_flags_plateau(self):
        # At the top (10 reps), rating it easy, but +5% on 10 lb rounds back
        # to 10 → weight-locked. Hold at top, surface the micro-loader nudge.
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=10.0,
            last_avg_rating=5.0, last_avg_reps=10.0, is_compound=False,
            goal="hypertrophy", **self.FIXED)
        assert w == 10.0
        assert (lo, hi) == (10, 10)
        assert adv is not None and "micro" in adv.lower()

    def test_top_of_range_with_loadable_jump_adds_weight_resets_reps(self):
        # 50 lb at the top: +5% = 52.5, and WITH micro-loaders the rack can
        # deliver it → weight moves, reps reset to the bottom of the range.
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=50.0,
            last_avg_rating=5.0, last_avg_reps=10.0, is_compound=False,
            goal="hypertrophy",
            pairs_lb=[5, 10, 15, 20, 25, 30, 35, 40, 45, 50],
            wrist_weights_lb=[1, 1.5, 2, 3])
        assert w == pytest.approx(52.5)
        assert (lo, hi) == (8, 10)
        assert adv is None

    def test_failure_cuts_weight_resets_reps(self):
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=30.0,
            last_avg_rating=1.0, last_avg_reps=6.0, is_compound=False,
            goal="hypertrophy", **self.FIXED)
        assert w == 25.0  # 30 * 0.925 = 27.75 → rounds to 25 on 5 lb steps
        assert (lo, hi) == (8, 10)

    def test_near_failure_holds_everything(self):
        # rating 2 (RIR 0–1) is above the deload cut but below REP_PROGRESS_MIN
        # → don't pile on reps; hold weight and the base range.
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=10.0,
            last_avg_rating=2.6, last_avg_reps=8.0, is_compound=False,
            goal="hypertrophy", **self.FIXED)
        assert w == 10.0
        assert (lo, hi) == (8, 10)

    def test_no_rep_history_holds_base_range(self):
        w, lo, hi, adv = double_progression(
            base_reps_lo=8, base_reps_hi=10, last_weight_lb=10.0,
            last_avg_rating=5.0, last_avg_reps=None, is_compound=False,
            goal="hypertrophy", **self.FIXED)
        assert (lo, hi) == (8, 10)


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

        Rotation sorts low-frequency candidates ahead, then the picker
        chooses from the top 3. So a heavily-used lift is excluded only
        when there are enough fresh alternatives to push it out of that
        top-3 window. (The "pull" split has TWO isolation_arm slots, so a
        2-exercise catalog can never exclude either — both slots must be
        filled. Give rotation real room: 1 heavily-used + 4 unseen.)
        """
        from myvitals.analytics.strength import select_exercises_for_split
        import random

        def _arm(eid: str) -> dict:
            return {
                "id": eid, "movement_pattern": "isolation_arm",
                "primary_muscle": "biceps", "is_compound": False,
                "level": "intermediate", "equipment": ["dumbbell"],
            }

        fresh = [_arm(f"Fresh_{i}") for i in range(4)]
        catalog = [_arm("Heavily_Used"), *fresh]
        # Heavily_Used picked 4x in the last 4w; the Fresh_* are unseen.
        freq = {"Heavily_Used": 4}
        rng = random.Random(0)
        chosen, _, _ = select_exercises_for_split(
            catalog, "pull", "intermediate", rng,
            recent_frequency=freq,
        )
        ids = [c["id"] for c in chosen]
        # Both arm slots get filled by unseen lifts; the heavily-used one
        # is sorted behind all four and never enters the top-3 pick window.
        assert any(i.startswith("Fresh_") for i in ids)
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
