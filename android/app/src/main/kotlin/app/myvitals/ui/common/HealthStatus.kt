package app.myvitals.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ReadinessDetail
import app.myvitals.sync.VitalTilesRollup
import java.time.LocalDate

/**
 * "Health status" — phone twin of `HealthStatus.vue`.
 *
 * Readiness rendered as a MetricCard rather than a bespoke hero. It is a
 * metric with a value, a band and a series, so it should look like every
 * other metric; the old hero was a third card style stacked above the
 * Focus pills and the Key metrics grid. Drivers survive behind a tap.
 */
@Composable
fun HealthStatus(
    readiness: ReadinessDetail?,
    rollup: VitalTilesRollup?,
    modifier: Modifier = Modifier,
) {
    var open by remember { mutableStateOf(false) }

    Column(modifier.fillMaxWidth()) {
        Text("Health status", color = Color(0xFFE9EDF2), fontSize = 21.sp)
        Spacer(Modifier.height(10.dp))

        if (rollup != null && rollup.judged > 0) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(Color(0xFF1B1C1F), RoundedCornerShape(16.dp))
                    .padding(horizontal = 14.dp, vertical = 12.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                Text("Vitals", color = Color(0xFFB9BEC6), fontSize = 13.sp)
                Spacer(Modifier.width(8.dp))
                Text(
                    "${rollup.inRange} of ${rollup.judged} in range",
                    color = Color(0xFFE9EDF2), fontSize = 16.sp,
                    fontWeight = FontWeight.Light,
                )
            }
            Spacer(Modifier.height(10.dp))
        }

        MetricCard(
            name = "Readiness",
            value = readiness?.score?.let { "%.0f".format(it) },
            unit = "",
            qualifier = if (readiness?.score == null) {
                (readiness?.reason ?: "Not enough data yet")
                    .replaceFirstChar { it.uppercase() }
            } else "Today",
            series = readiness?.series?.map { it.score } ?: emptyList(),
            dayLetters = readiness?.series?.map { dayLetter(it.date) } ?: emptyList(),
            status = bandStatus(readiness?.band),
            statusLabel = readiness?.band?.replaceFirstChar { it.uppercase() },
            onClick = { open = !open },
        )

        if (open && readiness != null) {
            Spacer(Modifier.height(10.dp))
            Column(
                Modifier
                    .fillMaxWidth()
                    .background(Color(0xFF1B1C1F), RoundedCornerShape(16.dp))
                    .padding(14.dp),
            ) {
                Text(
                    "A weighted blend of four signals, each scored against "
                        + "your own 28-day baseline — not a population "
                        + "average. 50 is your normal.",
                    color = Color(0xFF8D949D), fontSize = 12.sp,
                )
                Spacer(Modifier.height(8.dp))
                readiness.drivers.forEach { d ->
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 5.dp),
                        verticalAlignment = Alignment.Bottom,
                    ) {
                        Text(d.label, color = Color(0xFFE9EDF2), fontSize = 13.sp,
                            modifier = Modifier.weight(1f))
                        Text(
                            d.value?.let {
                                if (d.unit == "h") "%.1f".format(it) else "%.0f".format(it)
                            } ?: "—",
                            color = Color(0xFFE9EDF2), fontSize = 13.sp,
                        )
                        d.z?.let {
                            Spacer(Modifier.width(8.dp))
                            Text(
                                (if (it >= 0) "+" else "") + "%.1fσ".format(it),
                                color = if ((d.subScore ?: 50.0) >= 50.0)
                                    Color(0xFF7EE2A8) else Color(0xFFE8B661),
                                fontSize = 11.sp,
                            )
                        }
                        Spacer(Modifier.width(8.dp))
                        Text(
                            "%.0f%%".format((readiness.weights[d.key] ?: 0.0) * 100),
                            color = Color(0xFF6F767F), fontSize = 11.sp,
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "When too few signals are available the score is withheld "
                        + "rather than guessed — a number driven by one noisy "
                        + "input is worse than no number.",
                    color = Color(0xFF8D949D), fontSize = 12.sp,
                )
            }
        }
    }
}

/** Band → the same three-value vocabulary the tiles use, so one chip style
 *  covers the whole screen. */
private fun bandStatus(band: String?): String? = when (band) {
    "high" -> "good"
    "moderate" -> "typical"
    "low" -> "watch"
    else -> null
}

private fun dayLetter(iso: String): String = runCatching {
    when (LocalDate.parse(iso).dayOfWeek.value) {
        1 -> "M"; 2 -> "T"; 3 -> "W"; 4 -> "T"; 5 -> "F"; 6 -> "S"; else -> "S"
    }
}.getOrDefault("")
