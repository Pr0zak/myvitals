package app.myvitals.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.ThumbDown
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.NarrativeEvent
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Narrative event cards — phone twin of `NarrativeCards.vue`.
 *
 * "We tracked a nap · It looks like you took a nap at 12:45 PM for 52 min",
 * with the hypnogram underneath: one lane per stage, each segment placed by
 * WHEN it happened rather than summed into a single bar. A stacked total
 * would say "27 min light" without showing it came in two blocks either
 * side of the deep phase, which is the part worth seeing.
 *
 * The sentence and the nap-vs-night classification are the SERVER's — see
 * analytics/events.py — so both clients say the same thing.
 */
@Composable
fun NarrativeCards(
    events: List<NarrativeEvent>,
    modifier: Modifier = Modifier,
    /** null clears the vote. Toggling an active thumb should undo it. */
    onVote: ((String, String?) -> Unit)? = null,
    /** Backs the ⋮ menu. Omitted, the control is hidden rather than opening
     *  onto nothing. */
    onOpenDetail: (() -> Unit)? = null,
) {
    if (events.isEmpty()) return
    Column(modifier.fillMaxWidth()) {
        events.forEachIndexed { i, e ->
            dayBreakBefore(events, i)?.let { label ->
                DayBreak(label)
            }
            EventCard(e, onVote, onOpenDetail)
            Spacer(Modifier.height(12.dp))
        }
    }
}

/** "— Yesterday —" between cards from different days, mirroring the web. */
@Composable
private fun DayBreak(label: String) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.weight(1f).height(1.dp).background(Color(0xFF3A3D45)))
        Text(label, color = Color(0xFFB9BEC6), fontSize = 13.sp,
            modifier = Modifier.padding(horizontal = 12.dp))
        Box(Modifier.weight(1f).height(1.dp).background(Color(0xFF3A3D45)))
    }
}

@Composable
private fun StatCard(st: app.myvitals.sync.NarrativeStat) {
    val (fg, bg) = when (st.tone) {
        "good" -> Color(0xFF7EE2A8) to Color(0x287EE2A8)
        "watch" -> Color(0xFFE8B661) to Color(0x28E8B661)
        else -> Color(0xFFC7CBD1) to Color(0x24C7CBD1)
    }
    Column(
        Modifier
            .fillMaxWidth()
            .background(Color(0xFF232428), RoundedCornerShape(14.dp))
            .padding(12.dp),
    ) {
        Text(st.label, color = Color(0xFFB9BEC6), fontSize = 12.sp)
        Spacer(Modifier.height(2.dp))
        Text(st.value, color = Color(0xFFE9EDF2), fontSize = 22.sp,
            fontWeight = FontWeight.Light, maxLines = 1,
            overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(8.dp))
        Box(
            Modifier.background(bg, RoundedCornerShape(999.dp))
                .padding(horizontal = 9.dp, vertical = 3.dp),
        ) {
            Text(st.chip, color = fg, fontSize = 11.sp,
                fontWeight = FontWeight.Medium)
        }
    }
}

private fun dayBreakBefore(events: List<NarrativeEvent>, i: Int): String? {
    if (i == 0) return null
    val prev = dayOf(events[i - 1].end) ?: return null
    val cur = dayOf(events[i].end) ?: return null
    if (prev == cur) return null
    val today = java.time.LocalDate.now()
    return when (cur) {
        today -> "Today"
        today.minusDays(1) -> "Yesterday"
        else -> cur.format(DateTimeFormatter.ofPattern("MMM d"))
    }
}

private fun dayOf(iso: String): java.time.LocalDate? = runCatching {
    Instant.parse(iso).atZone(ZoneId.systemDefault()).toLocalDate()
}.getOrNull()

/** Card stamp: when the session ENDED, which is when the card would have
 *  appeared. Earlier days are named rather than shown as a bare time. */
private fun stamp(e: NarrativeEvent): String {
    val d = dayOf(e.end) ?: return clock(e.end)
    val today = java.time.LocalDate.now()
    val t = clock(e.end)
    return when (d) {
        today -> t
        today.minusDays(1) -> "Yesterday, $t"
        else -> "${d.format(DateTimeFormatter.ofPattern("MMM d"))}, $t"
    }
}

/** The midpoint label the reference puts between start and end. */
private fun midClock(e: NarrativeEvent): String = runCatching {
    val a = Instant.parse(e.start).toEpochMilli()
    val b = Instant.parse(e.end).toEpochMilli()
    DateTimeFormatter.ofPattern("h:mm a")
        .format(Instant.ofEpochMilli((a + b) / 2).atZone(ZoneId.systemDefault()))
}.getOrDefault("")

private val LANES = listOf("awake", "rem", "light", "deep")
private val LANE_LABEL = mapOf(
    "awake" to "Total awake", "rem" to "REM", "light" to "Light", "deep" to "Deep",
)
private val LANE_TONE = mapOf(
    "awake" to Color(0xFFF48FB1), "rem" to Color(0xFF4DD0E1),
    "light" to Color(0xFF7AA7FF), "deep" to Color(0xFF9575CD),
)

