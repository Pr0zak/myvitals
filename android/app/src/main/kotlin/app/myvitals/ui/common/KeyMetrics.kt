package app.myvitals.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
    /** The user's saved tile order, as tile keys. The classic home
     *  has always let people reorder and hide tiles; that preference has to
     *  survive the redesign rather than be quietly dropped. Empty = the
     *  catalog order. */
    order: List<String> = emptyList(),
    /** Tile keys the user has hidden. */
    hidden: Set<String> = emptySet(),
    /** Section headings in display order, from the server. */
    groupOrder: List<String> = emptyList(),
    /** Opens the tile reorder / hide sheet, mirroring the web's Edit link. */
    onEdit: (() -> Unit)? = null,
    /** UI-3 — null drops the "Key metrics" heading. Body is nothing BUT key
     *  metrics, so it read "Body / Key metrics" twice over. */
    title: String? = "Key metrics",
    /** UI-3 — tiles already shown elsewhere on the screen (Body's recovery
     *  hero), so the same number is not stated twice. */
    exclude: Set<String> = emptySet(),
    /** UI-3 — two tiers: `cadence == "daily"` tiles stay 2-up chart cards,
     *  `"intermittent"` ones (weight, BP, skin temp) become full-width
     *  compact rows with a 14-day reading strip. The cadence is the
     *  server's; a tile without one stays a card. Off = the home grid. */
    tiered: Boolean = false,
    /** Spark height on the 2-up cards. */
    chartHeight: androidx.compose.ui.unit.Dp = 40.dp,
) {
    val ordered = applyPreference(tiles, order, hidden).filter { it.key !in exclude }
    if (ordered.isEmpty()) return
    Column(modifier.fillMaxWidth()) {
        if (title != null || onEdit != null) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = androidx.compose.ui.Alignment.Bottom,
            ) {
                Text(
                    title ?: "", color = NeonMV.Ink,
                    fontSize = 21.sp, fontWeight = FontWeight.Normal,
                )
                if (onEdit != null) {
                    Text(
                        "Edit", color = NeonMV.Cyan, fontSize = 13.sp,
                        modifier = Modifier
                            .clickable(onClick = onEdit)
                            .padding(4.dp),
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
        }

        // Bucketed under the server's headings, in the server's order. A
        // grouping map duplicated per client is one edit from the two grids
        // disagreeing about where a metric belongs.
        val byGroup = ordered.groupBy { it.group ?: "Other" }
        val heads = groupOrder.filter { byGroup.containsKey(it) } +
            byGroup.keys.filter { it !in groupOrder }
        heads.forEach { head ->
            Text(
                head, color = NeonMV.Ink, fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(top = 18.dp, bottom = 10.dp),
            )
            val inGroup = byGroup[head] ?: emptyList()
            val rows = if (tiered) inGroup.filter { it.cadence == "intermittent" } else emptyList()
            val cards = inGroup - rows.toSet()
            cards.chunked(2).forEach { pair ->
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
                            target = t.target,
                            bars = t.key == "steps",
                            span = if (t.key in INTERMITTENT) 14 else 7,
                            accent = accentFor(t.key),
                            onClick = { routeFor(t.key)?.let(onOpen) },
                            chartHeight = chartHeight,
                        )
                    }
                }
                // No Spacer: a lone trailing card fills the row rather
                // than sitting beside a hole. Three of five rows rendered
                // with an empty right half before this.
            }
            }
            rows.forEach { t ->
                IntermittentRow(t, onClick = routeFor(t.key)?.let { r -> { onOpen(r) } })
                Spacer(Modifier.height(10.dp))
            }
        }
    }
}

/**
 * UI-3 — the compact row for a metric measured by hand every few days.
 *
 * As a 2-up chart card these were mostly an empty axis ("No readings in the
 * last 14 days", or one lonely dot), so the card's biggest element said
 * nothing. The questions that matter for a scale or a cuff are "what was the
 * last reading, when, and how often do I take one" — the value with its own
 * date answers the first two, and the 14-dot strip (filled where the server
 * series holds a reading) answers the third at a glance.
 */
