"""Canonical vocabulary for the exercise catalog.

The bundled catalog is assembled from two sources — yuhonas/free-exercise-db
and our own supplement file — which were written years apart by different
hands. They do not agree on how to name a muscle or a movement pattern, and
until this module existed the disagreement was silent: the *display* layer
normalised synonyms (both clients carry a ``MUSCLE_ALIAS`` map purely so the
right anatomy icon renders) while the *arithmetic* layer did not.

The result was volume that quietly vanished. ``weekly_muscle_volume`` keyed
``sets_by_muscle`` on the raw catalog string and then emitted only the keys
present in ``MUSCLE_VOLUME_TARGETS``, so every exercise tagged ``quads``
rather than ``quadriceps`` credited exactly zero sets — five real leg
exercises, including Walking Lunge and Dumbbell Sumo Squat — and roughly
forty secondary-credit tokens evaporated through the same path. The number
that disappeared is not cosmetic: it is rendered on the muscle-volume audit
card, it feeds ``muscle_need()`` and therefore adaptive split selection, and
it drives the WP-5F finisher gap ranking. A wrong input propagated all the
way into what the planner prescribed.

Movement patterns had the same problem in a different shape.
``_exercises_for_pattern`` matches ``movement_pattern`` by exact equality,
and ``SPLIT_SLOTS`` plus ``FINISHER_PATTERNS`` between them name only eleven
patterns — so the ten catalog rows tagged ``tricep_isolation``,
``bicep_isolation``, ``chest_isolation`` or ``lateral_squat`` could never be
selected by the generator at all, no matter what the user had configured.

This module is the single place the vocabulary is decided. Everything that
does arithmetic on a muscle or a pattern folds through it first, and
``tests/test_catalog_taxonomy.py`` fails the build when a catalog row
introduces a token that neither folds into a landmark bucket nor appears in
an explicit exemption list. Silent drift becomes a red test.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Volume landmarks
# ---------------------------------------------------------------------------
# Weekly working-set ranges per muscle: (MEV, MAV) — minimum effective volume
# and maximum adaptive volume, in the Israetel/Helms sense. These fourteen
# keys are the canonical muscle vocabulary: a token that does not fold into
# one of them earns no volume credit anywhere in the app.
#
# Moved here from analytics/strength.py so the landmarks and the vocabulary
# that feeds them cannot drift apart. strength.py re-exports the name, and
# BodyMapPaths.kt / BodyMap in StrengthCharts.vue render one region per key —
# adding a key here without adding the matching artwork on both surfaces
# leaves a row on the audit card that the body map cannot draw.
MUSCLE_VOLUME_TARGETS: dict[str, tuple[int, int]] = {
    "chest":       (10, 20),
    "back":        (10, 20),
    "lats":        (10, 20),
    "shoulders":   (8,  16),
    "biceps":      (8,  16),
    "triceps":     (6,  14),
    "quadriceps":  (10, 18),
    "hamstrings":  (8,  16),
    "glutes":      (10, 18),
    "calves":      (8,  14),
    "abdominals":  (8,  16),
    "forearms":    (2,  8),
    "traps":       (2,  8),
    "lower_back":  (2,  8),
}

CANONICAL_MUSCLES: frozenset[str] = frozenset(MUSCLE_VOLUME_TARGETS)


# ---------------------------------------------------------------------------
# Muscle synonym folding
# ---------------------------------------------------------------------------
# Every entry is a judgement about which landmark bucket the work actually
# lands in, not merely a spelling fix, so each non-obvious one carries its
# reason. The map is a superset of the two client-side icon aliases
# (frontend/src/utils/muscleIcon.ts and android .../ui/strength/MuscleIcon.kt)
# extended to cover the tokens those maps deliberately left unmapped, because
# an icon may honestly decline to render while a set of work must still be
# credited somewhere.
MUSCLE_ALIASES: dict[str, str] = {
    # --- pure synonyms -----------------------------------------------------
    "quads":        "quadriceps",
    "abs":          "abdominals",
    "core":         "abdominals",
    "upper_back":   "back",
    # --- anatomical roll-ups ----------------------------------------------
    # Obliques are trained by the same rotational and anti-rotational work
    # the abdominal landmark already covers; splitting them out would need
    # its own MEV/MAV evidence base that does not exist for a home gym.
    "obliques":     "abdominals",
    # The deep hip flexors (psoas, iliacus) are the prime movers in the
    # hollow-body hold and the Pilates leg-stretch family, which every
    # programming tradition counts as anterior-core work.
    "hip_flexors":  "abdominals",
    # Erector spinae. "spine" appears only on Pilates extension rows.
    "spine":        "lower_back",
    # Posterior deltoid is part of the shoulder landmark; there is no
    # separate rear-delt MEV in the source literature we follow.
    "rear_delts":   "shoulders",
    # Brachialis lies under the biceps and is loaded by the same elbow
    # flexion; the pinwheel curl that carries this tag is a biceps exercise.
    "brachialis":   "biceps",
    # Serratus anterior works with the pectorals through the pullover arc.
    "serratus":     "chest",
    # Upper trapezius performs cervical extension, so the isometric neck
    # holds credit traps. Note this deliberately differs from the clients'
    # icon maps, which send neck to the shoulders picture — an approximate
    # illustration is a different question from where the work lands, and
    # after this change the credit and the picture at least agree on the
    # posterior chain.
    "neck":         "traps",
    # Adductor magnus is a genuine hip extensor — the "fourth hamstring" —
    # and works alongside the glutes in the sumo squat, Cossack squat and
    # lateral lunge that carry these tags. Giving the adductors their own
    # landmark would be more precise, but it would put a fifteenth row on
    # the audit card that neither body map has artwork for; that is tracked
    # as a follow-up rather than shipped half-done here.
    "adductors":    "glutes",
    "groin":        "glutes",
    # "hips" appears only on yoga poses (pigeon, warrior 2, child's pose)
    # where the loaded tissue is the glute complex.
    "hips":         "glutes",
}

# Tokens that are real and correctly tagged but describe a quality rather
# than a muscle, so they earn no working-set credit. Listing them explicitly
# is what lets the drift test treat every *other* unknown token as a bug.
# "flexibility" is the primary tag on all fifteen yoga rows; the clients rely
# on it staying unmapped so the pose illustration renders instead of an
# anatomy icon.
NON_VOLUME_MUSCLES: frozenset[str] = frozenset({"flexibility", "balance"})


def canonical_muscle(raw: str | None) -> str | None:
    """Fold a catalog muscle token onto the canonical vocabulary.

    Returns None for a missing token. Returns the token unchanged when it is
    already canonical, when it is a known non-volume quality, or when it is
    unrecognised — an unknown token is passed through rather than dropped so
    that display keeps working, and the drift test is what turns it into a
    failure.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    return MUSCLE_ALIASES.get(key, key)


