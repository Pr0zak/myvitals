package app.myvitals.ui.common

import androidx.compose.ui.graphics.Color
import app.myvitals.sync.AiGoal
import kotlin.math.abs

/**
 * GOAL-STATE — rendering a goal that has moved the wrong way.
 *
 * A progress bar has one number with three meanings crammed into its zero:
 * "no reading yet", "on the starting line", and "you have gone backwards".
 * The third is the one worth knowing and the only one an empty bar cannot
 * say. A man five pounds heavier than when he set the goal saw the same
 * empty track as a man who set it this morning.
 *
 * `progressState` and `stateTone` come from the server, and the tone
 * especially is NOT derived here — same reason `analytics/compare.py` owns
 * `better` rather than letting each client decide which way is good. A
 * client left to infer "went down, so warn" would eventually paint a
 * broken sobriety streak amber.
 *
 * Mirrors `frontend/src/goalState.ts`; the two surfaces must not disagree.
 */

/**
 * Amber, and only amber.
 *
 * Rose is reserved for the crisis surfaces. Spending it on a body weight
 * that drifted over a quarter is how it comes to mean nothing on the day
 * it fires for something that does.
 */
val GoalAway = Color(0xFFFFB52E)

/** Whether the goal has moved AWAY from its target by more than noise.
 *  Server-decided; the band is measured there, not guessed here. */
fun goalMovedAway(g: AiGoal): Boolean =
    g.progressState == "moved_away" && g.deltaValue != null

/**
 * "5.4 lb above start". States the direction in words rather than leaning
 * on a sign, because a minus glyph in small mono type is the easiest thing
 * on the screen to miss and the direction is the entire message.
 */
fun goalDeltaLabel(g: AiGoal): String? {
    val d = g.deltaValue ?: return null
    val unit = g.targetUnit?.let { " $it" } ?: ""
    val mag = abs(d)
    if (mag == 0.0) return "at start"
    val n = if (mag >= 10) "%.0f".format(mag) else "%.1f".format(mag)
    return "$n$unit ${if (d > 0) "above" else "below"} start"
}

/** The short line a compact surface shows in place of a percentage that
 *  cannot tell "not started" from "gone backwards". */
fun goalStateNote(g: AiGoal): String? = when (g.progressState) {
    "moved_away" -> goalDeltaLabel(g)
    "at_start" -> "at your start"
    "no_data" -> "no reading yet"
    else -> null
}
