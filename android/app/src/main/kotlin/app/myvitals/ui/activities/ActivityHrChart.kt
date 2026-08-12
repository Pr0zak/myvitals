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
import app.myvitals.ui.vitals.ChartInsets
import app.myvitals.ui.vitals.chartGeom
import app.myvitals.ui.vitals.drawGapBridge
import app.myvitals.ui.vitals.drawGrid
import app.myvitals.ui.vitals.drawReferenceLine
import app.myvitals.ui.vitals.drawXLabels
import app.myvitals.ui.vitals.niceDomain
import app.myvitals.ui.LocalAppTokens
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

/** A gap longer than this is a dropout, not a reading. */
private const val DROPOUT_MS = 60_000L

private fun z0(bpm: Double, maxHr: Int): Int = zoneFor(bpm, maxHr)

/** "12:34" elapsed. */
private fun fmtElapsed(secs: Long): String {
    val m = secs / 60
    return if (m >= 60) "%d:%02d".format(m / 60, m % 60) else "%d min".format(m)
}

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
    // This chart hard-coded the classic MV.* palette while its host screen and
    // the shell around it are theme-aware, so it rendered as a navy card in a
    // neon app.
    val tok = LocalAppTokens.current
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("HEART RATE", color = tok.onSurfaceVariant,
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
                    // Don't charge a recording gap to a zone.
                    if (t1 - t0 > DROPOUT_MS) continue
                    out[z0(v, maxHr)] += (t1 - t0) / 1000L
                }
                out
            }

            Canvas(Modifier.fillMaxWidth().height(190.dp)) {
                val domain = niceDomain(
                    lo = minBpm.toFloat(), hi = maxBpm.toFloat(),
                    targetTicks = 3, minStep = 1f,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 30.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                val tStart = sampled.first().first
                val tEnd = sampled.last().first
                val tSpan = (tEnd - tStart).toFloat().coerceAtLeast(1f)

                // Zone bands. The edge list used to start at 0.50 x maxHr while
                // zoneFor() puts everything below 0.60 in Z1 — so an easy ride
                // spent below 50% sat on unpainted background while the chart's
                // own colouring called it Z1. Bands now follow the same
                // thresholds the line colouring uses.
                val zoneEdges = listOf(0.0, 0.60, 0.70, 0.80, 0.90, 10.0)
                for (zi in 0..4) {
                    val lo = (maxHr * zoneEdges[zi]).toFloat()
                    val hi = (maxHr * zoneEdges[zi + 1]).toFloat()
                    if (hi < domain.min || lo > domain.max) continue
                    val y0 = g.y(hi); val y1 = g.y(lo)
                    drawRect(
                        color = ZONE_COLORS[zi].copy(alpha = 0.07f),
                        topLeft = Offset(g.left, y0),
                        size = Size(g.width, (y1 - y0).coerceAtLeast(0f)),
                    )
                }

                // Labels used to be a SpaceBetween Column laid over the canvas
                // with a stray zero-height Spacer as a fourth child, so free
                // space split into three gaps and the middle number sat ~20dp
                // below the gridline it named. It also read (min+max)/2 while
                // the gridline was at the padded midpoint — two different
                // numbers. One geometry now.
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 3) {
                    "%.0f".format(it)
                }

                // Per-segment coloured line — zone of the segment's mean.
                for (i in 0 until sampled.size - 1) {
                    val (t0, v0) = sampled[i]
                    val (t1, v1) = sampled[i + 1]
                    val x0 = g.left + ((t0 - tStart).toFloat() / tSpan) * g.width
                    val x1 = g.left + ((t1 - tStart).toFloat() / tSpan) * g.width
                    val y0 = g.y(v0.toFloat()); val y1 = g.y(v1.toFloat())
                    // A gap in the recording is not a heart rate. Bridging it
                    // with a solid coloured segment invented a reading AND
                    // charged the missing minutes to whichever zone the
                    // interpolation happened to cross.
                    if (t1 - t0 > DROPOUT_MS) {
                        drawGapBridge(Offset(x0, y0), Offset(x1, y1), tok.onSurfaceDim)
                        continue
                    }
                    drawLine(
                        color = ZONE_COLORS[zoneFor((v0 + v1) * 0.5, maxHr)],
                        start = Offset(x0, y0), end = Offset(x1, y1),
                        strokeWidth = 2.dp.toPx(),
                    )
                }

                drawReferenceLine(g, avgBpm.toFloat(), tok.onSurfaceVariant,
                    measurer, "avg ${avgBpm.toInt()}")
                drawXLabels(g, measurer, tok.onSurfaceDim, listOf(
                    0f to "0:00",
                    1f to fmtElapsed((tEnd - tStart) / 1000L),
                ))
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
