"""DEDUP-1 — duplicate suppression + near-duplicate co-selection guard."""
import random

from myvitals.analytics.strength import (
    CATALOG,
    CATALOG_BY_ID,
    SPLIT_SLOTS,
    SUPERSEDED_EXERCISE_IDS,
    filter_catalog_for_equipment,
    is_near_duplicate,
    select_exercises_for_split,
)

EQUIP = {
    "dumbbells": {"type": "fixed_pairs",
                  "pairs_lb": [10, 15, 20, 25, 30, 35, 40, 45, 50]},
    "wrist_weights_lb": [1.5, 2.0],
    "bench": {"flat": True, "incline": True, "decline": False},
    "barbell": False, "squat_rack": False, "pull_up_bar": False,
    "cable_stack": False, "kettlebells_lb": [], "resistance_bands": False,
    "bodyweight": True,
}


# ── superseded ids ────────────────────────────────────────────────────

def test_superseded_ids_and_their_targets_all_exist():
    for dead, canonical in SUPERSEDED_EXERCISE_IDS.items():
        assert dead in CATALOG_BY_ID, f"{dead} not in catalog"
        assert canonical in CATALOG_BY_ID, f"{canonical} not in catalog"


def test_superseded_ids_stay_resolvable_for_history():
    # History rows reference these; dropping them would break name/image
    # lookup and PR tracking on past sessions.
    for dead in SUPERSEDED_EXERCISE_IDS:
        assert CATALOG_BY_ID[dead].get("name")


def test_superseded_ids_are_excluded_from_selection():
    pool = {e["id"] for e in filter_catalog_for_equipment(CATALOG, EQUIP)}
    for dead in SUPERSEDED_EXERCISE_IDS:
        assert dead not in pool
    # …and the survivor is still selectable, or we'd have lost the movement.
    for canonical in SUPERSEDED_EXERCISE_IDS.values():
        assert canonical in pool


def test_superseded_map_has_no_chains_or_cycles():
    # A → B where B is itself superseded would silently drop both.
    for dead, canonical in SUPERSEDED_EXERCISE_IDS.items():
        assert canonical not in SUPERSEDED_EXERCISE_IDS
        assert canonical != dead


# ── near-duplicate detection ──────────────────────────────────────────

def test_the_pair_that_shipped_together_is_detected():
    a = CATALOG_BY_ID["Incline_Dumbbell_Row"]
    b = CATALOG_BY_ID["Dumbbell_Incline_Row"]
    assert is_near_duplicate(a, b)


def test_different_muscles_are_never_near_duplicates():
    a = {"name": "Dumbbell Row", "primary_muscle": "back",
         "movement_pattern": "horizontal_pull"}
    b = {"name": "Dumbbell Row", "primary_muscle": "quadriceps",
         "movement_pattern": "horizontal_pull"}
    assert not is_near_duplicate(a, b)


def test_different_patterns_are_never_near_duplicates():
    a = {"name": "Dumbbell Press", "primary_muscle": "chest",
         "movement_pattern": "horizontal_push"}
    b = {"name": "Dumbbell Press", "primary_muscle": "chest",
         "movement_pattern": "vertical_push"}
    assert not is_near_duplicate(a, b)


def test_shared_generic_words_alone_do_not_trigger():
    # Every dumbbell move shares "dumbbell" — name overlap alone is far
    # too blunt a signal.
    a = {"name": "Dumbbell Bench Press", "primary_muscle": "chest",
         "movement_pattern": "horizontal_push"}
    b = {"name": "Dumbbell Floor Fly Wide Grip", "primary_muscle": "chest",
         "movement_pattern": "horizontal_push"}
    assert not is_near_duplicate(a, b)


def test_empty_names_do_not_crash_or_match():
    a = {"name": "", "primary_muscle": "chest", "movement_pattern": "p"}
    b = {"name": "", "primary_muscle": "chest", "movement_pattern": "p"}
    assert not is_near_duplicate(a, b)


# ── the guard, end to end ─────────────────────────────────────────────

def _generate(focus: str, seed: int):
    pool = filter_catalog_for_equipment(CATALOG, EQUIP)
    chosen, _slots, _notes = select_exercises_for_split(
        pool, focus, "intermediate", random.Random(seed),
    )
    return chosen


def test_no_session_contains_a_near_duplicate_pair():
    for focus in ("push", "pull", "legs", "upper", "lower", "full_body"):
        for seed in range(40):
            chosen = _generate(focus, seed)
            for i, a in enumerate(chosen):
                for b in chosen[i + 1:]:
                    assert not is_near_duplicate(a, b), (
                        f"{focus} seed={seed}: {a['id']} ~ {b['id']}"
                    )


def test_guard_does_not_starve_any_slot():
    # The guard is a preference, not a filter — every focus must still
    # fill as many slots as it did before.
    for focus in ("push", "pull", "legs", "upper", "lower", "full_body"):
        for seed in range(20):
            chosen = _generate(focus, seed)
            assert len(chosen) == len(SPLIT_SLOTS[focus]), (
                f"{focus} seed={seed} filled {len(chosen)}/"
                f"{len(SPLIT_SLOTS[focus])} slots"
            )


def test_selection_is_still_deterministic():
    assert [e["id"] for e in _generate("pull", 7)] == \
           [e["id"] for e in _generate("pull", 7)]
