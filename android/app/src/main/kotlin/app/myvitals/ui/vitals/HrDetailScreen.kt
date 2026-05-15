package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.TimePoint
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate

private val ZONE_COLORS = listOf(
    Color(0xFF38BDF8), Color(0xFF22C55E), Color(0xFFEAB308),
    Color(0xFFF97316), Color(0xFFEF4444),
)

/** A workout / activity that overlapped with the chart window. Drawn
 *  as a translucent vertical band so the user can correlate HR spikes
 *  with what they were doing. */
data class HrEventBand(
    val startMs: Long,
    val endMs: Long,
    val label: String,
    val color: Color,
)

@Composable
fun HrDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    var range by remember { mutableStateOf(VitalRange.DAY) }
    var live by remember { mutableStateOf<List<TimePoint>>(emptyList()) }
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var bands by remember { mutableStateOf<List<HrEventBand>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var maxHr by remember { mutableStateOf(190) }

    LaunchedEffect(range) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
        loading = true; error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            // Profile drives zone thresholds. Re-fetch on every load so a
            // birth-date update flows through to the chart immediately.
            runCatching { api.profile() }.getOrNull()?.let { maxHr = it.maxHr() }
            coroutineScope {
                if (range == VitalRange.DAY) {
                    val liveD = async(Dispatchers.IO) {
                        api.heartRateSeries(
                            since = Instant.now().minusSeconds(86_400).toString(),
                        )
                    }
                    val activitiesD = async(Dispatchers.IO) {
                        runCatching { api.activities(limit = 30) }.getOrDefault(emptyList())
                    }
                    val workoutsD = async(Dispatchers.IO) {
                        runCatching {
                            api.strengthWorkouts().workouts.filter { it.startedAt != null }
                        }.getOrDefault(emptyList())
                    }
                    val wearD = async(Dispatchers.IO) {
                        runCatching {
                            api.deviceStatusSeries(
                                since = Instant.now().minusSeconds(86_400).toString(),
                            )
                        }.getOrNull()
                    }
                    live = liveD.await().points

                    // Build event bands for the 24h window.
                    val windowStart = Instant.now().minusSeconds(86_400).toEpochMilli()
                    val windowEnd = Instant.now().toEpochMilli()
                    val list = mutableListOf<HrEventBand>()
                    // Off-wrist bands (WATCH-2): consecutive samples where is_worn
                    // is false get a single grey band so the user reads gaps in HR
                    // as "watch was off" rather than a missing-data anomaly. Runs
                    // shorter than 60s are filtered out — those are typically
                    // accelerometer flutter at the wear-detection threshold.
                    wearD.await()?.let { wear ->
                        val pts = wear.points.mapNotNull { p ->
                            val t = runCatching { Instant.parse(p.time).toEpochMilli() }
                                .getOrNull() ?: return@mapNotNull null
                            t to p.isWorn
                        }.sortedBy { it.first }
                        var runStart: Long? = null
                        for (pair in pts) {
                            val (t, worn) = pair
                            if (worn == false) {
                                if (runStart == null) runStart = t
                            } else if (runStart != null) {
                                if (t - runStart >= 60_000L) {
                                    list += HrEventBand(runStart, t,
                                        label = "off wrist",
                                        color = Color(0x4894A3B8))
                                }
                                runStart = null
                            }
                        }
                        // Close any still-open run at the last sample's timestamp.
                        if (runStart != null && pts.isNotEmpty()) {
                            val last = pts.last().first
                            if (last - runStart >= 60_000L) {
                                list += HrEventBand(runStart, last,
                                    label = "off wrist",
                                    color = Color(0x4894A3B8))
                            }
                        }
                    }
                    for (a in activitiesD.await()) {
                        val s = runCatching { Instant.parse(a.startAt).toEpochMilli() }
                            .getOrNull() ?: continue
                        val e = s + a.durationS * 1000L
                        if (e < windowStart || s > windowEnd) continue
                        list += HrEventBand(s, e,
                            label = a.name?.take(24) ?: a.type,
                            // Strava-orange-ish for activities
                            color = Color(0xFFF97316))
                    }
                    for (w in workoutsD.await()) {
                        val s = runCatching { Instant.parse(w.startedAt!!).toEpochMilli() }
                            .getOrNull() ?: continue
                        val e = w.completedAt?.let {
                            runCatching { Instant.parse(it).toEpochMilli() }.getOrNull()
                        } ?: (s + 60 * 60_000L)  // assume 1h if not yet finished
                        if (e < windowStart || s > windowEnd) continue
                        list += HrEventBand(s, e,
                            label = "${w.splitFocus} workout",
                            color = Vital.WORKOUT.color)
                    }
                    bands = list
                    rows = emptyList()
                } else {
                    val since = LocalDate.now().minusDays(range.days.toLong() - 1).toString()
                    rows = withContext(Dispatchers.IO) { api.summaryRange(since = since) }
                    live = emptyList()
                }
            }
            Timber.i("HR detail: range=%s live=%d rows=%d", range, live.size, rows.size)
        } catch (e: Exception) {
            Timber.w(e, "HR detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Icon(Vital.HR.icon, contentDescription = null, tint = Vital.HR.color,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Heart rate", color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            VitalRange.entries.forEach { r ->
                FilterChip(
                    selected = r == range,
                    onClick = { range = r },
                    label = { Text(r.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = Vital.HR.color.copy(alpha = 0.20f),
                        selectedLabelColor = MV.OnSurface,
                    ),
                )
            }
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red, modifier = Modifier.padding(16.dp))
            else -> LazyColumn(
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (range == VitalRange.DAY) {
                    item { LiveHrChart(live, maxHr, bands) }
                    item { TimeInZone(live, maxHr) }
                    item { HrHistogram(live) }
                } else {
                    item { RestingHrTrend(rows, range) }
                    item { WeekdayPattern(rows) }
                }
            }
        }
    }
}

