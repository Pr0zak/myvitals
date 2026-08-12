package app.myvitals.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import app.myvitals.ui.vitals.Vital
import app.myvitals.ui.vitals.accent
import app.myvitals.ui.neon.NeonMV
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
    /** Section headings in display order, from the server. */
    groupOrder: List<String> = emptyList(),
    /** Opens the tile reorder / hide sheet, mirroring the web's Edit link. */
    onEdit: (() -> Unit)? = null,
) {
    val ordered = applyPreference(tiles, order, hidden)
    if (ordered.isEmpty()) return
    Column(modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = androidx.compose.ui.Alignment.Bottom,
        ) {
            Text(
                "Key metrics", color = Color(0xFFE9EDF2),
                fontSize = 21.sp, fontWeight = FontWeight.Normal,
            )
            if (onEdit != null) {
                Text(
                    "Edit", color = Color(0xFF8AB4F8), fontSize = 13.sp,
                    modifier = Modifier
                        .clickable(onClick = onEdit)
                        .padding(4.dp),
                )
            }
        }
        Spacer(Modifier.height(4.dp))

        // Bucketed under the server's headings, in the server's order. A
        // grouping map duplicated per client is one edit from the two grids
        // disagreeing about where a metric belongs.
        val byGroup = ordered.groupBy { it.group ?: "Other" }
        val heads = groupOrder.filter { byGroup.containsKey(it) } +
            byGroup.keys.filter { it !in groupOrder }
        heads.forEach { head ->
            Text(
                head, color = Color(0xFFE9EDF2), fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(top = 18.dp, bottom = 10.dp),
            )
            (byGroup[head] ?: emptyList()).chunked(2).forEach { pair ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .height(IntrinsicSize.Min)
                    .padding(bottom = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                pair.forEach { t ->
                    // fillMaxHeight inside an IntrinsicSize.Min row makes both
                    // cards take the taller one's height, so a card whose
                    // chart is empty (weight and BP are measured weekly) ends
                    // level with its neighbour instead of stopping short.
                    Box(Modifier.weight(1f).fillMaxHeight()) {
                        MetricCard(
                            name = t.label,
                            value = displayValue(t),
                            unit = t.unit,
                            qualifier = qualifier(t),
                            series = t.series.map { it.value },
                            dayLetters = t.series.map { dayLetter(it.date) },
                            status = t.status,
                            statusLabel = chipLabel(t),
                            delta = t.delta,
                            higherIsBetter = t.higherIsBetter,
                            bandLow = t.bandLow,
                            bandHigh = t.bandHigh,
                            target = if (t.key == "steps") t.target else null,
                            bars = t.key == "steps",
                            span = if (t.key in INTERMITTENT) 14 else 7,
                            accent = accentFor(t.key),
                            onClick = { routeFor(t.key)?.let(onOpen) },
                        )
                    }
                }
                // No Spacer: a lone trailing card fills the row rather
                // than sitting beside a hole. Three of five rows rendered
                // with an empty right half before this.
            }
            }
        }
    }
}



/** Vital enum name → tiles key, so the saved preference (written against
 *  the old badge grid) still means something here. */
/** Measured every few weeks, not daily — a 7-day window is usually empty
 *  for these, so they plot the full 14 days the server sends rather than a
 *  bare axis over blank space. */
private val INTERMITTENT = setOf("weight", "blood_pressure")

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

/**
 * The accent of the DETAIL SCREEN this card opens.
 *
 * These were a separate hand-picked set left over from the classic theme, so a
 * mint-green "Resting HR" card opened a cyan heart-rate chart and an amber
 * Weight card opened an amber one only by coincidence. Deriving both from the
 * same `Vital` the card routes to means they cannot drift apart again.
 */
private fun accentFor(key: String): Color = vitalFor(key)?.accent ?: NeonMV.Cyan

private fun vitalFor(key: String): Vital? = when (key) {
    "hrv" -> Vital.HRV
    "resting_hr" -> Vital.HR
    "steps" -> Vital.STEPS
    "sleep_duration" -> Vital.SLEEP
    "weight" -> Vital.WEIGHT
    "blood_pressure" -> Vital.BP
    "recovery" -> Vital.RECOVERY
    "skin_temp" -> Vital.SKIN_TEMP
    else -> null
}

private fun routeFor(key: String): String? =
    vitalFor(key)?.let { "vitals/${it.name}" }

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
