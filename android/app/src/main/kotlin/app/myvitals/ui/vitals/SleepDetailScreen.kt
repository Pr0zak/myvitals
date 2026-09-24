package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
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
import app.myvitals.sync.RangeStats
import app.myvitals.sync.SleepNight
import app.myvitals.sync.SleepRangeStats
import app.myvitals.sync.SleepRawSegment
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

/**
 * Stage colours, all tokens. Deep used to be #1E40AF — navy on a near-black
 * card, so the stage that matters most was the one you could not see.
 * Both Fitbit vocabularies are covered: stages (light/deep/rem/wake) and the
 * classic levels (asleep/restless/awake).
 */
internal val STAGE_COLORS: Map<String, Color> = mapOf(
    "deep" to NeonMV.Periwinkle,
    "light" to NeonMV.Periwinkle.copy(alpha = 0.6f),
    "core" to NeonMV.Periwinkle.copy(alpha = 0.6f),
    "rem" to NeonMV.Magenta,
    "awake" to NeonMV.Amber,
    "asleep" to NeonMV.Periwinkle.copy(alpha = 0.8f),
    "restless" to NeonMV.Amber.copy(alpha = 0.55f),
    "out_of_bed" to NeonMV.Muted,
    "unmeasurable" to NeonMV.Muted.copy(alpha = 0.6f),
    "unknown" to NeonMV.Muted.copy(alpha = 0.6f),
)

private val STAGE_SYNONYMS = mapOf("wake" to "awake")

internal fun canonicalStage(raw: String): String {
    val s = raw.lowercase()
    return STAGE_SYNONYMS[s] ?: s
}

/** Hypnogram rows, shallowest first; only the stages present are drawn. */
private val HYPNO_ORDER = listOf(
    "awake", "restless", "rem", "light", "core", "asleep", "deep",
    "out_of_bed", "unmeasurable", "unknown",
)
private val STACK_ORDER = listOf(
    "deep", "asleep", "light", "core", "rem", "restless", "awake",
    "out_of_bed", "unmeasurable", "unknown",
)

/**
 * Sleep detail (UI-4). Hero = the chosen night: duration, the server's
 * verdict chip, and the hypnogram with its legend inline. Below: the
 * window's stats (server `/summary/range/stats` sleep block — naps
 * excluded there, not here), the per-night stage stack and the duration
 * trend against the server's sleep target.
 */
@Composable
fun SleepDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var nights by remember { mutableStateOf<List<SleepNight>>(emptyList()) }
    var stats by remember { mutableStateOf<SleepRangeStats?>(null) }
    var tile by remember { mutableStateOf<VitalTile?>(null) }
    var raw by remember { mutableStateOf<List<SleepRawSegment>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var selectedDay by remember { mutableStateOf(LocalDate.now()) }

    val nightsType = com.squareup.moshi.Types.newParameterizedType(List::class.java, SleepNight::class.java)
    val rawType = com.squareup.moshi.Types.newParameterizedType(List::class.java, SleepRawSegment::class.java)

    suspend fun fetchRaw(day: LocalDate) {
        val cacheKey = "sleep_detail_raw_$day"
        raw = JsonCache.read<List<SleepRawSegment>>(context, cacheKey, rawType)?.value ?: emptyList()
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val zone = ZoneId.systemDefault()
            // The night ending on `day`: 18:00 the evening before → 14:00.
            val start = day.minusDays(1).atTime(18, 0).atZone(zone).toInstant().toString()
            val end = day.atTime(14, 0).atZone(zone).toInstant().toString()
            val r = withContext(Dispatchers.IO) { api.sleepRaw(since = start, until = end) }
            raw = r
            JsonCache.write(context, cacheKey, rawType, r)
        } catch (e: Exception) {
            Timber.w(e, "sleep raw load failed for %s", day)
        }
    }

    suspend fun fetch() {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val today = LocalDate.now()
            val zone = ZoneId.systemDefault()
            val firstDay = today.minusDays(13)
            // Same local window the stats endpoint uses, so the chart and the
            // numbers under it count the same nights.
            val since = firstDay.minusDays(1).atTime(18, 0).atZone(zone).toInstant().toString()
            coroutineScope {
                val nD = async(Dispatchers.IO) { api.sleepRange(since = since) }
                val sD = async(Dispatchers.IO) {
                    runCatching { api.summaryRangeStats(since = firstDay.toString(), until = today.toString()) }
                        .getOrNull()
                }
                val tD = async(Dispatchers.IO) {
                    runCatching { api.summaryTiles().tiles.firstOrNull { it.key == "sleep_duration" } }
                        .getOrNull()
                }
                nights = nD.await()
                JsonCache.write(context, "sleep_detail_nights", nightsType, nights)
                sD.await()?.let {
                    stats = it.sleep
                    JsonCache.write(context, "sleep_detail_stats", RangeStats::class.java, it)
                }
                tile = tD.await()
            }
            fetchRaw(selectedDay)
            error = null
        } catch (e: Exception) {
            Timber.w(e, "sleep detail load failed")
            error = e.message?.take(160) ?: "Couldn't reach the backend."
        } finally { loading = false }
    }

    LaunchedEffect(Unit) {
        JsonCache.read<List<SleepNight>>(context, "sleep_detail_nights", nightsType)
            ?.let { nights = it.value; loading = false }
        JsonCache.read<RangeStats>(context, "sleep_detail_stats", RangeStats::class.java)
            ?.let { stats = it.value.sleep }
        fetch()
    }
    LaunchedEffect(selectedDay) { if (nights.isNotEmpty()) fetchRaw(selectedDay) }

    SleepDetailContent(
        nights = nights, stats = stats, tile = tile, raw = raw,
        selectedDay = selectedDay, today = LocalDate.now(),
        loading = loading, refreshing = refreshing, error = error,
        onBack = onBack,
        onRefresh = { scope.launch { refreshing = true; try { fetch() } finally { refreshing = false } } },
        dayNav = {
            app.myvitals.ui.common.DayNav(selected = selectedDay, onSelectedChange = { selectedDay = it })
        },
    )
}