@Composable
private fun LiveHrChart(
    points: List<TimePoint>,
    maxHr: Int,
    bands: List<HrEventBand> = emptyList(),
) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LAST 24H", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (points.size < 2) {
                Text("No HR samples in the last 24h.",
                    color = MV.OnSurfaceVariant, fontSize = 12.sp); return@Card
            }
            val parsed = remember(points) {
                points.mapNotNull { p ->
                    val t = runCatching { Instant.parse(p.time).toEpochMilli() }
                        .getOrNull() ?: return@mapNotNull null
                    t to p.value
                }.sortedBy { it.first }.distinctBy { it.first }
            }
            // Downsample for perf
            val sampled = remember(parsed) {
                if (parsed.size <= 600) parsed
                else {
                    val stride = parsed.size.toDouble() / 600
                    (0 until 600).map {
                        parsed[(it * stride).toInt().coerceAtMost(parsed.lastIndex)]
                    }
                }
            }
            val minV = sampled.minOf { it.second }
            val maxV = sampled.maxOf { it.second }
            val avgV = sampled.map { it.second }.average()
            Box(Modifier.fillMaxWidth().height(220.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val padX = 32.dp.toPx()
                    val padTop = 8.dp.toPx()
                    val padBot = 16.dp.toPx()
                    val plotW = size.width - padX
                    val plotH = size.height - padTop - padBot
                    val tStart = sampled.first().first
                    val tEnd = sampled.last().first
                    val tSpan = (tEnd - tStart).toFloat().coerceAtLeast(1f)
                    val yMin = (minV - 8).coerceAtLeast(40.0).toFloat()
                    val yMax = (maxV + 8).coerceAtMost(220.0).toFloat()
                    val ySpan = (yMax - yMin).coerceAtLeast(1f)
                    // Zone background bands
                    val edges = listOf(0.50, 0.60, 0.70, 0.80, 0.90, 1.10)
                    for (zi in 0..4) {
                        val lo = (maxHr * edges[zi]).toFloat()
                        val hi = (maxHr * edges[zi + 1]).toFloat()
                        if (hi < yMin || lo > yMax) continue
                        val y0 = padTop + ((yMax - hi.coerceAtMost(yMax)) / ySpan) * plotH
                        val y1 = padTop + ((yMax - lo.coerceAtLeast(yMin)) / ySpan) * plotH
                        drawRect(
                            color = ZONE_COLORS[zi].copy(alpha = 0.08f),
                            topLeft = Offset(padX, y0),
                            size = Size(plotW, (y1 - y0).coerceAtLeast(0f)),
                        )
                    }
                    // Workout / activity bands — vertical regions over the
                    // full chart height.
                    for (b in bands) {
                        val s = b.startMs.coerceAtLeast(tStart)
                        val e = b.endMs.coerceAtMost(tEnd)
                        if (e <= s) continue
                        val x0 = padX + ((s - tStart).toFloat() / tSpan) * plotW
                        val x1 = padX + ((e - tStart).toFloat() / tSpan) * plotW
                        drawRect(
                            color = b.color.copy(alpha = 0.18f),
                            topLeft = Offset(x0, padTop),
                            size = Size((x1 - x0).coerceAtLeast(1f), plotH),
                        )
                        // Left edge stripe for emphasis
                        drawLine(
                            color = b.color.copy(alpha = 0.6f),
                            start = Offset(x0, padTop),
                            end = Offset(x0, padTop + plotH),
                            strokeWidth = 1.5.dp.toPx(),
                        )
                    }
                    // Gridlines for easier reading
                    val ticks = listOf(yMin, (yMin + yMax) / 2f, yMax)
                    for (yv in ticks) {
                        val py = padTop + ((yMax - yv) / ySpan) * plotH
                        drawLine(
                            color = MV.OnSurfaceDim.copy(alpha = 0.15f),
                            start = Offset(padX, py), end = Offset(size.width, py),
                            strokeWidth = 0.7.dp.toPx(),
                        )
                    }
                    // Per-segment colored line (skip if gap > 5 min)
                    for (i in 0 until sampled.size - 1) {
                        val (t0, v0) = sampled[i]
                        val (t1, v1) = sampled[i + 1]
                        if (t1 - t0 > 5 * 60_000L) continue
                        val mean = (v0 + v1) * 0.5
                        val zi = zoneIdx(mean, maxHr)
                        val x0 = padX + ((t0 - tStart).toFloat() / tSpan) * plotW
                        val x1 = padX + ((t1 - tStart).toFloat() / tSpan) * plotW
                        val y0 = padTop + ((yMax - v0.toFloat()) / ySpan) * plotH
                        val y1 = padTop + ((yMax - v1.toFloat()) / ySpan) * plotH
                        drawLine(
                            color = ZONE_COLORS[zi],
                            start = Offset(x0, y0), end = Offset(x1, y1),
                            strokeWidth = 2.dp.toPx(),
                        )
                    }
                    // Avg dashed
                    val avgY = padTop + ((yMax - avgV.toFloat()) / ySpan) * plotH
                    drawLine(
                        color = MV.OnSurfaceVariant.copy(alpha = 0.55f),
                        start = Offset(padX, avgY), end = Offset(size.width, avgY),
                        strokeWidth = 1.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(
                            floatArrayOf(4.dp.toPx(), 3.dp.toPx())
                        ),
                    )
                }
                // Y-axis label column
                Column(Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.SpaceBetween) {
                    Text("${(maxV + 8).toInt()}",
                        color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("${((minV + maxV) / 2).toInt()}",
                        color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("${(minV - 8).coerceAtLeast(40.0).toInt()}",
                        color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp, bottom = 12.dp))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Min", "${minV.toInt()} bpm")
                Stat("Avg", "%.0f bpm".format(avgV))
                Stat("Max", "${maxV.toInt()} bpm")
                Stat("Samples", "${points.size}")
            }
        }
    }
}

