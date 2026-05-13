"""Workout generation: split selection, equipment filtering, exercise
selection determinism, superset pairing, vertical-pull advisory."""
from __future__ import annotations

import random

from myvitals.analytics.strength import (
    CATALOG, filter_catalog_for_equipment, pair_supersets,
    select_exercises_for_split, select_split,
)


class TestSelectSplit:
    def test_full_body_for_2_or_3_days(self):
        assert select_split(2, "auto", None) == "full_body"
        assert select_split(3, "auto", None) == "full_body"

    def test_upper_lower_for_4_days(self):
        assert select_split(4, "auto", None) == "upper"
        assert select_split(4, "auto", "upper") == "lower"
        assert select_split(4, "auto", "lower") == "upper"

    def test_ppl_for_5_or_6_days(self):
        assert select_split(5, "auto", None) == "push"
        assert select_split(6, "auto", None) == "push"
        assert select_split(5, "auto", "push") == "pull"
        assert select_split(5, "auto", "pull") == "legs"
        assert select_split(5, "auto", "legs") == "push"  # wraps

    def test_explicit_preference_wins(self):
        """Picking PPL with only 2 days/week does respect the choice."""
        assert select_split(2, "ppl", None) == "push"

    def test_unknown_last_split_starts_rotation(self):
        """If the rotation changed (e.g. user switched preferences), an
        old last_split that's no longer in rotation is ignored."""
        assert select_split(3, "auto", "push") == "full_body"

    def test_rotation_focuses_constant_covers_every_rotation(self):
        """`_ROTATION_FOCUSES` is the SQL filter used by
        last_split_for_user. If a new split is added to ROTATION but the
        filter constant isn't updated, intervening cardio/yoga will
        collapse the new rotation to its first element."""
        from myvitals.analytics.strength import ROTATION, _ROTATION_FOCUSES
        all_rotation_values = {v for vals in ROTATION.values() for v in vals}
        assert all_rotation_values <= set(_ROTATION_FOCUSES), (
            f"ROTATION values {all_rotation_values - set(_ROTATION_FOCUSES)} "
            "missing from _ROTATION_FOCUSES — last_split_for_user will "
            "skip them and collapse the rotation."
        )


class TestFilterCatalog:
    def test_user_setup_keeps_dumbbell_and_bodyweight(self, user_equipment):
        kept = filter_catalog_for_equipment(CATALOG, user_equipment)
        # Should keep most exercises (dumbbell + bench + bodyweight)
        assert len(kept) > 100, f"expected >100 kept, got {len(kept)}"
        # Every kept exercise must require nothing the user doesn't have
        for ex in kept:
            for tag in ex["equipment"]:
                assert tag in {"dumbbell", "bench", "bodyweight"}, \
                    f"{ex['id']} requires {tag}"

    def test_bare_setup_keeps_only_bodyweight(self, bare_equipment):
        kept = filter_catalog_for_equipment(CATALOG, bare_equipment)
        assert all(ex["equipment"] == ["bodyweight"] for ex in kept), \
            "non-BW exercise leaked through filter"
        # There are bodyweight exercises in the catalog (push-ups, planks, etc.)
        assert len(kept) > 0, "no bodyweight exercises kept — catalog wrong?"

    def test_pullup_bar_unlocks_pullups(
        self, user_equipment, equipment_with_pullup_bar,
    ):
        """Adding a pull-up bar to the user's setup at runtime should
        expand the catalog by exactly the bar-required exercises.
        Pull-ups, chin-ups, and hanging movements are tagged
        equipment=['bodyweight'] in free-exercise-db (the body is the
        load), but the bar is the gate — filter_catalog_for_equipment
        drops them by id when pull_up_bar=false."""
        from myvitals.analytics.strength import _BAR_REQUIRED_EXERCISES
        before_set = {e["id"] for e in filter_catalog_for_equipment(CATALOG, user_equipment)}
        after_set = {e["id"] for e in filter_catalog_for_equipment(CATALOG, equipment_with_pullup_bar)}
        unlocked = after_set - before_set
        assert unlocked == _BAR_REQUIRED_EXERCISES & {e["id"] for e in CATALOG}, (
            f"expected bar to unlock exactly {_BAR_REQUIRED_EXERCISES}, "
            f"got {unlocked}"
        )
        assert "Pullups" not in before_set, "Pullups leaked without a bar"
        assert "Pullups" in after_set, "Pullups missing when bar present"
        assert len(after_set) > len(before_set), "bar should strictly expand the catalog"