@Composable
private fun EventCard(
    e: NarrativeEvent,
    onVote: ((String, String?) -> Unit)?,
    onOpenDetail: (() -> Unit)?,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(Color(0xFF1B1C1F), RoundedCornerShape(20.dp))
            .padding(16.dp),
    ) {
        val isNap = e.kind == "nap"

        // Icon + timestamp, not a pill — the reference stamps the card with
        // when it happened and lets the headline carry the meaning.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Outlined.Bedtime, contentDescription = null,
                tint = Color(0xFFB39DDB), modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(7.dp))
            Text(stamp(e), color = Color(0xFFB9BEC6), fontSize = 12.sp)
        }
        Spacer(Modifier.height(8.dp))

        Text(e.headline, color = Color(0xFFE9EDF2), fontSize = 21.sp,
            fontWeight = FontWeight.Normal)
        // Only the nap carries a sentence; a scored night says it in stats.
        if (isNap) {
            Spacer(Modifier.height(4.dp))
            Text(e.detail, color = Color(0xFFB9BEC6), fontSize = 13.sp)
        }

        if (e.stats.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                e.stats.forEach { st ->
                    Box(Modifier.weight(1f)) { StatCard(st) }
                }
            }
        }
        Spacer(Modifier.height(12.dp))

        Column(
            Modifier
                .fillMaxWidth()
                .background(Color(0xFF131417), RoundedCornerShape(14.dp))
                .padding(12.dp),
        ) {
            val seen = e.stages.map { it.stage }.toSet()
            LANES.filter { it in seen || it == "awake" }.forEach { stage ->
                val total = e.stages.firstOrNull { it.stage == stage }?.durationS ?: 0
                Text(
                    "${LANE_LABEL[stage]} · ${fmtMins(total)}",
                    color = Color(0xFFE9EDF2), fontSize = 12.sp,
                )
                Spacer(Modifier.height(4.dp))
                StageTrack(e, stage, LANE_TONE[stage] ?: Color(0xFF7AA7FF))
                Spacer(Modifier.height(10.dp))
            }
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(clock(e.start), color = Color(0xFF6F767F), fontSize = 11.sp)
                Text(midClock(e), color = Color(0xFF6F767F), fontSize = 11.sp)
                Text(clock(e.end), color = Color(0xFF6F767F), fontSize = 11.sp)
            }
        }

        if (onVote != null) {
            Spacer(Modifier.height(12.dp))
            // Optimism lives in the caller: it flips local state, then
            // writes. A vote the server rejected must not stay lit.
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Thumb(
                    up = true, active = e.feedback == "up",
                    onClick = { onVote(e.id, if (e.feedback == "up") null else "up") },
                )
                Spacer(Modifier.width(4.dp))
                Thumb(
                    up = false, active = e.feedback == "down",
                    onClick = { onVote(e.id, if (e.feedback == "down") null else "down") },
                )
                Spacer(Modifier.weight(1f))
                onOpenDetail?.let { open ->
                    Icon(
                        Icons.Outlined.MoreVert, contentDescription = "More",
                        tint = Color(0xFF8D949D),
                        modifier = Modifier
                            .clickable(onClick = open)
                            .padding(6.dp)
                            .size(18.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun Thumb(up: Boolean, active: Boolean, onClick: () -> Unit) {
    val tint = if (active) Color(0xFF7EE2A8) else Color(0xFF8D949D)
    Box(
        Modifier
            .background(
                if (active) Color(0x247EE2A8) else Color.Transparent,
                RoundedCornerShape(999.dp),
            )
            .clickable(onClick = onClick)
            .padding(6.dp),
    ) {
        Icon(
            if (up) Icons.Outlined.ThumbUp else Icons.Outlined.ThumbDown,
            contentDescription = if (up) "This looks right" else "This looks wrong",
            tint = tint,
            modifier = Modifier.size(18.dp),
        )
    }
}

/** One stage lane: its segments positioned across the session's duration. */
@Composable
private fun StageTrack(e: NarrativeEvent, stage: String, tone: Color) {
    val t0 = runCatching { Instant.parse(e.start).toEpochMilli() }.getOrNull()
    val t1 = runCatching { Instant.parse(e.end).toEpochMilli() }.getOrNull()
    BoxWithConstraints(
        Modifier
            .fillMaxWidth()
            .height(14.dp)
            .background(Color(0xFF24262B), RoundedCornerShape(7.dp)),
    ) {
        val span = if (t0 != null && t1 != null) (t1 - t0).toDouble() else 0.0
        if (span <= 0) return@BoxWithConstraints
        val full = maxWidth
        e.segments.filter { it.stage == stage }.forEach { seg ->
            val start = runCatching { Instant.parse(seg.start).toEpochMilli() }
                .getOrNull() ?: return@forEach
            val leftFrac = ((start - t0!!) / span).coerceIn(0.0, 1.0)
            val widthFrac = ((seg.durationS * 1000.0) / span).coerceIn(0.0, 1.0 - leftFrac)
            Box(
                Modifier
                    .offset(x = full * leftFrac.toFloat())
                    // Floor the width so a 30-second stage stays visible
                    // instead of collapsing to an invisible sliver.
                    .width((full * widthFrac.toFloat()).coerceAtLeast(3.dp))
                    .height(14.dp)
                    .background(tone, RoundedCornerShape(7.dp)),
            )
        }
    }
}

private fun fmtMins(seconds: Int): String {
    val m = Math.round(seconds / 60.0).toInt()
    if (m < 60) return "$m min"
    val h = m / 60
    val r = m % 60
    return if (r == 0) "${h}h" else "${h}h ${r}m"
}

private fun clock(iso: String): String = runCatching {
    DateTimeFormatter.ofPattern("h:mm a")
        .format(Instant.parse(iso).atZone(ZoneId.systemDefault()))
}.getOrDefault("")
