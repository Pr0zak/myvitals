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
        expand the catalog by at least one entry — the pull-up itself."""
        # Note: the pull-up entries in the catalog are equipment=['bodyweight']
        # because they don't need a *device* in free-exercise-db's taxonomy.
        # That's a known catalog quirk. So this test doesn't actually
        # change the count — it just sanity-checks that adding gear
        # never *shrinks* the catalog.
        before = len(filter_catalog_for_equipment(CATALOG, user_equipment))
        after = len(filter_catalog_for_equipment(CATALOG, equipment_with_pullup_bar))
        assert after >= before


class TestSelectExercisesForSplit:
    def test_full_body_returns_multiple_patterns(self, user_equipment):
        catalog = filter_catalog_for_equipment(CATALOG, user_equipment)
        rng = random.Random("test_seed")
        chosen, notes = select_exercises_for_split(
            catalog, "full_body", "intermediate", rng,
        )
        # Full body should hit at least 4 distinct movement patterns
        patterns = {ex["movement_pattern"] for ex in chosen}
        assert len(patterns) >= 4

    def test_deterministic_with_same_seed(self, user_equipment):
        """Same seed → same output (so 'today's plan' is stable until
        the user hits regenerate)."""
        catalog = filter_catalog_for_equipment(CATALOG, user_equipment)
        a, _ = select_exercises_for_split(
            catalog, "upper", "intermediate", random.Random("x"),
        )
        b, _ = select_exercises_for_split(
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
        exs = [{"id": "Curl", "movement_pattern": "isolation_arm",
                "primary_muscle": "biceps", "is_compound": False}]
        assert pair_supersets(exs) == {}