/** The night that ENDED on [day] (local), longest first; naps only if
 *  there is no night. No fallback to some other night — a day without a
 *  recorded night says so rather than showing yesterday's under its date. */
internal fun nightEndingOn(nights: List<SleepNight>, day: LocalDate): SleepNight? {
    val zone = ZoneId.systemDefault()
    val onDay = nights.filter { n ->
        val end = n.end?.let { runCatching { Instant.parse(it).atZone(zone).toLocalDate() }.getOrNull() }
        (end ?: runCatching { LocalDate.parse(n.date) }.getOrNull()) == day
    }
    return onDay.filter { it.kind != "nap" }.maxByOrNull { it.totalS } ?: onDay.maxByOrNull { it.totalS }
}

@Composable
fun SleepDetailContent(
    nights: List<SleepNight>,
    stats: SleepRangeStats?,
    tile: VitalTile?,
    raw: List<SleepRawSegment>,
    selectedDay: LocalDate,
    today: LocalDate,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    dayNav: @Composable () -> Unit = {},
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    val accent = Vital.SLEEP.accent
    NeonScreen(
        title = "Sleep",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
        headerTrailing = { DetailTitleIcon(Vital.SLEEP) },
    ) {
        dayNav()
        Spacer(Modifier.height(6.dp))
        if (nights.isEmpty() && stats == null) {
            if (error != null && !loading) NeonErrorBanner(error) { onRefresh() }
            else if (loading) DetailSkeleton(accent)
            else DetailNote("No sleep sessions in the last two weeks.")
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        if (error != null) NeonErrorBanner("Showing your last saved copy. $error") { onRefresh() }

        val isToday = selectedDay == today
        val night = nightEndingOn(nights, selectedDay)
        NeonHeroCard(accent) {
            NeonEyebrow(
                if (isToday) "Last night"
                else "Night ending " + selectedDay.format(DateTimeFormatter.ofPattern("EEE MMM d")),
                Modifier.padding(top = 0.dp),
            )
            NeonNumber(fmtDurS(night?.totalS) ?: "—", color = accent, size = 50)
            Text(
                night?.let { formatStartEnd(it) } ?: "No night recorded ending on this day",
                color = NeonMV.Muted, fontSize = 12.sp,
            )
            if (isToday) {
                Spacer(Modifier.height(8.dp))
                DetailStatusChip(tile?.status, tile?.statusReason)
            }
            Spacer(Modifier.height(12.dp))
            Hypnogram(raw)
            val present = raw.map { canonicalStage(it.stage) }.toSet()
            if (present.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                val byStage = night?.stages?.groupBy { canonicalStage(it.stage) }
                    ?.mapValues { e -> e.value.sumOf { it.durationS } }.orEmpty()
                DetailLegend(HYPNO_ORDER.filter { it in present }.map { st ->
                    (STAGE_COLORS[st] ?: NeonMV.Muted) to (st + (byStage[st]?.let { " ${it / 60}m" } ?: ""))
                })
            }
        }
        DetailStatRow(
            listOf(
                fmtDurS(stats?.avgS) to "Avg night",
                fmtDurS(stats?.minS) to "Shortest",
                fmtDurS(stats?.maxS) to "Longest",
            ),
            accentFirst = accent,
        )
        stats?.let {
            Text(
                "${it.nights} night${if (it.nights == 1) "" else "s"} in the last 14 days" +
                    if (it.naps > 0) " · ${it.naps} nap${if (it.naps == 1) "" else "s"} not counted" else "",
                color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp),
            )
        }
        DetailCard("Stage breakdown") { StageBreakdown(nights) }
        DetailCard("Duration", subtitle = tile?.target?.let { "Dashed line: your ${"%.1f".format(it)} h target" }) {
            DurationLine(nights.filter { it.kind != "nap" }, tile?.target?.toFloat(), accent)
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun Hypnogram(segments: List<SleepRawSegment>) {
    if (segments.isEmpty()) { DetailNote("No stage detail synced for this night yet."); return }
    val measurer = rememberTextMeasurer()
    val parsed = remember(segments) {
        segments.mapNotNull { s ->
            val t = runCatching { Instant.parse(s.time).toEpochMilli() }.getOrNull() ?: return@mapNotNull null
            Triple(t, t + s.durationS * 1000L, canonicalStage(s.stage))
        }
    }
    val rows = remember(parsed) {
        val present = parsed.mapTo(HashSet()) { it.third }
        HYPNO_ORDER.filter { it in present }.ifEmpty { HYPNO_ORDER.take(1) }
    }
    val tStart = parsed.minOfOrNull { it.first } ?: return
    val tEnd = parsed.maxOfOrNull { it.second } ?: return
    Canvas(Modifier.fillMaxWidth().height((rows.size * 28).coerceAtLeast(96).dp)) {
        val gutter = 44.dp.toPx()
        val axisH = 14.dp.toPx()
        val plotW = size.width - gutter
        val plotH = size.height - axisH
        val span = (tEnd - tStart).toFloat().coerceAtLeast(1f)
        val rowH = plotH / rows.size
        val labelStyle = TextStyle(color = NeonMV.Muted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
        for ((i, st) in rows.withIndex()) {
            val y = i * rowH
            drawLine(NeonMV.Track, Offset(gutter, y + rowH), Offset(size.width, y + rowH), strokeWidth = 0.7.dp.toPx())
            val lay = measurer.measure(st, labelStyle)
            drawText(lay, topLeft = Offset((gutter - 6.dp.toPx() - lay.size.width).coerceAtLeast(0f),
                y + (rowH - lay.size.height) / 2f))
        }
        for ((s, e, stage) in parsed) {
            val idx = rows.indexOf(stage).takeIf { it >= 0 } ?: continue
            val x0 = gutter + ((s - tStart).toFloat() / span) * plotW
            val x1 = gutter + ((e - tStart).toFloat() / span) * plotW
            drawRoundRect(
                color = STAGE_COLORS[stage] ?: NeonMV.Muted,
                topLeft = Offset(x0, idx * rowH + rowH * 0.16f),
                size = Size((x1 - x0).coerceAtLeast(1f), rowH * 0.68f),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(2.dp.toPx()),
            )
        }
        val axisStyle = TextStyle(color = NeonMV.Muted, fontSize = 9.sp)
        val hourMs = 3_600_000L
        val zoneId = ZoneId.systemDefault()
        var tick = Instant.ofEpochMilli(tStart).atZone(zoneId).withMinute(0).withSecond(0).withNano(0)
            .plusHours(1).toInstant().toEpochMilli()
        val stepH = if (tEnd - tStart > 8 * hourMs) 2L else 1L
        while (tick <= tEnd) {
            val x = gutter + ((tick - tStart).toFloat() / span) * plotW
            val lay = measurer.measure(
                DateTimeFormatter.ofPattern("h a").format(Instant.ofEpochMilli(tick).atZone(zoneId)).lowercase(),
                axisStyle,
            )
            drawText(lay, topLeft = Offset((x - lay.size.width / 2f).coerceIn(0f, size.width - lay.size.width),
                plotH + 2.dp.toPx()))
            tick += stepH * hourMs
        }
    }
}

/** Nights on a continuous day axis, null where none was recorded. */
private fun onDayAxis(nights: List<SleepNight>): List<SleepNight?> {
    val byDate = nights.associateBy { it.date }
    val days = nights.mapNotNull { runCatching { LocalDate.parse(it.date) }.getOrNull() }
    val first = days.minOrNull() ?: return nights
    val last = days.maxOrNull() ?: return nights
    val span = java.time.temporal.ChronoUnit.DAYS.between(first, last).toInt()
    if (span < 0 || span > 400) return nights
    return (0..span).map { byDate[first.plusDays(it.toLong()).toString()] }
}

@Composable
private fun StageBreakdown(nights: List<SleepNight>) {
    if (nights.isEmpty()) { DetailNote("No data."); return }
    val measurer = rememberTextMeasurer()
    val present = nights.flatMap { n -> n.stages.map { canonicalStage(it.stage) } }.toSet()
    Canvas(Modifier.fillMaxWidth().height(160.dp)) {
        val tops = nights.map { n -> n.stages.sumOf { it.durationS } / 3600f }
        val domain = niceDomain(0f, (tops.maxOrNull() ?: 1f).coerceAtLeast(1f),
            zeroAnchored = true, targetTicks = 3, minStep = 1f)
        val g = chartGeom(domain, ChartInsets(
            left = 26.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { "%.0fh".format(it) }
        val slots = onDayAxis(nights)
        val barW = g.slot(slots.size) * 0.72f
        for ((i, n) in slots.withIndex()) {
            if (n == null) continue
            val cx = g.xBar(i, slots.size)
            var acc = 0f
            for (st in STACK_ORDER) {
                val secs = n.stages.filter { canonicalStage(it.stage) == st }.sumOf { it.durationS }
                if (secs <= 0) continue
                val hrs = secs / 3600f
                val yTop = g.y(acc + hrs)
                val yBot = g.y(acc)
                drawRect(STAGE_COLORS[st] ?: NeonMV.Muted, topLeft = Offset(cx - barW / 2f, yTop),
                    size = Size(barW, (yBot - yTop).coerceAtLeast(0f)))
                acc += hrs
            }
        }
        drawXLabels(g, measurer, NeonMV.Muted, buildList {
            val n = slots.size
            slots.firstOrNull { it != null }?.let { add((0.5f / n) to detailMd(it.date)) }
            if (n >= 2) slots.lastOrNull { it != null }?.let { add(((n - 0.5f) / n) to detailMd(it.date)) }
        })
    }
    Spacer(Modifier.height(8.dp))
    DetailLegend(STACK_ORDER.filter { it in present }.map { (STAGE_COLORS[it] ?: NeonMV.Muted) to it })
}

@Composable
private fun DurationLine(nights: List<SleepNight>, goalH: Float?, color: Color) {
    if (nights.size < 2) { DetailNote("Not enough nights to draw a trend."); return }
    val measurer = rememberTextMeasurer()
    Canvas(Modifier.fillMaxWidth().height(120.dp)) {
        val slots = onDayAxis(nights)
        val ys = slots.map { it?.let { n -> n.totalS / 3600f } }
        val real = ys.filterNotNull()
        if (real.isEmpty()) return@Canvas
        val domain = niceDomain(0f, maxOf(real.max(), goalH ?: 0f), targetTicks = 3, minStep = 1f, zeroAnchored = true)
        val g = chartGeom(domain, ChartInsets(
            left = 24.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 4.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { "%.0fh".format(it) }
        goalH?.let { drawReferenceLine(g, it, NeonMV.Ink, measurer, "target ${"%.1f".format(it)}h") }
        val path = androidx.compose.ui.graphics.Path()
        var prev: Offset? = null
        var prevIdx = -1
        for ((i, y) in ys.withIndex()) {
            if (y == null) continue
            val p = Offset(g.x(i, ys.size), g.y(y))
            val p0 = prev
            when {
                p0 == null -> path.moveTo(p.x, p.y)
                i - prevIdx > 1 -> { drawGapBridge(p0, p, color); path.moveTo(p.x, p.y) }
                else -> path.lineTo(p.x, p.y)
            }
            drawCircle(color, radius = 2.dp.toPx(), center = p)
            prev = p; prevIdx = i
        }
        drawPath(path, color, style = Stroke(width = 2.dp.toPx(),
            cap = androidx.compose.ui.graphics.StrokeCap.Round,
            join = androidx.compose.ui.graphics.StrokeJoin.Round))
    }
}

private fun formatStartEnd(n: SleepNight): String {
    val zone = ZoneId.systemDefault()
    val s = n.start?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() }
    val e = n.end?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() }
    val fmt = DateTimeFormatter.ofPattern("h:mm a")
    return if (s == null || e == null) n.date else "${fmt.format(s)} → ${fmt.format(e)}"
}
