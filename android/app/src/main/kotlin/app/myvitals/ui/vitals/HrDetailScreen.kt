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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.HrZoneStats
import app.myvitals.sync.RangeStats
import app.myvitals.sync.RestingHrRangeStats
import app.myvitals.sync.TimeSeries
import app.myvitals.sync.VitalTile
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Z1..Z5 — Periwinkle → Cyan → Lime → Amber → Bad. Bad only for Z5, which
 *  is a genuine top-intensity band, not a warning about the user. */
internal val HR_ZONE_COLORS = listOf(
    NeonMV.Periwinkle, NeonMV.Cyan, NeonMV.Lime, NeonMV.Amber, NeonMV.Bad,
)

/** A workout / activity that overlapped the chart window, drawn as a
 *  translucent vertical band so HR spikes line up with what caused them. */
data class HrEventBand(
    val startMs: Long,
    val endMs: Long,
    val label: String,
    val color: Color,
)

/** A journal entry on the trace (LOG-4): an emoji at its minute. */
data class HrMarker(val ms: Long, val glyph: String)

/**
 * Heart rate detail (UI-4). DAY: the hero is the day's trace over the
 * server's zone bands; below it the server's time-in-zone and band
 * histogram. 7d/30d/90d: the hero is resting HR over the window with the
 * normal band and baseline from /summary/tiles; below it the server's
 * weekday means. Every figure is rendered verbatim from the server — zones
 * come from analytics/cardio.py, the same bounds the Activities screen uses.
 */
