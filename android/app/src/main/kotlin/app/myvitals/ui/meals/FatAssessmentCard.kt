package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.HelpOutline
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.FatAssessment
import app.myvitals.ui.neon.NeonMV

/**
 * The per-meal fat verdict for one serving — the phone mirror of the
 * web's `FatAssessment.vue`.
 *
 * What this does NOT say is as important as what it does. The app has no
 * default fat threshold and will not invent one: tolerance after a
 * cholecystectomy varies widely between people and commonly improves
 * over months, so a made-up limit could be wrong in either direction.
 * When the server returns `verdict = "unknown"` this renders the refusal
 * and what would fix it, in NEUTRAL grey — never green, because "we
 * cannot judge this" must not borrow the reassurance of "this is fine".
 *
 * `basis` is always shown next to the verdict, so "high" never appears
 * as a bare fact.
 */
@Composable
fun FatAssessmentCard(
    assessment: FatAssessment,
    modifier: Modifier = Modifier,
    compact: Boolean = false,
) {
    val style = verdictStyle(assessment.verdict)

    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(NeonMV.Card),
    ) {
        // Left severity stripe — encodes the verdict in form as well as
        // colour, so it survives being read at a glance.
        Box(
            Modifier
                .width(3.dp)
                .background(style.colour)
                .fillMaxWidth(0f),
        )
        Column(Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(style.icon, contentDescription = null, tint = style.colour)
                Text(
                    "  " + (assessment.fatG?.let { String.format("%.1f g", it) } ?: "—") + " fat",
                    color = NeonMV.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                )
                Text("  per serving", color = NeonMV.Muted, fontSize = 10.sp)
                Text(
                    style.label,
                    color = style.colour,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(start = 8.dp),
                )
            }
            basisLine(assessment)?.let {
                Text(
                    it, color = NeonMV.Muted, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            if (!compact) {
                assessment.reason?.let {
                    Text(
                        it, color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 16.sp,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}

private data class VerdictStyle(
    val colour: Color, val icon: ImageVector, val label: String,
)

private fun verdictStyle(verdict: String): VerdictStyle = when (verdict) {
    "very_high" -> VerdictStyle(NeonMV.Bad, Icons.Filled.Warning, "WELL ABOVE USUAL")
    "high" -> VerdictStyle(NeonMV.Amber, Icons.Filled.Warning, "HIGH FOR ONE MEAL")
    "approaching" -> VerdictStyle(NeonMV.Amber, Icons.Filled.Info, "APPROACHING")
    "ok" -> VerdictStyle(NeonMV.Lime, Icons.Filled.CheckCircle, "IN RANGE")
    // Neutral on purpose. An absent judgment is not a good one.
    else -> VerdictStyle(NeonMV.Muted, Icons.Filled.HelpOutline, "NOT ENOUGH TO JUDGE")
}

/** Names what the verdict was measured against, so it is never a bare
 *  assertion. Returns null when there is no basis at all — the reason
 *  line carries the explanation in that case. */
private fun basisLine(a: FatAssessment): String? = when (a.basis) {
    "target" -> a.targetSource
        ?.let { "vs your ${fmtG(a.targetG)} target — $it" }
        ?: "vs your ${fmtG(a.targetG)} per-meal target"
    "history" -> "vs your own ${a.comparisonMeals} other meals"
    else -> null
}

private fun fmtG(v: Double?): String =
    if (v == null) "—" else if (v == v.toLong().toDouble()) "${v.toLong()}g"
    else String.format("%.1fg", v)
