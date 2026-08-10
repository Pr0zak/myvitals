package app.myvitals.ui.neon

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ReadinessDetail
import app.myvitals.sync.ReadinessDriver

/**
 * Readiness hero — the number, what it means, and what moved it.
 *
 * The score is the app's best-engineered figure (weighted z-scores against
 * 28-day baselines, physiology-only) and it used to render as bare ink with
 * no band and no drivers, so an HRV of 22 ms and 95 ms looked identical.
 *
 * Everything here is SERVER-DERIVED — score, band, z-scores, sub-scores and
 * weights all arrive from /summary/readiness. Nothing is recomputed in
 * Compose, so this can't drift from the web or from the stored value.
 *
 * Deliberately no AI narration: Google Health shipped prose on its home
 * screen and was still walking it back on its July 2026 roadmap. A number,
 * a word, a sparkline and three rows are readable at a glance.
 */
@Composable
fun ReadinessHero(
    detail: ReadinessDetail?,
    modifier: Modifier = Modifier,
    onDriverClick: ((ReadinessDriver) -> Unit)? = null,
    onExplain: (() -> Unit)? = null,
) {
    if (detail == null) return
    val band = detail.band
    val accent = bandColor(band)

    Column(
        modifier
            .fillMaxWidth()
            .padding(bottom = 14.dp)
            .background(NeonMV.Card, RoundedCornerShape(18.dp))
            .border(1.dp, accent.copy(alpha = 0.30f), RoundedCornerShape(18.dp))
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        Text(
            "READINESS",
            color = NeonMV.Muted, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp,
        )
        Spacer(Modifier.height(6.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(
                Modifier
                    .weight(1f)
                    .then(
                        if (onExplain != null) Modifier.clickable { onExplain() }
                        else Modifier,
                    ),
            ) {
                if (detail.score == null) {
                    // Never show a fabricated number. The backend returns null
                    // rather than a score dominated by one noisy input, and the
                    // reason is worth surfacing verbatim.
                    Text("—", color = NeonMV.Muted, fontSize = 46.sp,
                        fontWeight = FontWeight.Bold)
                    Text(
                        detail.reason?.replaceFirstChar { it.uppercase() }
                            ?: "Not enough data yet",
                        color = NeonMV.Muted, fontSize = 12.sp,
                    )
                } else {
                    Row(verticalAlignment = Alignment.Bottom) {
                        NeonNumber(
                            "%.0f".format(detail.score),
                            size = 46, color = NeonMV.Ink,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            (band ?: "").uppercase(),
                            color = accent, fontSize = 13.sp,
                            fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp,
                            modifier = Modifier.padding(bottom = 8.dp),
                        )
                    }
                    if (onExplain != null) {
                        Text("How this is calculated", color = NeonMV.Cyan,
                            fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            ReadinessSparkline(
                detail.series.map { it.score },
                accent,
                Modifier.width(96.dp).height(44.dp),
            )
        }

        if (detail.drivers.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            detail.drivers.forEach { d ->
                DriverRow(d, onClick = onDriverClick?.let { cb -> { cb(d) } })
            }
        }
    }
}

/**
 * "How this is calculated" — rendered FROM the payload's weights and the
 * live drivers, not from a hand-written string. A copied formula in the UI
 * drifts the moment someone retunes the weights server-side; this cannot.
 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun ReadinessFormulaSheet(detail: ReadinessDetail, onDismiss: () -> Unit) {
    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = NeonMV.Card,
    ) {
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
            Text("How readiness is calculated", color = NeonMV.Ink,
                fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            Text(
                "A weighted blend of four signals, each scored against your "
                    + "own 28-day baseline — not a population average. 50 is "
                    + "your normal; higher is better than your normal.",
                color = NeonMV.Muted, fontSize = 13.sp,
            )
            Spacer(Modifier.height(16.dp))

            val order = listOf(
                "hrv" to "HRV", "rhr" to "Resting HR",
                "sleep_score" to "Sleep quality", "sleep_duration" to "Sleep duration",
            )
            order.forEach { (key, label) ->
                val w = detail.weights[key] ?: return@forEach
                val d = detail.drivers.firstOrNull { it.key == key }
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(label, color = NeonMV.Ink, fontSize = 13.sp,
                        modifier = Modifier.weight(1f))
                    if (d?.subScore != null) {
                        NeonNumber("%.0f".format(d.subScore), size = 13,
                            color = NeonMV.Ink)
                        Spacer(Modifier.width(10.dp))
                    } else {
                        Text("not used today", color = NeonMV.Muted,
                            fontSize = 11.sp)
                        Spacer(Modifier.width(10.dp))
                    }
                    Text("%.0f%%".format(w * 100), color = NeonMV.Cyan,
                        fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }

            Spacer(Modifier.height(14.dp))
            Text("Bands", color = NeonMV.Muted, fontSize = 10.sp,
                fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                BandKey("Low", "≤29", NeonMV.Bad)
                BandKey("Moderate", "30–64", NeonMV.Amber)
                BandKey("High", "≥65", NeonMV.Lime)
            }
            Spacer(Modifier.height(14.dp))
            Text(
                "When too few signals are available the score is withheld "
                    + "rather than guessed — a number driven by one noisy "
                    + "input is worse than no number.",
                color = NeonMV.Muted, fontSize = 12.sp,
            )
        }
    }
}

@Composable
private fun BandKey(label: String, range: String, tone: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(8.dp).height(8.dp)
            .background(tone, RoundedCornerShape(4.dp)))
        Spacer(Modifier.width(5.dp))
        Text("$label $range", color = NeonMV.Muted, fontSize = 11.sp)
    }
}

/** Semantic band colour — independent of the shell accent. */
private fun bandColor(band: String?): Color = when (band) {
    "high" -> NeonMV.Lime
    "moderate" -> NeonMV.Amber
    "low" -> NeonMV.Bad
    else -> NeonMV.Muted
}

@Composable
private fun DriverRow(d: ReadinessDriver, onClick: (() -> Unit)?) {
    // A driver is "good" when it pushed the score UP — i.e. its sub-score is
    // above the 50 midpoint. Using the raw z would invert for resting HR,
    // where lower is better; sub_score already accounts for direction.
    val good = (d.subScore ?: 50.0) >= 50.0
    val tone = if (good) NeonMV.Lime else NeonMV.Bad
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (good) "▲" else "▼", color = tone, fontSize = 10.sp,
            fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(8.dp))
        Text(d.label, color = NeonMV.Muted, fontSize = 12.sp,
            modifier = Modifier.weight(1f))
        d.value?.let {
            NeonNumber(fmtDriver(d), size = 13, color = NeonMV.Ink)
        }
        d.z?.let {
            Spacer(Modifier.width(8.dp))
            Text(
                (if (it >= 0) "+" else "") + "%.1fσ".format(it),
                color = tone, fontSize = 11.sp, fontWeight = FontWeight.Medium,
            )
        }
    }
}

private fun fmtDriver(d: ReadinessDriver): String {
    val v = d.value ?: return "—"
    val n = if (d.unit == "h") "%.1f".format(v) else "%.0f".format(v)
    return if (d.unit.isBlank()) n else "$n ${d.unit}"
}

/**
 * 7-day trend. Nulls are gaps, not zeros — a day with no score must not
 * dive the line to the floor and imply a crash that didn't happen.
 *
 * Geometry matches `ReadinessHero.vue` exactly: same inset, same isolated-
 * point rule, same endpoint emphasis. The two surfaces plot one dataset.
 */
@Composable
private fun ReadinessSparkline(
    points: List<Double?>,
    accent: Color,
    modifier: Modifier = Modifier,
) {
    val real = points.filterNotNull()
    if (real.size < 2) return
    val min = real.min()
    val max = real.max()
    val span = (max - min).takeIf { it > 0.5 } ?: 1.0
    Canvas(modifier) {
        // Inset by the dot radius so the endpoint marker isn't half-clipped
        // against the canvas edge.
        val pad = 3.5f
        val stepX =
            if (points.size > 1) (size.width - pad * 2) / (points.size - 1) else 0f
        fun at(v: Double, i: Int) = Offset(
            pad + i * stepX,
            size.height - pad - ((v - min) / span).toFloat() * (size.height - pad * 2),
        )

        val path = Path()
        var started = false
        points.forEachIndexed { i, p ->
            if (p == null) { started = false; return@forEachIndexed }
            val o = at(p, i)
            // A lone reading between two gaps would be a moveTo with no
            // lineTo — i.e. invisible. Draw it as a dot instead.
            if (points.getOrNull(i - 1) == null && points.getOrNull(i + 1) == null) {
                drawCircle(accent, radius = 2.5f, center = o)
            }
            if (!started) { path.moveTo(o.x, o.y); started = true } else path.lineTo(o.x, o.y)
        }
        drawPath(path, accent, style = Stroke(width = 2.5f))
        // Emphasise the endpoint — today is the value the header states.
        points.lastOrNull()?.let { last ->
            if (last != null) drawCircle(accent, radius = 3.5f, center = at(last, points.size - 1))
        }
    }
}