@Composable
fun HrDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var range by remember { mutableStateOf(VitalRange.DAY) }
    var selectedDay by remember { mutableStateOf(LocalDate.now()) }
    var live by remember { mutableStateOf<TimeSeries?>(null) }
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var rangeStats by remember { mutableStateOf<RestingHrRangeStats?>(null) }
    // Which range `rows` belong to, so a tab switch never draws the old
    // range's series under the new title.
    var rowsRange by remember { mutableStateOf<VitalRange?>(null) }
    var restingTile by remember { mutableStateOf<VitalTile?>(null) }
    var bands by remember { mutableStateOf<List<HrEventBand>>(emptyList()) }
    var markers by remember { mutableStateOf<List<HrMarker>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val rowsType = com.squareup.moshi.Types.newParameterizedType(
        List::class.java, DailySummary::class.java,
    )

    suspend fun fetch() {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val tileD = async(Dispatchers.IO) {
                    runCatching { api.summaryTiles().tiles.firstOrNull { it.key == "resting_hr" } }
                        .getOrNull()
                }
                if (range == VitalRange.DAY) {
                    val zone = ZoneId.systemDefault()
                    val isToday = selectedDay == LocalDate.now()
                    val dayStart = selectedDay.atStartOfDay(zone).toInstant()
                    val dayEnd = if (isToday) Instant.now()
                        else selectedDay.plusDays(1).atStartOfDay(zone).toInstant()
                    val sinceIso = dayStart.toString()
                    val untilIso = dayEnd.toString()
                    val liveD = async(Dispatchers.IO) {
                        // 2-minute buckets: ~720 points a day instead of ~5k.
                        api.heartRateSeries(since = sinceIso, until = untilIso, bucketSeconds = 120)
                    }
                    val activitiesD = async(Dispatchers.IO) {
                        runCatching { api.activities(limit = 30) }.getOrDefault(emptyList())
                    }
                    val workoutsD = async(Dispatchers.IO) {
                        runCatching { api.strengthWorkouts().workouts.filter { it.startedAt != null } }
                            .getOrDefault(emptyList())
                    }
                    val annoD = async(Dispatchers.IO) {
                        runCatching { api.journalList(since = sinceIso, until = untilIso, limit = 50) }
                            .getOrDefault(emptyList())
                    }
                    live = liveD.await()
                    val ws = dayStart.toEpochMilli()
                    val we = dayEnd.toEpochMilli()
                    val list = mutableListOf<HrEventBand>()
                    for (a in activitiesD.await()) {
                        val s = runCatching { Instant.parse(a.startAt).toEpochMilli() }.getOrNull() ?: continue
                        val e = s + a.durationS * 1000L
                        if (e < ws || s > we) continue
                        list += HrEventBand(s, e, a.name?.take(24) ?: a.type, NeonMV.Amber)
                    }
                    for (w in workoutsD.await()) {
                        val s = runCatching { Instant.parse(w.startedAt!!).toEpochMilli() }.getOrNull() ?: continue
                        val e = w.completedAt?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }
                            ?: (s + 60 * 60_000L)
                        if (e < ws || s > we) continue
                        list += HrEventBand(s, e, "${w.splitFocus} workout", NeonMV.Magenta)
                    }
                    bands = list
                    markers = annoD.await().mapNotNull { a ->
                        runCatching { Instant.parse(a.ts).toEpochMilli() }.getOrNull()
                            ?.let { HrMarker(it, annotationEmoji(a.type)) }
                    }
                } else {
                    val today = LocalDate.now()
                    val since = today.minusDays(range.days.toLong() - 1).toString()
                    val rowsD = async(Dispatchers.IO) { api.summaryRange(since = since) }
                    val statsD = async(Dispatchers.IO) {
                        runCatching { api.summaryRangeStats(since = since, until = today.toString()) }
                            .getOrNull()
                    }
                    rows = rowsD.await()
                    rowsRange = range
                    JsonCache.write(context, "hr_detail_rows_${range.name.lowercase()}", rowsType, rows)
                    statsD.await()?.let {
                        rangeStats = it.restingHr
                        JsonCache.write(context, "hr_detail_stats_${range.name.lowercase()}",
                            RangeStats::class.java, it)
                    }
                }
                restingTile = tileD.await()
            }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "HR detail load failed")
            error = e.message?.take(160) ?: "Couldn't reach the backend."
        } finally { loading = false }
    }

    LaunchedEffect(range, selectedDay) {
        if (rowsRange != null && rowsRange != range) {
            rows = emptyList(); rowsRange = null; rangeStats = null
        }
        if (range != VitalRange.DAY) {
            val key = range.name.lowercase()
            JsonCache.read<List<DailySummary>>(context, "hr_detail_rows_$key", rowsType)
                ?.let { rows = it.value; rowsRange = range; loading = false }
            JsonCache.read<RangeStats>(context, "hr_detail_stats_$key", RangeStats::class.java)
                ?.let { rangeStats = it.value.restingHr }
        } else {
            live = null
            loading = true
        }
        fetch()
    }

    HrDetailContent(
        range = range, live = live, rows = if (rowsRange == range) rows else emptyList(),
        rangeStats = rangeStats, restingTile = restingTile, bands = bands, markers = markers,
        selectedDay = selectedDay, today = LocalDate.now(), nowMs = System.currentTimeMillis(),
        loading = loading, refreshing = refreshing, error = error,
        onBack = onBack,
        onRange = { r -> range = r; if (r != VitalRange.DAY) selectedDay = LocalDate.now() },
        onRefresh = { scope.launch { refreshing = true; try { fetch() } finally { refreshing = false } } },
        dayNav = {
            app.myvitals.ui.common.DayNav(selected = selectedDay, onSelectedChange = { selectedDay = it })
        },
    )
}

