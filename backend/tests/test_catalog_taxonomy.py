"""Drift guard for the exercise catalog's vocabulary — TD-1.

The bundled catalog is hand-maintained across two files, and every consumer
downstream of it matches muscle names and movement patterns by exact string
equality. That combination fails silently: an exercise tagged with a muscle
the volume landmarks do not name credits zero sets, and an exercise tagged
with a pattern no split slot names can never be selected by the generator.
Neither failure raises, logs, or shows up on screen as anything other than a
number that is quietly too low.

These tests turn both classes of drift into a red build the next time someone
adds a row by hand. They deliberately assert against the *whole* catalog
rather than a fixture, because the catalog is the thing that drifts.

The bug they were written for: five real leg exercises (Walking Lunge,
Cossack Squat, Lateral Lunge, Dumbbell Step-Up, Dumbbell Sumo Squat) were
tagged `quads` against a landmark table that only knew `quadriceps`, so they
credited exactly zero volume; six Pilates rows tagged `core` did the same
against `abdominals`; and ten rows carried arm/chest/squat patterns the slot
tables had never heard of.
"""

from __future__ import annotations

import pytest

from myvitals.analytics import strength, taxonomy


# --------------------------------------------------------------------------
# Muscle vocabulary
# --------------------------------------------------------------------------

def _all_primary_tokens() -> set[str]:
    return {
        row["primary_muscle"]
        for row in strength.CATALOG
        if row.get("primary_muscle")
    }


def _all_secondary_tokens() -> set[str]:
    return {
        token
        for row in strength.CATALOG
        for token in (row.get("secondary_muscles") or [])
    }


def test_every_primary_muscle_credits_volume_or_is_exempt():
    """No exercise may credit volume to a bucket that does not exist.

    A token is acceptable only if it folds into MUSCLE_VOLUME_TARGETS or is
    listed in NON_VOLUME_MUSCLES — the qualities (flexibility, balance) that
    describe yoga work rather than a muscle. Anything else is a typo or a new
    muscle group, and both need a human decision.
    """
    orphans = {
        token
        for token in _all_primary_tokens()
        if taxonomy.credits_volume(token) is None
        and token not in taxonomy.NON_VOLUME_MUSCLES
    }
    assert not orphans, (
        f"primary_muscle tokens that credit no volume: {sorted(orphans)}. "
        "Add an entry to taxonomy.MUSCLE_ALIASES mapping each onto a landmark "
        "bucket, or to taxonomy.NON_VOLUME_MUSCLES if it genuinely describes a "
        "quality rather than a muscle."
    )


def test_every_secondary_muscle_credits_volume_or_is_exempt():
    """Secondary movers evaporate just as silently as primary ones.

    They are worth half a set each, so a whole tag going unrecognised is
    easier to miss and adds up faster across a catalog this size.
    """
    orphans = {
        token
        for token in _all_secondary_tokens()
        if taxonomy.credits_volume(token) is None
        and token not in taxonomy.NON_VOLUME_MUSCLES
    }
    assert not orphans, (
        f"secondary_muscles tokens that credit no volume: {sorted(orphans)}. "
        "Same fix as the primary case — extend taxonomy.MUSCLE_ALIASES."
    )


def test_catalog_is_normalised_at_import():
    """The fold happens once, at module load, not at each call site.

    If this fails, `taxonomy.normalise_catalog(CATALOG)` has been removed from
    or reordered within strength.py's module body, and every consumer is back
    to matching raw source spellings.
    """
    for row in strength.CATALOG:
        primary = row.get("primary_muscle")
        if primary:
            assert primary == taxonomy.canonical_muscle(primary), (
                f"{row['id']} still carries un-folded primary_muscle {primary!r}"
            )
        pattern = row.get("movement_pattern")
        if pattern:
            assert pattern == taxonomy.canonical_pattern(pattern), (
                f"{row['id']} still carries un-folded movement_pattern {pattern!r}"
            )


def test_no_row_credits_the_same_muscle_twice():
    """A muscle listed as both primary and secondary would be paid 1.5x.

    This can only happen after folding — a row tagging primary `abdominals`
    and secondary `core` looks fine in the source file and collides once the
    synonym resolves.
    """
    offenders = [
        row["id"]
        for row in strength.CATALOG
        if row.get("primary_muscle") in (row.get("secondary_muscles") or [])
    ]
    assert not offenders, (
        f"rows crediting their primary mover twice: {offenders}"
    )


# --------------------------------------------------------------------------
# Movement-pattern vocabulary
# --------------------------------------------------------------------------

