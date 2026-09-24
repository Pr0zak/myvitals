package app.myvitals.ui.activities

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ActivityZones
import app.myvitals.sync.TimePoint
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumberFamily
import app.myvitals.ui.vitals.ChartInsets
import app.myvitals.ui.vitals.chartGeom
import app.myvitals.ui.vitals.drawGapBridge
import app.myvitals.ui.vitals.drawGrid
import app.myvitals.ui.vitals.drawReferenceLine
import app.myvitals.ui.vitals.drawXLabels
import app.myvitals.ui.vitals.niceDomain
import java.time.Instant

/*
 * Heart rate during an activity (UI-5).
 *
 * Zones used to be computed HERE, from a hard-coded 60/70/80/90% of a
 * profile max, while the zones card beside it showed the server's
 * boundaries — so the chart's bands and the card's table could name
 * different zones for the same beat. The chart also summed its own
 * "time in zone" from samples. Now every boundary is the server's
 * `zones[].loBpm/hiBpm`; the phone only decides colour. The totals
 * live in [HrZonesSummary], which renders the server's seconds and percent.
 */

/** Z1..Z5, cool to hot — NeonMV tokens, matching the web palette. */
val ZONE_COLORS: List<Color> = listOf(
    NeonMV.Periwinkle, NeonMV.Cyan, NeonMV.Lime, NeonMV.Amber, NeonMV.Bad,
)

internal fun zoneColor(i: Int): Color = ZONE_COLORS.getOrElse(i) { ZONE_COLORS.last() }

/** A gap longer than this is a dropout, not a reading. */
private const val DROPOUT_MS = 60_000L

/** 0-based zone index for [bpm] against the server's boundaries (colour only). */
internal fun zoneIndexFor(bpm: Double, zones: ActivityZones?): Int {
    val z = zones?.zones ?: return -1
    for (i in z.indices.reversed()) if (bpm >= z[i].loBpm) return i
    return 0
}

private fun fmtElapsed(secs: Long): String {
    val m = secs / 60
    return if (m >= 60) "%d:%02d".format(m / 60, m % 60) else "%d min".format(m)
}

@Composable
fun ActivityHrChart(
    points: List<TimePoint>,
    zones: ActivityZones?,
    avgHr: Double?,
) {
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    Column(
        Modifier.fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(14.dp),
    ) {
        NeonEyebrow("Heart rate", Modifier.padding(top = 0.dp))
        val parsed = remember(points) {
            points.mapNotNull { p ->
                val t = runCatching { Instant.parse(p.time).toEpochMilli() }.getOrNull()
                    ?: return@mapNotNull null
                t to p.value
            }.sortedBy { it.first }.distinctBy { it.first }
        }
        if (parsed.size < 2) {
            Text("Not enough heart-rate samples for this activity.",
                color = NeonMV.Muted, fontSize = 12.sp)
            return@Column
        }
        // Downsample for perf — a 2k+ series is not worth pixel detail.
        val sampled = remember(parsed) {
            val cap = 600
            if (parsed.size <= cap) parsed
            else {
                val stride = parsed.size.toDouble() / cap
                (0 until cap).map { i -> parsed[(i * stride).toInt().coerceAtMost(parsed.lastIndex)] }
            }
        }
        val lo = sampled.minOf { it.second }
        val hi = sampled.maxOf { it.second }
        Canvas(Modifier.fillMaxWidth().height(190.dp)) {
            val domain = niceDomain(lo = lo.toFloat(), hi = hi.toFloat(), targetTicks = 3, minStep = 1f)
            val g = chartGeom(domain, ChartInsets(
                left = 30.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
            ))
            val tStart = sampled.first().first
            val tEnd = sampled.last().first
            val tSpan = (tEnd - tStart).toFloat().coerceAtLeast(1f)

            // Zone bands from the SERVER's boundaries, shaded behind the line.
            zones?.zones?.forEachIndexed { i, z ->
                val bLo = z.loBpm.toFloat()
                val bHi = (z.hiBpm ?: 300).toFloat()
                if (bHi < domain.min || bLo > domain.max) return@forEachIndexed
                val y0 = g.y(bHi); val y1 = g.y(bLo)
                drawRect(zoneColor(i).copy(alpha = 0.10f), Offset(g.left, y0),
                    Size(g.width, (y1 - y0).coerceAtLeast(0f)))
            }
            drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { "%.0f".format(it) }
            for (i in 0 until sampled.size - 1) {
                val (t0, v0) = sampled[i]
                val (t1, v1) = sampled[i + 1]
                val x0 = g.left + ((t0 - tStart).toFloat() / tSpan) * g.width
                val x1 = g.left + ((t1 - tStart).toFloat() / tSpan) * g.width
                val p0 = Offset(x0, g.y(v0.toFloat())); val p1 = Offset(x1, g.y(v1.toFloat()))
                // A gap in the recording is not a heart rate.
                if (t1 - t0 > DROPOUT_MS) { drawGapBridge(p0, p1, NeonMV.Muted); continue }
                val zi = zoneIndexFor((v0 + v1) * 0.5, zones)
                drawLine(if (zi < 0) NeonMV.Cyan else zoneColor(zi), p0, p1, strokeWidth = 2.dp.toPx())
            }
            avgHr?.let {
                drawReferenceLine(g, it.toFloat(), NeonMV.Ink, measurer, "avg ${it.toInt()}")
            }
            drawXLabels(g, measurer, NeonMV.Muted, listOf(
                0f to "0:00", 1f to fmtElapsed((tEnd - tStart) / 1000L),
            ))
        }
    }
}