@Composable
fun HrDetailContent(
    range: VitalRange,
    live: TimeSeries?,
    rows: List<DailySummary>,
    rangeStats: RestingHrRangeStats?,
    restingTile: VitalTile?,
    bands: List<HrEventBand>,
    markers: List<HrMarker>,
    selectedDay: LocalDate,
    today: LocalDate,
    nowMs: Long,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    onBack: () -> Unit,
    onRange: (VitalRange) -> Unit,
    onRefresh: () -> Unit,
    dayNav: @Composable () -> Unit = {},
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    val accent = Vital.HR.accent
    NeonScreen(
        title = "Heart rate",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
        headerTrailing = { DetailTitleIcon(Vital.HR) },
    ) {
        app.myvitals.ui.common.VitalRangeGroup(
            selected = range, accent = accent,
            modifier = Modifier.padding(bottom = 6.dp),
        ) { onRange(it) }
        if (range == VitalRange.DAY) dayNav()
        Spacer(Modifier.height(6.dp))

        val hasContent = if (range == VitalRange.DAY) live != null else rows.isNotEmpty() || rangeStats != null
        if (!hasContent) {
            if (error != null && !loading) NeonErrorBanner(error, title = "Couldn't load heart rate") { onRefresh() }
            else DetailSkeleton(accent)
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        if (error != null) NeonErrorBanner("Showing your last saved copy. $error", title = "Couldn't refresh") { onRefresh() }

        val isToday = selectedDay == today
        if (range == VitalRange.DAY && live != null) {
            val zone = ZoneId.systemDefault()
            val startMs = selectedDay.atStartOfDay(zone).toInstant().toEpochMilli()
            val endMs = if (isToday) nowMs else selectedDay.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
            NeonHeroCard(accent) {
                NeonEyebrow(
                    if (isToday) "Today" else selectedDay.format(DateTimeFormatter.ofPattern("EEE MMM d")),
                    Modifier.padding(top = 0.dp),
                )
                Row(verticalAlignment = Alignment.Bottom) {
                    NeonNumber(live.avg?.let { "%.0f".format(it) } ?: "—", color = accent, size = 52)
                    Spacer(Modifier.width(6.dp))
                    Text("avg bpm", color = NeonMV.Muted, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 10.dp))
                }
                if (isToday) RestingChip(restingTile)
                Spacer(Modifier.height(12.dp))
                if (live.points.size < 2) {
                    DetailNote(if (isToday) "No HR samples yet today." else "No HR samples on this day.")
                } else {
                    DayTrace(live, bands, markers, startMs, endMs, accent)
                    Spacer(Modifier.height(6.dp))
                    DetailLegend(
                        live.stats?.timeInZone?.mapIndexed { i, z ->
                            HR_ZONE_COLORS[i.coerceAtMost(4)].copy(alpha = 0.6f) to z.zone
                        }.orEmpty() + bands.map { it.color to it.label }.distinctBy { it.second }.take(3),
                    )
                }
            }
            DetailStatRow(
                listOf(
                    live.minBpm?.let { "%.0f".format(it) } to "Min bpm",
                    live.avg?.let { "%.0f".format(it) } to "Avg bpm",
                    live.maxBpm?.let { "%.0f".format(it) } to "Max bpm",
                ),
                accentFirst = null,
            )
            Text(
                "The line is a 2-minute average; min and max are from every reading.",
                color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp),
            )
            live.stats?.let { zs ->
                if (zs.trackedS > 0) {
                    DetailCard(
                        "Time in zone",
                        subtitle = zs.maxHr?.let { "Zones from a max HR of $it bpm (${maxHrSourceWord(zs.maxHrSource)})" },
                    ) { TimeInZone(zs) }
                }
                if (zs.histogram.isNotEmpty()) {
                    DetailCard("HR distribution", subtitle = "5-bpm bins · time spent in each") {
                        HrHistogram(zs, accent)
                    }
                }
            }
        } else {
            NeonHeroCard(accent) {
                NeonEyebrow("Resting HR · ${range.label}", Modifier.padding(top = 0.dp))
                Row(verticalAlignment = Alignment.Bottom) {
                    NeonNumber(rangeStats?.latest?.let { "%.0f".format(it) } ?: "—", color = accent, size = 52)
                    Spacer(Modifier.width(6.dp))
                    Text("bpm latest", color = NeonMV.Muted, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 10.dp))
                }
                rangeStats?.latestVsAvg?.let { d ->
                    Text(
                        if (kotlin.math.abs(d) < 0.5) "at your ${range.label} average"
                        else "%+.0f vs ${range.label} average".format(d),
                        color = NeonMV.Muted, fontSize = 12.sp,
                    )
                }
                Spacer(Modifier.height(6.dp))
                RestingChip(restingTile)
                Spacer(Modifier.height(12.dp))
                RestingTrend(rows, restingTile, accent)
            }
            DetailStatRow(
                listOf(
                    rangeStats?.min?.let { "%.0f".format(it) } to "Min",
                    rangeStats?.avg?.let { "%.0f".format(it) } to "Avg",
                    rangeStats?.max?.let { "%.0f".format(it) } to "Max",
                ),
            )
            rangeStats?.weekdayMeans?.takeIf { w -> w.any { it.mean != null } }?.let { wm ->
                DetailCard("Resting HR by weekday", subtitle = "Average on each weekday in this window") {
                    WeekdayBars(wm.map { it.dow to it.mean }, accent, zeroAnchored = false,
                        format = { "%.0f".format(it) })
                }
            }
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun RestingChip(tile: VitalTile?) {
    val v = tile?.value as? Number ?: return
    DetailStatusChip(
        tile.status,
        "Resting ${"%.0f".format(v.toDouble())}" + (tile.statusReason?.let { " · $it" } ?: ""),
    )
}

private fun maxHrSourceWord(src: String?): String = when (src) {
    "profile" -> "from your profile"
    "estimated" -> "estimated from age"
    else -> "a default — add your birth date for a better one"
}

@Composable
private fun DayTrace(
    series: TimeSeries,
    bands: List<HrEventBand>,
    markers: List<HrMarker>,
    startMs: Long,
    endMs: Long,
    accent: Color,
) {
    val measurer = rememberTextMeasurer()
    val parsed = remember(series.points) {
        series.points.mapNotNull { p ->
            runCatching { Instant.parse(p.time).toEpochMilli() }.getOrNull()?.let { it to p.value }
        }.sortedBy { it.first }
    }
    if (parsed.size < 2) return
    val zones = series.stats?.timeInZone.orEmpty()
    Canvas(Modifier.fillMaxWidth().height(200.dp)) {
        val lo = parsed.minOf { it.second }.toFloat()
        val hi = parsed.maxOf { it.second }.toFloat()
        val domain = niceDomain(lo, hi, targetTicks = 5, minStep = 1f, padFraction = 0.10f)
        val g = chartGeom(domain, ChartInsets(
            left = 28.dp.toPx(), top = 14.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        // Zone bands: the server's own bpm boundaries, tinted per zone.
        for ((i, z) in zones.withIndex()) {
            val zlo = z.loBpm.toFloat()
            val zhi = (z.hiBpm ?: 250).toFloat()
            if (zhi < domain.min || zlo > domain.max) continue
            val y0 = g.y(zhi.coerceAtMost(domain.max))
            val y1 = g.y(zlo.coerceAtLeast(domain.min))
            drawRect(HR_ZONE_COLORS[i.coerceAtMost(4)].copy(alpha = 0.10f),
                topLeft = Offset(g.left, y0), size = Size(g.width, (y1 - y0).coerceAtLeast(0f)))
        }
        for (b in bands) {
            val s = b.startMs.coerceAtLeast(startMs)
            val e = b.endMs.coerceAtMost(endMs)
            if (e <= s) continue
            val x0 = g.xAt(s, startMs, endMs)
            val x1 = g.xAt(e, startMs, endMs)
            drawRect(b.color.copy(alpha = 0.16f), topLeft = Offset(x0, g.top),
                size = Size((x1 - x0).coerceAtLeast(1f), g.height))
            drawLine(b.color.copy(alpha = 0.6f), Offset(x0, g.top), Offset(x0, g.bottom),
                strokeWidth = 1.5.dp.toPx())
        }
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { "%.0f".format(it) }
        // The line, broken at gaps over five minutes rather than bridged.
        val path = androidx.compose.ui.graphics.Path()
        var prevT = -1L
        for ((t, v) in parsed) {
            val x = g.xAt(t, startMs, endMs); val y = g.y(v.toFloat())
            if (prevT < 0 || t - prevT > 5 * 60_000L) path.moveTo(x, y) else path.lineTo(x, y)
            prevT = t
        }
        drawPath(path, accent, style = Stroke(width = 1.8.dp.toPx(),
            cap = androidx.compose.ui.graphics.StrokeCap.Round,
            join = androidx.compose.ui.graphics.StrokeJoin.Round))
        series.avg?.let {
            val y = g.y(it.toFloat())
            drawLine(NeonMV.Ink.copy(alpha = 0.45f), Offset(g.left, y), Offset(g.right, y),
                strokeWidth = 1.dp.toPx(),
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx())))
        }
        val emoji = TextStyle(fontSize = 11.sp)
        for (m in markers) {
            if (m.ms < startMs || m.ms > endMs) continue
            drawText(measurer, m.glyph, topLeft = Offset(g.xAt(m.ms, startMs, endMs) - 6.dp.toPx(), 0f), style = emoji)
        }
        val zoneId = ZoneId.systemDefault()
        drawXLabels(g, measurer, NeonMV.Muted, listOf(0f, 0.25f, 0.5f, 0.75f, 1f).map { f ->
            val h = Instant.ofEpochMilli(startMs + ((endMs - startMs) * f).toLong()).atZone(zoneId).hour
            f to when { h == 0 -> "12a"; h < 12 -> "${h}a"; h == 12 -> "12p"; else -> "${h - 12}p" }
        })
    }
}

@Composable
private fun TimeInZone(zs: HrZoneStats) {
    Row(Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(5.dp))) {
        for ((i, z) in zs.timeInZone.withIndex()) {
            if (z.seconds > 0) {
                Box(Modifier.weight(z.seconds.toFloat()).fillMaxSize()
                    .background(HR_ZONE_COLORS[i.coerceAtMost(4)]))
            }
        }
    }
    Spacer(Modifier.height(10.dp))
    for ((i, z) in zs.timeInZone.withIndex()) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 2.dp)) {
            Box(Modifier.size(9.dp).clip(RoundedCornerShape(2.dp)).background(HR_ZONE_COLORS[i.coerceAtMost(4)]))
            Spacer(Modifier.width(8.dp))
            Text("${z.zone} · ${z.label}", color = NeonMV.Ink, fontSize = 12.sp, modifier = Modifier.weight(1f))
            Text(
                z.hiBpm?.let { "${z.loBpm}–$it" } ?: "${z.loBpm}+",
                color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.width(64.dp),
            )
            Text(fmtDurS(z.seconds) ?: "—", color = NeonMV.Ink, fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.width(60.dp))
            Text(z.pct?.let { "%.0f%%".format(it) } ?: "—", color = NeonMV.Muted, fontSize = 11.sp)
        }
    }
}