@Composable
private fun IntermittentRow(t: VitalTile, onClick: (() -> Unit)?) {
    val accent = accentFor(t.key)
    val hasData = t.value != null
    Column(
        Modifier
            .fillMaxWidth()
            .background(NeonMV.Card, androidx.compose.foundation.shape.RoundedCornerShape(18.dp))
            .border(1.dp, accent.copy(alpha = 0.16f), androidx.compose.foundation.shape.RoundedCornerShape(18.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(t.label, color = NeonMV.Muted, fontSize = 12.sp, maxLines = 1)
                Row(verticalAlignment = androidx.compose.ui.Alignment.Bottom) {
                    Text(
                        if (hasData) t.displayValue() else "No data",
                        color = if (hasData) NeonMV.Ink else NeonMV.Muted,
                        fontFamily = app.myvitals.ui.neon.NeonNumberFamily,
                        fontWeight = if (hasData) FontWeight.Bold else FontWeight.Medium,
                        fontSize = if (hasData) 24.sp else 17.sp,
                        letterSpacing = (-0.5).sp,
                        maxLines = 1,
                    )
                    if (hasData && t.unit.isNotBlank()) {
                        Spacer(Modifier.width(4.dp))
                        Text(
                            t.unit, color = NeonMV.Muted, fontSize = 12.sp, maxLines = 1,
                            softWrap = false, modifier = Modifier.padding(bottom = 3.dp),
                        )
                    }
                }
            }
            chipLabel(t)?.let { label ->
                val tone = when (t.status) {
                    "good" -> NeonMV.Lime
                    "watch" -> NeonMV.Amber
                    else -> NeonMV.Muted
                }
                Text(
                    label, color = tone, fontSize = 10.sp, fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    modifier = Modifier
                        .background(tone.copy(alpha = 0.13f),
                            androidx.compose.foundation.shape.RoundedCornerShape(999.dp))
                        .padding(horizontal = 9.dp, vertical = 3.dp),
                )
            }
        }
        Text(
            rowQualifier(t), color = NeonMV.Muted, fontSize = 11.sp,
            maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
        )
        Spacer(Modifier.height(8.dp))
        ReadingStrip(t.series.takeLast(STRIP_DAYS).map { it.value != null }, accent)
    }
}

private const val STRIP_DAYS = 14

/** One dot per day, oldest left, filled where a reading exists. Presence
 *  only — the heights of the readings belong on the detail chart. */
@Composable
private fun ReadingStrip(present: List<Boolean>, accent: Color) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        // Pad on the left so a short series still anchors today at the right.
        val padded = List((STRIP_DAYS - present.size).coerceAtLeast(0)) { false } + present
        padded.forEachIndexed { i, on ->
            val today = i == padded.lastIndex
            Box(
                Modifier
                    .size(if (today) 9.dp else 8.dp)
                    .background(
                        if (on) accent else NeonMV.Track,
                        androidx.compose.foundation.shape.CircleShape,
                    )
                    .then(
                        if (today && !on) Modifier.border(
                            1.dp, NeonMV.Muted.copy(alpha = 0.6f),
                            androidx.compose.foundation.shape.CircleShape,
                        ) else Modifier,
                    ),
            )
        }
    }
}

/** "as of Sep 20 · 9.6 lb to lose" — the reading's own date always leads,
 *  because on these metrics the date is half the information. The goal
 *  note is the server's sentence, rendered verbatim (OG3-A4). */
private fun rowQualifier(t: VitalTile): String {
    if (t.value == null) return "No readings in the last $STRIP_DAYS days"
    val sd = t.staleDays
    val whenTxt = if (sd == null || sd <= 0 || t.asOf == null) "Today" else runCatching {
        "as of " + LocalDate.parse(t.asOf).format(DateTimeFormatter.ofPattern("MMM d"))
    }.getOrDefault("Today")
    return listOfNotNull(whenTxt, t.goalNote).joinToString(" · ")
}



/** Vital enum name → tiles key, so the saved preference (written against
 *  the old badge grid) still means something here. */
/** Measured every few weeks, not daily — a 7-day window is usually empty
 *  for these, so they plot the full 14 days the server sends rather than a
 *  bare axis over blank space. */
private val INTERMITTENT = setOf("weight", "blood_pressure")

/**
 * TILE-1: `order` and `hidden` now arrive as tile keys from
 * `GET /profile/tile-prefs`, already reconciled against the tiles that
 * exist and already translated out of the legacy `Vital` enum names.
 *
 * The private VITAL_TO_KEY table this used to carry was missing
 * SKIN_TEMP, so any saved order sorted skin temp to the very end — and
 * the web copy of the same table had the identical gap, which is exactly
 * the class of two-clients-disagree bug the server-owns-it rule exists
 * to prevent.
 */
private fun applyPreference(
    tiles: List<VitalTile>, order: List<String>, hidden: Set<String>,
): List<VitalTile> {
    val visible = tiles.filter { it.key !in hidden }
    if (order.isEmpty()) return visible
    val rank = order.withIndex().associate { (i, k) -> k to i }
    // Defensive only — the server's order covers every current tile.
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
    "measurements" -> Vital.MEASUREMENTS
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
    // OG3-A4 — rendered verbatim. The distance to a weight goal is signed and
    // its wording depends on which way the goal points, so the server builds
    // the sentence; deriving `target - value` here would put a second opinion
    // about direction on a client, which is what GOAL-STATE exists to stop.
    val sd = t.staleDays
    val stale = if (sd != null && sd > 0 && t.asOf != null) {
        runCatching {
            LocalDate.parse(t.asOf).format(DateTimeFormatter.ofPattern("MMM d"))
        }.getOrNull()
    } else null
    t.goalNote?.let { return "${stale ?: "Today"} • $it" }
    return stale ?: "Today"
}

private fun displayValue(t: VitalTile): String? =
    if (t.value == null) null else t.displayValue()

private fun dayLetter(iso: String): String = runCatching {
    when (LocalDate.parse(iso).dayOfWeek.value) {
        1 -> "M"; 2 -> "T"; 3 -> "W"; 4 -> "T"; 5 -> "F"; 6 -> "S"; else -> "S"
    }
}.getOrDefault("")
