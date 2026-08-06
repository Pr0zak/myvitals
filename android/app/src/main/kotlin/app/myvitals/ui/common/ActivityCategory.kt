package app.myvitals.ui.common

import androidx.compose.ui.graphics.Color
import app.myvitals.ui.neon.NeonMV

/**
 * One palette for "what kind of activity is this", shared by the year
 * calendar, the activity feed rows and anything else that colour-codes by
 * type.
 *
 * Before this existed the same hexes were written out in three places —
 * the calendar's fill `when` block, its hard-coded legend, and the feed
 * row icons — which is how the legend ended up missing Row and Other
 * while the canvas still drew them.
 *
 * The neon values are not invented here: `StrengthHistory.vue:100-111`
 * already maps strength→magenta, yoga→periwinkle, cardio→cyan in the neon
 * skin, so a neon calendar now agrees with the neon strength charts. The
 * classic values are the exact hexes the calendar drew before, so the
 * default shell is unchanged.
 */
enum class ActivityCategory(
    val key: String,
    val label: String,
    val classic: Color,
    val neon: Color,
) {
    STRENGTH("strength", "Strength", Color(0xFFEF4444), NeonMV.Magenta),
    YOGA("yoga", "Yoga", Color(0xFFA78BFA), NeonMV.Periwinkle),
    RIDE("ride", "Ride", Color(0xFF38BDF8), NeonMV.Cyan),
    RUN("run", "Run", Color(0xFF22C55E), NeonMV.Lime),
    WALK("walk", "Walk", Color(0xFFF59E0B), NeonMV.Amber),
    // Teal, deliberately distinct from Cyan — rowing next to a ride must
    // not read as the same category on a 10 px calendar cell.
    ROW("row", "Row", Color(0xFF06B6D4), Color(0xFF2EE6C5)),
    OTHER("other", "Other", Color(0xFF94A3B8), NeonMV.Muted);

    fun color(neon: Boolean): Color = if (neon) this.neon else classic
}

/** Colour for a day with nothing logged. */
fun activityCategoryEmpty(neon: Boolean): Color =
    if (neon) Color(0xFF161A24) else Color(0x141A2332)

/**
 * Classify a raw activity `type` string.
 *
 * The exact matches are the ones the calendar already recognised. The
 * substring fallbacks are new: the catalog carries ~37 distinct type
 * strings across Strava, Fitbit and MyFitnessPal, so variants like
 * `VirtualRide`, `TrailRun` and the MyFitnessPal
 * `walking,_3.0_mph,_mod._pace_...` labels used to fall through to OTHER
 * and render grey.
 *
 * Order matters: "run" is tested before "walk" because several
 * MyFitnessPal labels contain both words.
 */
fun categoryForActivityType(type: String?): ActivityCategory {
    val t = (type ?: "").lowercase()
    return when (t) {
        "ride", "ebikeride", "mountain_biking", "cycling" -> ActivityCategory.RIDE
        "run", "trailrun", "running" -> ActivityCategory.RUN
        "hike", "walk", "walking" -> ActivityCategory.WALK
        "rower", "rowing", "row" -> ActivityCategory.ROW
        else -> when {
            t.isEmpty() -> ActivityCategory.OTHER
            t.contains("kayak") || t.contains("row") || t.contains("paddle") ||
                t.contains("canoe") -> ActivityCategory.ROW
            t.contains("run") || t.contains("jog") -> ActivityCategory.RUN
            t.contains("hike") || t.contains("walk") -> ActivityCategory.WALK
            t.contains("bike") || t.contains("cycl") || t.contains("ride") ->
                ActivityCategory.RIDE
            t.contains("strength") || t.contains("weight") ||
                t.contains("lifting") -> ActivityCategory.STRENGTH
            t.contains("yoga") || t.contains("pilates") ||
                t.contains("mobility") -> ActivityCategory.YOGA
            else -> ActivityCategory.OTHER
        }
    }
}

/**
 * Classify a generated workout by its `split_focus`.
 *
 * Cardio days map to RIDE rather than STRENGTH: the activity feed already
 * draws them with a bike icon (ActivitiesScreen ActivityIcon), so painting
 * them red on the calendar contradicted the row two inches below.
 */
fun categoryForSplitFocus(focus: String?): ActivityCategory =
    when ((focus ?: "").lowercase()) {
        "yoga" -> ActivityCategory.YOGA
        "cardio" -> ActivityCategory.RIDE
        else -> ActivityCategory.STRENGTH
    }
