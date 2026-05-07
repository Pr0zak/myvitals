package app.myvitals.ui.activities

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.TimePoint
import app.myvitals.ui.MV
import java.time.Instant

private val ZONE_COLORS = listOf(
    Color(0xFF38BDF8),  // Z1 — recovery
    Color(0xFF22C55E),  // Z2 — endurance
    Color(0xFFEAB308),  // Z3 — tempo
    Color(0xFFF97316),  // Z4 — threshold
    Color(0xFFEF4444),  // Z5 — VO2
)
private val ZONE_LABELS = listOf("Z1", "Z2", "Z3", "Z4", "Z5")

private fun zoneFor(bpm: Double, maxHr: Int): Int {
    val pct = bpm / maxHr
    return when {
        pct < 0.60 -> 0
        pct < 0.70 -> 1
        pct < 0.80 -> 2
        pct < 0.90 -> 3
        else -> 4
    }
}

@Composable
fun ActivityHrChart(points: List<TimePoint>, maxHr: Int = 190) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("HEART RATE", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (points.size < 2) {
                Text("Not enough HR samples for this activity.",
                    color = MV.OnSurfaceVariant, fontSize = 12.sp)
                return@Card
            }
            val parsed = remember(points) {
                points.mapNotNull { p ->
                    val t = runCatching { Instant.parse(p.time).toEpochMilli() }
                        .getOrNull() ?: return@mapNotNull null
                    t to p.value
                }.sortedBy { it.first }.distinctBy { it.first }
            }
            // Downsample for perf — Canvas can handle hundreds of segments
            // but a 2k+ HR series isn't worth pixel-accurate detail anyway.
            val sampled = remember(parsed) {
                val cap = 600
                if (parsed.size <= cap) parsed
                else {
                    val stride = parsed.size.toDouble() / cap
                    (0 until cap).map { i ->
                        parsed[(i * stride).toInt().coerceAtMost(parsed.lastIndex)]
                    }
                }
            }
            val minBpm = sampled.minOf { it.second }
            val maxBpm = sampled.maxOf { it.second }
            val avgBpm = sampled.map { it.second }.average()

            // Time-in-zone (seconds) — sum of segment widths in each zone.
            val zoneSecs = remember(sampled, maxHr) {
                val out = LongArray(5)
                for (i in 0 until sampled.size - 1) {
                    val (t0, v) = sampled[i]
                    val (t1, _) = sampled[i + 1]
                    val z = zoneFor(v, maxHr)
                    out[z] += (t1 - t0) / 1000L
                }
                out
            }

            Box(Modifier.fillMaxWidth().height(180.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val padX = 28.dp.toPx()  // leave room for y-axis labels
                    val padTop = 8.dp.toPx()
                    val padBot = 16.dp.toPx()
                    val plotW = size.width - padX
                    val plotH = size.height - padTop - padBot
                    val tStart = sampled.first().first
                    val tEnd = sampled.last().first
                    val tSpan = (tEnd - tStart).toFloat().coerceAtLeast(1f)

                    // Y range — pad min/max a bit.
                    val yMin = (minBpm - 10).coerceAtLeast(40.0).toFloat()
                    val yMax = (maxBpm + 10).coerceAtMost(220.0).toFloat()
                    val ySpan = (yMax - yMin).coerceAtLeast(1f)

                    // Zone background bands (faint).
                    val zoneEdges = listOf(0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
                    for (zi in 0..4) {
                        val lo = (maxHr * zoneEdges[zi]).toFloat()
                        val hi = (maxHr * zoneEdges[zi + 1]).toFloat()
                        if (hi < yMin || lo > yMax) continue
                        val y0 = padTop + ((yMax - hi.coerceAtMost(yMax)) / ySpan) * plotH
                        val y1 = padTop + ((yMax - lo.coerceAtLeast(yMin)) / ySpan) * plotH
                        drawRect(
                            color = ZONE_COLORS[zi].copy(alpha = 0.07f),
                            topLeft = Offset(padX, y0),
                            size = Size(plotW, (y1 - y0).coerceAtLeast(0f)),
                        )
                    }

                    // Y-axis tick lines + labels via raw drawText? — Compose
                    // Canvas doesn't have a text helper, so we leave the
                    // numeric labels to a Row outside; we just draw faint
                    // gridlines.
                    val ticks = listOf(yMin, (yMin + yMax) / 2f, yMax)
                    for (yv in ticks) {
                        val py = padTop + ((yMax - yv) / ySpan) * plotH
                        drawLine(
                            color = MV.OnSurfaceDim.copy(alpha = 0.18f),
                            start = Offset(padX, py),
                            end = Offset(size.width, py),
                            strokeWidth = 0.7.dp.toPx(),
                        )
                    }

                    // Per-segment colored line — pick the zone of the
                    // segment's mean.
                    for (i in 0 until sampled.size - 1) {
                        val (t0, v0) = sampled[i]
                        val (t1, v1) = sampled[i + 1]
                        val mean = (v0 + v1) * 0.5
                        val zi = zoneFor(mean, maxHr)
                        val x0 = padX + ((t0 - tStart).toFloat() / tSpan) * plotW
                        val x1 = padX + ((t1 - tStart).toFloat() / tSpan) * plotW
                        val y0 = padTop + ((yMax - v0.toFloat()) / ySpan) * plotH
                        val y1 = padTop + ((yMax - v1.toFloat()) / ySpan) * plotH
                        drawLine(
                            color = ZONE_COLORS[zi],
                            start = Offset(x0, y0),
                            end = Offset(x1, y1),
                            strokeWidth = 2.dp.toPx(),
                        )
                    }

                    // Avg line
                    val avgY = padTop + ((yMax - avgBpm.toFloat()) / ySpan) * plotH
                    drawLine(
                        color = MV.OnSurfaceVariant.copy(alpha = 0.5f),
                        start = Offset(padX, avgY), end = Offset(size.width, avgY),
                        strokeWidth = 1.dp.toPx(),
                        pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(
                            floatArrayOf(4.dp.toPx(), 3.dp.toPx())
                        ),
                    )
                }
                // Y-axis labels overlaid as Text rows
                Column(
                    Modifier.fillMaxSize().padding(start = 0.dp, end = 0.dp),
                    verticalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("${(maxBpm + 10).toInt()}", color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Spacer(Modifier.height(0.dp))
                    Text("${((minBpm + maxBpm) / 2).toInt()}",
                        color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("${(minBpm - 10).coerceAtLeast(40.0).toInt()}",
                        color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp, bottom = 12.dp))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row {
                Stat("Min", "${minBpm.toInt()} bpm")
                Spacer(Modifier.width(16.dp))
                Stat("Avg", "%.0f bpm".format(avgBpm))
                Spacer(Modifier.width(16.dp))
                Stat("Max", "${maxBpm.toInt()} bpm")
            }
            Spacer(Modifier.height(12.dp))
            Text("TIME IN ZONE", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            ZoneBar(zoneSecs)
            Spacer(Modifier.height(8.dp))
            Column {
                for (zi in 0 until 5) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(vertical = 1.dp)) {
                        Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp))
                            .background(ZONE_COLORS[zi]))
                        Spacer(Modifier.width(6.dp))
                        Text(ZONE_LABELS[zi], color = MV.OnSurface,
                            fontSize = 11.sp, modifier = Modifier.width(28.dp))
                        Text(fmtMins(zoneSecs[zi]), color = MV.OnSurfaceVariant,
                            fontSize = 11.sp, modifier = Modifier.width(60.dp))
                        val total = zoneSecs.sum().coerceAtLeast(1)
                        val pct = (zoneSecs[zi].toDouble() / total * 100).toInt()
                        Text("$pct%", color = MV.OnSurfaceDim, fontSize = 11.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun ZoneBar(zoneSecs: LongArray) {
    val total = zoneSecs.sum().coerceAtLeast(1)
    Row(Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(3.dp))) {
        for (zi in 0 until 5) {
            val frac = (zoneSecs[zi].toFloat() / total)
            if (frac > 0f) {
                Box(Modifier.weight(frac).fillMaxSize()
                    .background(ZONE_COLORS[zi]))
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun fmtMins(s: Long): String {
    val m = s / 60
    return if (m >= 60) "${m / 60}h ${m % 60}m" else "${m}m"
}
