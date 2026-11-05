package app.myvitals.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ReadinessDetail
import app.myvitals.sync.VitalTile
import app.myvitals.sync.VitalTilesRollup
import app.myvitals.sync.WeekProgress
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumberFamily

/**
 * Today brief — the home hero, phone twin of `TodayBrief.vue`.
 *
 * Replaces the weekly-steps ring + three chips (TodayHero) and the
 * Readiness card under "Health status". Those put readiness on screen
 * twice and steps three times before the first metric card; the hero
 * answered "how far through the week's steps am I", which is not the
 * question anyone opens the app with in the morning.
 *
 * One concentric tri-ring — the app's own mark — with readiness in the
 * centre: Sleep outer (magenta), Move middle (lime), Readiness inner
 * (cyan). Beside it a plain legend in the same order, which carries the
 * numbers. The hero sits on the page ground rather than in a card; it is
 * the only element on the screen that does.
 *
 * Every number is the server's: tile values and targets from
 * /summary/tiles, readiness and its band from /summary/readiness, the
 * weekly figure from the tiles response's `week`. The only arithmetic here
 * is value / target for the arc sweep, which is geometry, not a metric.
 */
@Composable
fun TodayBrief(
    tiles: List<VitalTile>,
    week: WeekProgress?,
    readiness: ReadinessDetail?,
    rollup: VitalTilesRollup?,
    syncNote: String?,
    onOpen: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    fun tile(key: String) = tiles.firstOrNull { it.key == key }
    val sleep = tile("sleep_duration")
    val steps = tile("steps")

    fun frac(t: VitalTile?): Float? {
        val v = (t?.value as? Number)?.toDouble() ?: return null
        val target = t.target ?: return null
        if (target <= 0) return null
        return (v / target).toFloat().coerceIn(0f, 1f)
    }
    val score = readiness?.score

    Column(modifier.fillMaxWidth().padding(top = 4.dp, bottom = 20.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .size(176.dp)
                    .clip(RoundedCornerShape(88.dp))
                    .clickable { onOpen("vitals/RECOVERY") },
                contentAlignment = Alignment.Center,
            ) {
                TriRing(
                    sleep = frac(sleep),
                    move = frac(steps),
                    ready = score?.let { (it / 100.0).toFloat().coerceIn(0f, 1f) },
                )
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        score?.let { "%.0f".format(it) } ?: "—",
                        color = NeonMV.Ink, fontSize = 38.sp,
                        fontFamily = NeonNumberFamily, fontWeight = FontWeight.Medium,
                        letterSpacing = (-1).sp,
                    )
                    Text("Readiness", color = NeonMV.Muted, fontSize = 11.sp)
                }
            }
            Spacer(Modifier.width(18.dp))
            Column(
                Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                LegendRow(
                    color = NeonMV.Magenta, label = "Sleep",
                    value = fmtSleep(sleep?.value),
                    sub = sleep?.target?.let { "of ${fmtHours(it)}" },
                ) { onOpen("vitals/SLEEP") }
                LegendRow(
                    color = NeonMV.Lime, label = "Move",
                    value = (steps?.value as? Number)?.let { "%,d".format(it.toLong()) } ?: "—",
                    sub = week?.let { "${Math.round(it.pct)}% of the week" }
                        ?: steps?.target?.let { "of %,d".format(it.toLong()) },
                ) { onOpen("vitals/STEPS") }
                LegendRow(
                    color = NeonMV.Cyan, label = "Readiness",
                    value = readiness?.band?.replaceFirstChar { it.uppercase() } ?: "—",
                    sub = if (score != null) "50 is your normal"
                        else readiness?.reason?.replaceFirstChar { it.uppercase() },
                ) { onOpen("vitals/RECOVERY") }
            }
        }

        // One quiet line instead of the "Health status" section: the
        // roll-up and freshness qualify the numbers above, so they sit
        // directly under them with no card of their own.
        val roll = rollup?.takeIf { it.judged > 0 }
        if (roll != null || syncNote != null) {
            Spacer(Modifier.height(14.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                if (roll != null) {
                    val allIn = roll.inRange == roll.judged
                    Box(
                        Modifier.size(6.dp).background(
                            if (allIn) NeonMV.Lime else NeonMV.Amber,
                            RoundedCornerShape(3.dp),
                        ),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "${roll.inRange} of ${roll.judged} vitals in your range",
                        color = NeonMV.Ink.copy(alpha = 0.85f), fontSize = 13.sp,
                    )
                }
                Spacer(Modifier.weight(1f))
                syncNote?.let { Text(it, color = NeonMV.Muted, fontSize = 12.sp) }
            }
        }
    }
}

@Composable
private fun LegendRow(
    color: Color, label: String, value: String, sub: String?,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier
                .padding(top = 5.dp)
                .size(width = 3.dp, height = 30.dp)
                .background(color, RoundedCornerShape(2.dp)),
        )
        Spacer(Modifier.width(10.dp))
        Column {
            Text(label, color = NeonMV.Muted, fontSize = 12.sp)
            Text(
                value, color = NeonMV.Ink, fontSize = 20.sp,
                fontFamily = NeonNumberFamily, fontWeight = FontWeight.Medium,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            sub?.let {
                Text(it, color = NeonMV.Muted, fontSize = 11.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** Three concentric arcs from 12 o'clock. A null fraction draws the track
 *  only — "no reading" must not look like "zero". */
@Composable
private fun TriRing(sleep: Float?, move: Float?, ready: Float?) {
    Canvas(Modifier.fillMaxSize()) {
        val stroke = 13.dp.toPx()
        val gap = 4.dp.toPx()
        val rings = listOf(
            NeonMV.Magenta to sleep,
            NeonMV.Lime to move,
            NeonMV.Cyan to ready,
        )
        rings.forEachIndexed { i, (color, f) ->
            val inset = stroke / 2f + i * (stroke + gap)
            val d = size.minDimension - inset * 2f
            val tl = Offset((size.width - d) / 2f, (size.height - d) / 2f)
            val sz = Size(d, d)
            drawArc(color.copy(alpha = 0.13f), 0f, 360f, false, tl, sz, style = Stroke(stroke))
            if (f != null && f > 0f) {
                drawArc(
                    color.copy(alpha = 0.12f), -90f, 360f * f, false, tl, sz,
                    style = Stroke(stroke + 4.dp.toPx(), cap = StrokeCap.Round),
                )
                drawArc(
                    color, -90f, 360f * f, false, tl, sz,
                    style = Stroke(stroke, cap = StrokeCap.Round),
                )
            }
        }
    }
}

private fun fmtSleep(v: Any?): String {
    val h = (v as? Number)?.toDouble() ?: return "—"
    val whole = h.toInt()
    val m = Math.round((h - whole) * 60).toInt()
    return "${whole}h ${m}m"
}

private fun fmtHours(h: Double): String =
    if (h == Math.floor(h)) "${h.toInt()}h" else fmtSleep(h)