@Composable
private fun TimeInZone(points: List<TimePoint>, maxHr: Int) {
    val zoneSecs = remember(points, maxHr) {
        val out = LongArray(5)
        val parsed = points.mapNotNull { p ->
            runCatching { Instant.parse(p.time).toEpochMilli() }.getOrNull()?.let { it to p.value }
        }.sortedBy { it.first }
        for (i in 0 until parsed.size - 1) {
            val gap = parsed[i + 1].first - parsed[i].first
            if (gap > 5 * 60_000L) continue
            out[zoneIdx(parsed[i].second, maxHr)] += gap / 1000L
        }
        out
    }
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TIME IN ZONE — 24H", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
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
            Spacer(Modifier.height(8.dp))
            for (zi in 0 until 5) {
                val pct = (zoneSecs[zi].toDouble() / total * 100).toInt()
                Row(verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(vertical = 1.dp)) {
                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp))
                        .background(ZONE_COLORS[zi]))
                    Spacer(Modifier.width(6.dp))
                    Text(zoneLabel(zi), color = MV.OnSurface, fontSize = 11.sp,
                        modifier = Modifier.weight(1f))
                    Text(fmtSec(zoneSecs[zi]), color = MV.OnSurfaceVariant, fontSize = 11.sp,
                        modifier = Modifier.width(72.dp))
                    Text("$pct%", color = MV.OnSurfaceDim, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
private fun RestingHrTrend(rows: List<DailySummary>, range: VitalRange) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("RESTING HR — ${range.label.uppercase()}",
                color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val pts = rows.map { it.restingHr?.toFloat() }
            val real = pts.filterNotNull()
            if (real.size < 2) {
                Text("No resting HR data in this window.",
                    color = MV.OnSurfaceVariant, fontSize = 12.sp); return@Card
            }
            Row(verticalAlignment = Alignment.Bottom) {
                Text("%.0f".format(real.last()), color = MV.OnSurface,
                    fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(4.dp))
                Text("bpm", color = MV.OnSurfaceDim, fontSize = 11.sp,
                    modifier = Modifier.padding(bottom = 4.dp))
            }
            Spacer(Modifier.height(6.dp))
            Box(Modifier.fillMaxWidth().height(140.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val padTop = 4.dp.toPx()
                    val padBot = 4.dp.toPx()
                    val plotH = size.height - padTop - padBot
                    val minY = real.min()
                    val maxY = real.max()
                    val span = (maxY - minY).coerceAtLeast(1f)
                    val stepX = size.width / (pts.size - 1)
                    val path = androidx.compose.ui.graphics.Path()
                    var started = false
                    for ((i, v) in pts.withIndex()) {
                        if (v == null) { started = false; continue }
                        val x = i * stepX
                        val py = padTop + ((maxY - v) / span) * plotH
                        if (!started) { path.moveTo(x, py); started = true }
                        else path.lineTo(x, py)
                        drawCircle(color = Vital.HR.color, radius = 1.5.dp.toPx(),
                            center = Offset(x, py))
                    }
                    drawPath(path = path, color = Vital.HR.color,
                        style = Stroke(width = 2.dp.toPx()))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Min", "${real.min().toInt()} bpm")
                Stat("Avg", "%.0f bpm".format(real.average()))
                Stat("Max", "${real.max().toInt()} bpm")
            }
        }
    }
}