@Composable
private fun HrHistogram(zs: HrZoneStats, color: Color) {
    val measurer = rememberTextMeasurer()
    val bins = zs.histogram
    Canvas(Modifier.fillMaxWidth().height(140.dp)) {
        val domain = niceDomain(
            lo = 0f, hi = (bins.maxOfOrNull { it.minutes } ?: 1.0).toFloat().coerceAtLeast(1f),
            zeroAnchored = true, targetTicks = 3, minStep = 1f,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 30.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) {
            if (it >= 60f) "%.0fh".format(it / 60f) else "%.0fm".format(it)
        }
        val barW = g.slot(bins.size) * 0.8f
        bins.forEachIndexed { i, b ->
            if (b.minutes <= 0) return@forEachIndexed
            drawBar(g, g.xBar(i, bins.size), barW, g.y(b.minutes.toFloat()), color)
        }
        drawXLabels(g, measurer, NeonMV.Muted, buildList {
            add(0f to "${bins.first().lo}")
            if (bins.size >= 5) add(0.5f to "${bins[bins.size / 2].lo}")
            add(1f to "${bins.last().hi}")
        })
    }
}

@Composable
private fun RestingTrend(rows: List<DailySummary>, tile: VitalTile?, accent: Color) {
    val measurer = rememberTextMeasurer()
    val pts = rows.map { it.restingHr?.toFloat() }
    val real = pts.filterNotNull()
    if (real.size < 2) { DetailNote("No resting HR data in this window."); return }
    val bandLow = tile?.bandLow
    val bandHigh = tile?.bandHigh
    val baseline = tile?.baseline
    Canvas(Modifier.fillMaxWidth().height(170.dp)) {
        val domain = niceDomain(
            lo = real.min(), hi = real.max(),
            includeLo = listOfNotNull(bandLow, baseline).minOrNull()?.toFloat(),
            includeHi = listOfNotNull(bandHigh, baseline).maxOrNull()?.toFloat(),
            minStep = 1f,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 26.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track) { "%.0f".format(it) }
        if (bandLow != null && bandHigh != null) drawNormalBand(g, bandLow.toFloat(), bandHigh.toFloat(), accent)
        baseline?.let {
            drawReferenceLine(g, it.toFloat(), NeonMV.Muted, measurer, "baseline ${kotlin.math.round(it).toInt()}")
        }
        val line = androidx.compose.ui.graphics.Path()
        var lastPt: Offset? = null
        var lastIdx = -1
        for ((i, v) in pts.withIndex()) {
            if (v == null) continue
            val p = Offset(g.x(i, pts.size), g.y(v))
            val prev = lastPt
            when {
                prev == null -> line.moveTo(p.x, p.y)
                i - lastIdx > 1 -> { drawGapBridge(prev, p, accent); line.moveTo(p.x, p.y) }
                else -> line.lineTo(p.x, p.y)
            }
            if (pts.size <= 31) drawCircle(accent, radius = 1.8.dp.toPx(), center = p)
            lastPt = p; lastIdx = i
        }
        drawPath(line, accent, style = Stroke(width = 2.dp.toPx(),
            cap = androidx.compose.ui.graphics.StrokeCap.Round,
            join = androidx.compose.ui.graphics.StrokeJoin.Round))
        val firstIdx = pts.indexOfFirst { it != null }
        val lastRealIdx = pts.indexOfLast { it != null }
        val minGap = (GAP_MIN_FRACTION * pts.size).coerceAtLeast(1f)
        if (firstIdx > minGap) drawNoDataSpan(g.left, g.x(firstIdx, pts.size), g.y(pts[firstIdx]!!), accent)
        if (pts.size - 1 - lastRealIdx > minGap) {
            drawNoDataSpan(g.x(lastRealIdx, pts.size), g.right, g.y(pts[lastRealIdx]!!), accent)
        }
        lastPt?.let { drawLatestMarker(it, accent, NeonMV.CardHigh) }
        drawXLabels(g, measurer, NeonMV.Muted, buildList {
            add(0f to detailMd(rows.first().date))
            if (rows.size >= 5) add(0.5f to detailMd(rows[rows.size / 2].date))
            add(1f to detailMd(rows.last().date))
        })
    }
    if (bandLow != null && bandHigh != null) {
        Spacer(Modifier.height(6.dp))
        DetailLegend(listOf(accent.copy(alpha = 0.3f) to "usual range ${bandLow.toInt()}–${bandHigh.toInt()} bpm"))
    }
}

private fun annotationEmoji(kind: String): String = when (kind) {
    "caffeine" -> "☕"
    "alcohol" -> "🍺"
    "mood" -> "🙂"
    "food" -> "🍽️"
    "meds" -> "💊"
    "note" -> "📝"
    else -> "•"
}
