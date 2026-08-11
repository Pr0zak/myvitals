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
import androidx.compose.material.icons.outlined.ThumbDown
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
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
) {
    if (events.isEmpty()) return
    Column(modifier.fillMaxWidth()) {
        events.forEach { e ->
            EventCard(e, onVote)
            Spacer(Modifier.height(12.dp))
        }
    }
}

private val LANES = listOf("awake", "rem", "light", "deep")
private val LANE_LABEL = mapOf(
    "awake" to "Total awake", "rem" to "REM", "light" to "Light", "deep" to "Deep",
)
private val LANE_TONE = mapOf(
    "awake" to Color(0xFFF48FB1), "rem" to Color(0xFF4DD0E1),
    "light" to Color(0xFF7AA7FF), "deep" to Color(0xFF9575CD),
)

@Composable
private fun EventCard(e: NarrativeEvent, onVote: ((String, String?) -> Unit)?) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(Color(0xFF1B1C1F), RoundedCornerShape(20.dp))
            .padding(16.dp),
    ) {
        val isNap = e.kind == "nap"
        Box(
            Modifier
                .background(
                    if (isNap) Color(0x33E8B661) else Color(0x389575CD),
                    RoundedCornerShape(999.dp),
                )
                .padding(horizontal = 10.dp, vertical = 3.dp),
        ) {
            Text(
                if (isNap) "Nap" else "Sleep",
                color = if (isNap) Color(0xFFFFD7A1) else Color(0xFFD7C9FF),
                fontSize = 11.sp, fontWeight = FontWeight.Medium,
            )
        }
        Spacer(Modifier.height(10.dp))

        Text(e.headline, color = Color(0xFFE9EDF2), fontSize = 20.sp,
            fontWeight = FontWeight.Normal)
        Spacer(Modifier.height(4.dp))
        Text(e.detail, color = Color(0xFFB9BEC6), fontSize = 13.sp)
        Spacer(Modifier.height(14.dp))

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
                Text(clock(e.start), color = Color(0xFF6F767F), fontSize = 10.sp)
                Text(clock(e.end), color = Color(0xFF6F767F), fontSize = 10.sp)
            }
        }

        if (onVote != null) {
            Spacer(Modifier.height(12.dp))
            // Optimism lives in the caller: it flips local state, then
            // writes. A vote the server rejected must not stay lit.
            Row {
                Thumb(
                    up = true, active = e.feedback == "up",
                    onClick = { onVote(e.id, if (e.feedback == "up") null else "up") },
                )
                Spacer(Modifier.width(4.dp))
                Thumb(
                    up = false, active = e.feedback == "down",
                    onClick = { onVote(e.id, if (e.feedback == "down") null else "down") },
                )
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
