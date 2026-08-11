package app.myvitals.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.VitalTile
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * "Key metrics" — a titled section of identical MetricCards, 2-up.
 *
 * Phone twin of `KeyMetrics.vue`, down to the chip wording and qualifier
 * text, because the point of the redesign is that one card vocabulary is
 * repeated everywhere rather than each surface inventing its own.
 */
@Composable
fun KeyMetrics(
    tiles: List<VitalTile>,
    onOpen: (String) -> Unit,
    modifier: Modifier = Modifier,
    /** The user's saved tile order, as Vital enum names. The classic home
     *  has always let people reorder and hide tiles; that preference has to
     *  survive the redesign rather than be quietly dropped. Empty = the
     *  catalog order. */
    order: List<String> = emptyList(),
    /** Vital enum names the user has hidden. */
    hidden: Set<String> = emptySet(),
) {
    val ordered = applyPreference(tiles, order, hidden)
    if (ordered.isEmpty()) return
    Column(modifier.fillMaxWidth()) {
        Text(
            "Key metrics", color = Color(0xFFE9EDF2),
            fontSize = 21.sp, fontWeight = FontWeight.Normal,
        )
        Spacer(Modifier.height(12.dp))
        ordered.chunked(2).forEach { pair ->
            Row(
                Modifier.fillMaxWidth().padding(bottom = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                pair.forEach { t ->
                    Box(Modifier.weight(1f)) {
                        MetricCard(
                            name = t.label,
                            value = displayValue(t),
                            unit = t.unit,
                            qualifier = qualifier(t),
                            series = t.series.map { it.value },
                            dayLetters = t.series.map { dayLetter(it.date) },
                            status = t.status,
                            statusLabel = chipLabel(t),
                            bandLow = t.bandLow,
                            bandHigh = t.bandHigh,
                            target = if (t.key == "steps") t.target else null,
                            bars = t.key == "steps",
                            accent = accentFor(t.key),
                            onClick = { routeFor(t.key)?.let(onOpen) },
                        )
                    }
                }
                // Odd count: keep the last card half-width rather than
                // letting it stretch across the row.
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

/** Vital enum name → tiles key, so the saved preference (written against
 *  the old badge grid) still means something here. */
private val VITAL_TO_KEY = mapOf(
    "HR" to "resting_hr", "HRV" to "hrv", "SLEEP" to "sleep_duration",
    "STEPS" to "steps", "WEIGHT" to "weight", "BP" to "blood_pressure",
    "RECOVERY" to "recovery",
)

private fun applyPreference(
    tiles: List<VitalTile>, order: List<String>, hidden: Set<String>,
): List<VitalTile> {
    val hiddenKeys = hidden.mapNotNull { VITAL_TO_KEY[it] }.toSet()
    val visible = tiles.filter { it.key !in hiddenKeys }
    if (order.isEmpty()) return visible
    val rank = order.mapNotNull { VITAL_TO_KEY[it] }
        .withIndex().associate { (i, k) -> k to i }
    // Anything the saved order doesn't mention tail-appends in catalog
    // order rather than disappearing.
    return visible.sortedBy { rank[it.key] ?: Int.MAX_VALUE }
}

private fun accentFor(key: String): Color = when (key) {
    "steps" -> Color(0xFF5FD3C4)
    "sleep_duration" -> Color(0xFFB39DDB)
    "blood_pressure" -> Color(0xFF7FC8F8)
    "weight" -> Color(0xFFE8B661)
    else -> Color(0xFF7EE2A8)
}

private fun routeFor(key: String): String? = when (key) {
    "hrv" -> "vitals/HRV"
    "resting_hr" -> "vitals/HR"
    "steps" -> "vitals/STEPS"
    "sleep_duration" -> "vitals/SLEEP"
    "weight" -> "vitals/WEIGHT"
    "blood_pressure" -> "vitals/BP"
    "recovery" -> "vitals/RECOVERY"
    else -> null
}

/** Sentence-case chip wording, matching the web. "Goal not met" reads
 *  better than "Out of range" on a goal metric. */
private fun chipLabel(t: VitalTile): String? = when {
    t.status == null -> null
    t.key == "steps" -> if (t.status == "good") "Goal met" else "Goal not met"
    t.key == "sleep_duration" -> when (t.status) {
        "good" -> "Goal met"
        "typical" -> "Near goal"
        else -> "Goal not met"
    }
    t.key == "blood_pressure" -> t.statusReason?.substringBefore(" range")
    // A 0-100 composite has no "range" to be in — "In range" on a recovery
    // of 35 reads as reassurance the number does not support. Use the
    // server's wording: recovered / partially recovered / under-recovered.
    t.key == "recovery" -> t.statusReason?.replaceFirstChar { it.uppercase() }
    t.status == "watch" -> "Out of range"
    else -> "In range"
}

/** The reference puts remaining-to-goal here, which beats repeating the
 *  percentage the chip already implies. A carried value shows its date. */
private fun qualifier(t: VitalTile): String {
    val v = (t.value as? Number)?.toDouble()
    if (t.key == "steps" && v != null && (t.target ?: 0.0) > 0) {
        val left = ((t.target ?: 0.0) - v).toLong()
        return if (left > 0) "Today • %,d to go".format(left) else "Today • goal met"
    }
    val sd = t.staleDays
    if (sd != null && sd > 0 && t.asOf != null) {
        return runCatching {
            LocalDate.parse(t.asOf).format(DateTimeFormatter.ofPattern("MMM d"))
        }.getOrDefault("Today")
    }
    return "Today"
}

private fun displayValue(t: VitalTile): String? =
    if (t.value == null) null else t.displayValue()

private fun dayLetter(iso: String): String = runCatching {
    when (LocalDate.parse(iso).dayOfWeek.value) {
        1 -> "M"; 2 -> "T"; 3 -> "W"; 4 -> "T"; 5 -> "F"; 6 -> "S"; else -> "S"
    }
}.getOrDefault("")