/**
 * Time in zone as ONE stacked bar plus a legend — every number (seconds,
 * percent, the bpm boundaries) straight from GET /activities/…/zones.
 */
@Composable
fun HrZonesSummary(z: ActivityZones) {
    Column(
        Modifier.fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(14.dp),
    ) {
        NeonEyebrow("Time in zone", Modifier.padding(top = 0.dp))
        Row(Modifier.fillMaxWidth().height(14.dp).clip(RoundedCornerShape(7.dp))
            .background(NeonMV.Track)) {
            z.zones.forEachIndexed { i, zone ->
                val f = (zone.pct / 100.0).toFloat()
                if (f > 0f) Box(Modifier.weight(f).fillMaxHeight().background(zoneColor(i)))
            }
            val rest = (1f - z.zones.sumOf { it.pct }.toFloat() / 100f)
            if (rest > 0.001f) Spacer(Modifier.weight(rest))
        }
        Spacer(Modifier.height(10.dp))
        z.zones.forEachIndexed { i, zone ->
            val range = zone.hiBpm?.let { "${zone.loBpm}–$it" } ?: "${zone.loBpm}+"
            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).clip(RoundedCornerShape(3.dp)).background(zoneColor(i)))
                Spacer(Modifier.width(8.dp))
                Text("${zone.zone} ${zone.label}", color = NeonMV.Ink, fontSize = 13.sp,
                    modifier = Modifier.weight(1f))
                Text("$range bpm", color = NeonMV.Muted, fontSize = 11.sp,
                    fontFamily = NeonNumberFamily, modifier = Modifier.width(76.dp))
                Text(fmtDurationHm(zone.seconds), color = NeonMV.Ink, fontSize = 12.sp,
                    fontFamily = NeonNumberFamily, textAlign = TextAlign.End,
                    modifier = Modifier.width(56.dp))
                Text("%.0f%%".format(zone.pct), color = NeonMV.Muted, fontSize = 12.sp,
                    fontFamily = NeonNumberFamily, textAlign = TextAlign.End,
                    fontWeight = FontWeight.Bold, modifier = Modifier.width(42.dp))
            }
        }
        if (!z.sampled) {
            Spacer(Modifier.height(6.dp))
            Text(
                "No heart-rate series was recorded, so the whole session is attributed " +
                    "to the zone its average falls in. Treat the split as coarse.",
                color = NeonMV.Muted, fontSize = 11.sp,
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(
            when (z.maxHrSource) {
                "profile" -> "Zones from your max HR of ${z.maxHr} bpm."
                "estimated" -> "Zones from an estimated max HR of ${z.maxHr} bpm " +
                    "(Tanaka, age ${z.ageUsed}). Set a measured max in Settings → Profile."
                else -> "Zones from a default max HR of ${z.maxHr} bpm — no birth date or " +
                    "measured max on file, so these boundaries are a guess."
            },
            color = NeonMV.Muted, fontSize = 11.sp,
        )
    }
}