private fun zoneIdx(bpm: Double, maxHr: Int): Int {
    val pct = bpm / maxHr
    return when {
        pct < 0.60 -> 0; pct < 0.70 -> 1; pct < 0.80 -> 2
        pct < 0.90 -> 3; else -> 4
    }
}

private fun zoneLabel(z: Int): String = when (z) {
    0 -> "Z1 — recovery"
    1 -> "Z2 — endurance"
    2 -> "Z3 — tempo"
    3 -> "Z4 — threshold"
    else -> "Z5 — VO2"
}

private fun fmtSec(s: Long): String {
    val m = s / 60
    return if (m >= 60) "${m / 60}h ${m % 60}m" else "${m}m"
}

@Composable
private fun Stat(label: String, value: String) {
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun HrHistogram(points: List<TimePoint>) {
    if (points.isEmpty()) return
    // 5-bpm bins so the chart isn't too jagged. The lo/hi range is
    // derived from the data itself rather than fixed (40-200 bpm) so
    // a tight resting cluster still gets meaningful bar height.
    val bins = remember(points) {
        val bin = 5
        val byBin = HashMap<Int, Int>()
        var lo = Int.MAX_VALUE; var hi = Int.MIN_VALUE
        for (p in points) {
            val b = (p.value / bin).toInt() * bin
            byBin[b] = (byBin[b] ?: 0) + 1
            if (b < lo) lo = b
            if (b > hi) hi = b
        }
        if (lo == Int.MAX_VALUE) emptyList()
        else (lo..hi step bin).map { it to (byBin[it] ?: 0) }
    }
    if (bins.isEmpty()) return
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("HR DISTRIBUTION — 24H", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(2.dp))
            Text("5-bpm bins · ${points.size} samples",
                color = MV.OnSurfaceDim, fontSize = 10.sp)
            Spacer(Modifier.height(8.dp))
            val maxCount = (bins.maxOfOrNull { it.second } ?: 1).coerceAtLeast(1)
            Box(Modifier.fillMaxWidth().height(120.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val gapPx = 2f
                    val barW = (size.width - gapPx * (bins.size - 1)) / bins.size
                    bins.forEachIndexed { i, (_, c) ->
                        val h = (c.toFloat() / maxCount) * size.height
                        val x = i * (barW + gapPx)
                        drawRect(
                            color = Vital.HR.color,
                            topLeft = androidx.compose.ui.geometry.Offset(x, size.height - h),
                            size = androidx.compose.ui.geometry.Size(barW, h),
                        )
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${bins.first().first}", color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text("${bins.last().first + 5}", color = MV.OnSurfaceDim, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun WeekdayPattern(rows: List<DailySummary>) {
    if (rows.isEmpty()) return
    val byDow = remember(rows) {
        val sums = DoubleArray(7)
        val cnts = IntArray(7)
        val cal = java.util.Calendar.getInstance()
        for (r in rows) {
            val v = r.restingHr ?: continue
            val d = runCatching {
                java.time.LocalDate.parse(r.date).atStartOfDay(java.time.ZoneId.systemDefault())
                    .toInstant().toEpochMilli()
            }.getOrNull() ?: continue
            cal.timeInMillis = d
            // Calendar.SUNDAY = 1 → index 0
            val dow = (cal.get(java.util.Calendar.DAY_OF_WEEK) - 1).coerceIn(0, 6)
            sums[dow] += v
            cnts[dow] += 1
        }
        (0..6).map { i -> if (cnts[i] > 0) sums[i] / cnts[i] else null }
    }
    if (byDow.all { it == null }) return
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("RESTING HR · BY WEEKDAY", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val nonNull = byDow.filterNotNull()
            val lo = nonNull.min()
            val hi = nonNull.max()
            val span = (hi - lo).coerceAtLeast(1.0)
            val labels = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
            Row(Modifier.fillMaxWidth().height(110.dp),
                verticalAlignment = Alignment.Bottom,
                horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                byDow.forEachIndexed { i, v ->
                    Column(Modifier.weight(1f),
                        horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(if (v != null) "${v.toInt()}" else "—",
                            color = MV.OnSurface, fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold)
                        Spacer(Modifier.height(2.dp))
                        val frac = if (v != null) ((v - lo) / span).toFloat() else 0f
                        // Always render at least a sliver so a value isn't invisible
                        val height = (16f + frac * 70f).dp
                        Box(Modifier.fillMaxWidth().height(height)
                            .clip(RoundedCornerShape(3.dp))
                            .background(Vital.HR.color.copy(alpha = if (v == null) 0.15f else 0.85f)))
                        Spacer(Modifier.height(2.dp))
                        Text(labels[i], color = MV.OnSurfaceDim, fontSize = 10.sp)
                    }
                }
            }
        }
    }
}