class TestSelectExercisesForSplit:
    def test_full_body_returns_multiple_patterns(self, user_equipment):
        catalog = filter_catalog_for_equipment(CATALOG, user_equipment)
        rng = random.Random("test_seed")
        chosen, _slots, notes = select_exercises_for_split(
            catalog, "full_body", "intermediate", rng,
        )
        # Full body should hit at least 4 distinct movement patterns
        patterns = {ex["movement_pattern"] for ex in chosen}
        assert len(patterns) >= 4

    def test_deterministic_with_same_seed(self, user_equipment):
        """Same seed → same output (so 'today's plan' is stable until
        the user hits regenerate)."""
        catalog = filter_catalog_for_equipment(CATALOG, user_equipment)
        a, _, _ = select_exercises_for_split(
            catalog, "upper", "intermediate", random.Random("x"),
        )
        b, _, _ = select_exercises_for_split(
            catalog, "upper", "intermediate", random.Random("x"),
        )
        assert [e["id"] for e in a] == [e["id"] for e in b]

    def test_different_seeds_can_differ(self, user_equipment):
        """Two distinct seeds should have a non-zero chance of differing.
        Run several to make the test robust against the rare case where
        both pick the highest-ranked candidate by chance."""
        catalog = filter_catalog_for_equipment(CATALOG, user_equipment)
        seeds = [str(i) for i in range(20)]
        outputs = {
            tuple(e["id"] for e in select_exercises_for_split(
                catalog, "upper", "intermediate", random.Random(s),
            )[0])
            for s in seeds
        }
        assert len(outputs) >= 2, "20 different seeds all produced same output"


class TestPairSupersets:
    def test_pairs_biceps_and_triceps(self):
        exs = [
            {"id": "Curl",     "movement_pattern": "isolation_arm",
             "primary_muscle": "biceps",  "is_compound": False},
            {"id": "Skullcrusher", "movement_pattern": "isolation_arm",
             "primary_muscle": "triceps", "is_compound": False},
            {"id": "Bench",    "movement_pattern": "horizontal_push",
             "primary_muscle": "chest",   "is_compound": True},
        ]
        pairs = pair_supersets(exs)
        assert pairs.get("Curl") == pairs.get("Skullcrusher")
        assert pairs["Curl"] is not None
        assert "Bench" not in pairs  # compound, doesn't superset

    def test_unpaired_isolation_returns_no_supersets(self):
        """Single isolation has no partner — falls through both passes."""
        exs = [{"id": "Curl", "movement_pattern": "isolation_arm",
                "primary_muscle": "biceps", "is_compound": False}]
        assert pair_supersets(exs) == {}

    def test_non_antagonist_isolations_still_pair(self):
        """Pass 2: any 2 distinct-muscle isolations pair up so the
        active-workout flow always uses superset cadence in the
        isolation block."""
        exs = [
            {"id": "LateralRaise", "movement_pattern": "isolation_shoulder",
             "primary_muscle": "shoulders", "is_compound": False},
            {"id": "CalfRaise", "movement_pattern": "isolation_leg",
             "primary_muscle": "calves", "is_compound": False},
        ]
        pairs = pair_supersets(exs)
        assert pairs.get("LateralRaise") == pairs.get("CalfRaise") != None  # noqa: E711

    def test_same_muscle_isolations_do_not_pair(self):
        """Two biceps isolations shouldn't superset — defeats the rest-
        while-the-other-muscle-works point."""
        exs = [
            {"id": "Curl",     "movement_pattern": "isolation_arm",
             "primary_muscle": "biceps", "is_compound": False},
            {"id": "Hammer",   "movement_pattern": "isolation_arm",
             "primary_muscle": "biceps", "is_compound": False},
        ]
        assert pair_supersets(exs) == {}