def _selectable_patterns() -> set[str]:
    """Every pattern the generator can actually fill a slot with."""
    from_slots = {
        slot["pattern"]
        for slots in strength.SPLIT_SLOTS.values()
        for slot in slots
    }
    # FINISHER_PATTERNS is a local inside generate_plan, so it is restated
    # here. The test below asserts the two lists agree, which is what stops
    # this copy from becoming its own drift.
    from_finishers = {
        "isolation_leg", "isolation_core", "isolation_arm",
        "isolation_shoulder", "vertical_pull",
    }
    return from_slots | from_finishers


def test_every_movement_pattern_is_reachable():
    """An exercise the generator can never select is dead weight in the pool.

    It still shows in the catalog browser and can be swapped in by hand, but
    no amount of configuration will make the planner prescribe it — which is
    invisible unless you go looking for it.
    """
    known = _selectable_patterns() | set(taxonomy.NON_SLOT_PATTERNS)
    orphans = {
        row["movement_pattern"]
        for row in strength.CATALOG_SELECTABLE
        if row.get("movement_pattern") and row["movement_pattern"] not in known
    }
    assert not orphans, (
        f"movement_pattern values no slot or finisher can select: {sorted(orphans)}. "
        "Add an entry to taxonomy.PATTERN_ALIASES folding each onto a pattern "
        "SPLIT_SLOTS names, or to taxonomy.NON_SLOT_PATTERNS if it is filled by "
        "a different mechanism (as `mobility` is)."
    )


def test_finisher_patterns_are_all_real_slot_patterns():
    """Keeps the restated finisher list above honest against the source.

    FINISHER_PATTERNS maps an under-MEV muscle to the pattern used to top it
    up. Every value must be a pattern the catalog actually carries, or the
    finisher silently finds no candidates and the gap never closes.
    """
    catalog_patterns = {
        row["movement_pattern"]
        for row in strength.CATALOG_SELECTABLE
        if row.get("movement_pattern")
    }
    missing = {
        pattern for pattern in (
            "isolation_leg", "isolation_core", "isolation_arm",
            "isolation_shoulder", "vertical_pull",
        )
        if pattern not in catalog_patterns
    }
    assert not missing, f"finisher patterns with no catalog carrier: {sorted(missing)}"


# --------------------------------------------------------------------------
# Regression cases — the specific exercises the drift was hiding
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exercise_id,expected_muscle",
    [
        ("Walking_Lunge", "quadriceps"),
        ("Cossack_Squat", "quadriceps"),
        ("Lateral_Lunge", "quadriceps"),
        ("Dumbbell_Step_Up", "quadriceps"),
        ("Dumbbell_Sumo_Squat", "quadriceps"),
        ("Pilates_Hundred", "abdominals"),
        ("Pilates_Teaser", "abdominals"),
    ],
)
def test_previously_uncredited_exercises_now_credit_volume(exercise_id, expected_muscle):
    """These are the rows that credited zero sets before TD-1."""
    row = strength.CATALOG_BY_ID[exercise_id]
    assert row["primary_muscle"] == expected_muscle
    assert taxonomy.credits_volume(row["primary_muscle"]) == expected_muscle


@pytest.mark.parametrize(
    "exercise_id,expected_pattern",
    [
        ("Dumbbell_Skullcrusher", "isolation_arm"),
        ("Tricep_Kickback", "isolation_arm"),
        ("Spider_Curl", "isolation_arm"),
        ("Drag_Curl", "isolation_arm"),
        ("Cossack_Squat", "lunge"),
        ("Lateral_Lunge", "lunge"),
    ],
)
def test_previously_unreachable_exercises_are_now_selectable(exercise_id, expected_pattern):
    """These rows carried patterns no slot named, so the generator could not
    reach them regardless of the user's equipment or split."""
    row = strength.CATALOG_BY_ID[exercise_id]
    assert row["movement_pattern"] == expected_pattern
    candidates = strength._exercises_for_pattern(
        strength.CATALOG_SELECTABLE, expected_pattern, "intermediate", None,
    )
    assert exercise_id in {c["id"] for c in candidates}


def test_provenance_is_preserved_for_folded_rows():
    """Catalog maintenance still needs to see what the source file said."""
    folded = [
        row for row in strength.CATALOG
        if "primary_muscle_raw" in row or "movement_pattern_raw" in row
    ]
    assert folded, "expected at least some rows to require folding"
    for row in folded:
        if "primary_muscle_raw" in row:
            assert row["primary_muscle_raw"] != row["primary_muscle"]
        if "movement_pattern_raw" in row:
            assert row["movement_pattern_raw"] != row["movement_pattern"]
