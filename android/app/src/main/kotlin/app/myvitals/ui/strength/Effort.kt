package app.myvitals.ui.strength

import androidx.compose.ui.graphics.Color
import app.myvitals.sync.StrengthProgressionPoint

/**
 * OG2-D-4 — how a session FELT, on the progression chart. Mirrors
 * `frontend/src/effort.ts`; keep the two in step, the way `Units.kt`
 * mirrors `units.ts`.
 *
 * The chart drew a flat line across four sessions of Straight-Arm Dumbbell
 * Pullover at 20 lb and said nothing about the ratings underneath it moving
 * 4, 4, 5, 5 before the jump to 25. Weight was the only channel, so the
 * sessions in which the lift got easier — the ones that EARNED the jump —
 * were rendered as no progress at all.
 *
 * Two things deliberately do not happen here.
 *
 * The BAND is not derived. `effort` arrives from the server, computed from
 * the same EASY_THRESHOLD / FAIL_THRESHOLD the progression policy acts on,
 * so a dot marked "easy" is exactly the dot where the weight went up. This
 * app rates sets 1-5 where 5 is EASY — the scale counts up with ease, not
 * with effort, and openGym's RIR counts the other way — so which end means
 * what is precisely the inversion GOAL-STATE says one server must own rather
 * than two clients.
 *
 * The LABEL is not written here either. It comes from `effortLegend` in the
 * same response, so the words explaining a band and the thresholds defining
 * it cannot drift apart.
 *
 * What is left is colour, and it is an intensity ramp rather than a traffic
 * light. Effort is descriptive, not a verdict: a hard session is not a
 * failure and an easy one is not a win — an easy session usually means the
 * load is due to go up. Green and red would be scoring the user's training,
 * which is the thing this codebase keeps declining to do.
 */
enum class EffortBand { EASY, WORKING, FAILED }

/** Three bands and nothing else. An unrecognised value from a newer server
 *  must not become a lookup miss that paints an undefined colour. */
fun effortBand(p: StrengthProgressionPoint): EffortBand? = when (p.effort) {
    "easy" -> EffortBand.EASY
    "working" -> EffortBand.WORKING
    "failed" -> EffortBand.FAILED
    else -> null
}

/**
 * Deepening ink, not hue-coded judgement. `working` and an unrated day both
 * fall back to the series colour, so the ordinary case reads as the line
 * itself and only the two ends stand out — and "nobody rated this" never
 * looks like a reading.
 */
fun effortColor(band: EffortBand?, seriesColor: Color, neon: Boolean): Color = when (band) {
    EffortBand.EASY -> if (neon) Color(0xFF5EEAD4) else Color(0xFF14B8A6)
    EffortBand.FAILED -> if (neon) Color(0xFFFBBF24) else Color(0xFFD97706)
    else -> seriesColor
}

/**
 * The readout line. Returns null when nothing was rated — an absence, not a
 * zero, and never the middle band. The count travels with the average for
 * OG2-C4's reason: a mean over two of five sets must not silently speak for
 * the other three.
 */
fun effortSummary(
    p: StrengthProgressionPoint,
    legend: Map<String, String>,
): String? {
    val band = effortBand(p) ?: return null
    val avg = p.ratingAvg ?: return null
    val n = p.ratedSets
    val words = legend[p.effort] ?: p.effort ?: return null
    val sets = if (n == 1) "set" else "sets"
    return "$avg/5 over $n rated $sets — $words"
}
