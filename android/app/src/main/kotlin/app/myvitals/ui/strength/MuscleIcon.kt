package app.myvitals.ui.strength

/**
 * Phone-side mirror of frontend/src/utils/muscleIcon.ts. Maps the
 * catalog's 17 distinct primary_muscle values onto the 11 anatomy
 * icon buckets we have PNGs for. Returns null for muscles that the
 * yoga / mobility flow handles separately (flexibility, hips, balance).
 *
 * TD-1 note: the backend now folds the catalog's muscle vocabulary onto a
 * canonical set at import (backend analytics/taxonomy.py), so bundled
 * exercises arrive here already spelled canonically and most of the aliases
 * below never fire. They are kept deliberately as defence for anything that
 * did not come through that path — an imported CSV exercise, or a catalog
 * row served by an older backend than the one this build was written for.
 * Do not treat this map as the source of truth for anything but the picture:
 * where the work is *credited* is decided server-side, and this map's
 * neck→shoulders entry intentionally disagrees with the server's neck→traps.
 */

private val MUSCLE_ALIAS = mapOf(
    "chest" to "chest",
    "back" to "back",
    "lats" to "back",
    "upper_back" to "back",
    "lower_back" to "back",
    "traps" to "back",
    "shoulders" to "shoulders",
    "neck" to "shoulders",
    "abs" to "abs",
    "abdominals" to "abs",
    "core" to "abs",
    "obliques" to "abs",
    "biceps" to "biceps",
    "triceps" to "triceps",
    "forearms" to "forearms",
    "glutes" to "glutes",
    "quads" to "quads",
    "quadriceps" to "quads",
    "hamstrings" to "hamstrings",
    "calves" to "calves",
)

/** Returns the relative URL path for the muscle icon, or null. */
fun muscleIconPath(primaryMuscle: String?): String? {
    val key = MUSCLE_ALIAS[primaryMuscle?.lowercase()] ?: return null
    return "/exercises/img/muscle/$key/0.png"
}

/** Pretty consolidated label (Abs vs Abdominals). */
fun muscleIconLabel(primaryMuscle: String?): String {
    val raw = primaryMuscle ?: return ""
    val key = MUSCLE_ALIAS[raw.lowercase()] ?: return raw
    return key.replaceFirstChar { it.uppercase() }
}