def credits_volume(raw: str | None) -> str | None:
    """The landmark bucket this token credits, or None if it credits none.

    This is the one predicate the volume arithmetic should use. It folds
    synonyms first, so a row tagged ``quads`` credits ``quadriceps``, and it
    returns None for yoga qualities and for anything unrecognised.
    """
    canon = canonical_muscle(raw)
    return canon if canon in CANONICAL_MUSCLES else None


# ---------------------------------------------------------------------------
# Movement-pattern folding
# ---------------------------------------------------------------------------
# The generator's slot tables name eleven patterns. Anything the catalog
# emits outside that set is unreachable, so these four aliases are not
# cosmetic — each one returns a group of exercises to the selectable pool.
PATTERN_ALIASES: dict[str, str] = {
    # The catalog spells arm isolation three different ways. All three are
    # the same slot; push day's isolation_arm slot filters to triceps and
    # pull day's to biceps, so the primary muscle already does the routing
    # that these redundant pattern names were attempting.
    "tricep_isolation": "isolation_arm",
    "bicep_isolation":  "isolation_arm",
    # A dumbbell fly or pullover is still work in the horizontal pushing
    # plane, and horizontal_push is the only chest slot the splits define.
    "chest_isolation":  "horizontal_push",
    # The Cossack squat and lateral lunge are frontal-plane single-leg
    # patterns; the lunge slot is where they belong and where the splits
    # already look for that stimulus.
    "lateral_squat":    "lunge",
}

# Patterns that legitimately have no slot in SPLIT_SLOTS or FINISHER_PATTERNS
# because they are selected by a different mechanism entirely — the mobility
# cool-down block is appended by select_mobility_poses, not by slot filling.
NON_SLOT_PATTERNS: frozenset[str] = frozenset({"mobility"})


def canonical_pattern(raw: str | None) -> str | None:
    """Fold a catalog movement_pattern onto the vocabulary the slots use."""
    if not raw:
        return None
    key = raw.strip().lower()
    return PATTERN_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Catalog normalisation
# ---------------------------------------------------------------------------

def normalise_catalog_row(row: dict[str, Any]) -> dict[str, Any]:
    """Rewrite one catalog row's vocabulary in place, preserving provenance.

    The original values are kept under ``primary_muscle_raw``,
    ``secondary_muscles_raw`` and ``movement_pattern_raw`` so that catalog
    maintenance can still see what the source file said. Only synonyms are
    folded: a non-volume quality such as ``flexibility`` survives untouched,
    because the clients key their pose illustrations off it.

    Secondary muscles are de-duplicated after folding — a row tagging both
    ``abs`` and ``core`` would otherwise credit the abdominals twice.
    """
    primary = row.get("primary_muscle")
    if primary:
        canon = canonical_muscle(primary)
        if canon != primary:
            row["primary_muscle_raw"] = primary
            row["primary_muscle"] = canon

    secondary = row.get("secondary_muscles") or []
    if secondary:
        folded: list[str] = []
        for token in secondary:
            canon = canonical_muscle(token)
            if canon and canon not in folded:
                folded.append(canon)
        # Never let a secondary tag duplicate the primary mover: the primary
        # already credits 1.0x and the secondary would add another 0.5x for
        # the same work. This can only happen after folding (e.g. a row with
        # primary "abdominals" and secondary "core").
        folded = [m for m in folded if m != row.get("primary_muscle")]
        if folded != secondary:
            row["secondary_muscles_raw"] = list(secondary)
            row["secondary_muscles"] = folded

    pattern = row.get("movement_pattern")
    if pattern:
        canon = canonical_pattern(pattern)
        if canon != pattern:
            row["movement_pattern_raw"] = pattern
            row["movement_pattern"] = canon

    return row


def normalise_catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply :func:`normalise_catalog_row` across a whole catalog, in place."""
    for row in rows:
        normalise_catalog_row(row)
    return rows
