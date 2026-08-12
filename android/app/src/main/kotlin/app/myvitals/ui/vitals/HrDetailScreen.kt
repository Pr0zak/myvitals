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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
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
import app.myvitals.ui.LocalAppTokens

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
    // Server-derived normal band for resting HR — same bounds the metric
    // card shades. Never recomputed here.
    var bandLow by remember { mutableStateOf<Double?>(null) }
    var bandHigh by remember { mutableStateOf<Double?>(null) }
    LaunchedEffect(Unit) {
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            api.summaryTiles().tiles.firstOrNull { it.key == "resting_hr" }?.let {
                bandLow = it.bandLow; bandHigh = it.bandHigh
            }
        }
    }

    val tok = LocalAppTokens.current
    val context = androidx.compose.ui.platform.LocalContext.current
    var range by remember { mutableStateOf(VitalRange.DAY) }
    // Day selector — only visible when range == DAY. Drives the 24h
    // window so the user can scroll back through prior days.
    var selectedDay by remember { mutableStateOf(java.time.LocalDate.now()) }
    var live by remember { mutableStateOf<List<TimePoint>>(emptyList()) }
    // Server-computed over the RAW rows; `live` is 2-minute bucket means.
    var liveMin by remember { mutableStateOf<Double?>(null) }
    var liveMax by remember { mutableStateOf<Double?>(null) }
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    // Which range `rows` was actually fetched for. Without this the card
    // renders the PREVIOUS range's series under the new range's title the
    // moment you tap a tab — tapping 90d after 30d drew 30 days of history
    // headed "RESTING HR — 90D", stats and date axis included.
    var rowsRange by remember { mutableStateOf<VitalRange?>(null) }
    var bands by remember { mutableStateOf<List<HrEventBand>>(emptyList()) }
    var annotations by remember {
        mutableStateOf<List<app.myvitals.sync.Annotation>>(emptyList())
    }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var maxHr by remember { mutableStateOf(190) }

    val rowsType = com.squareup.moshi.Types.newParameterizedType(
        List::class.java, DailySummary::class.java,
    )

    // SWR: read last-rendered rows + live points for the current range
    // and render them so the screen never shows a spinner on a warm
    // launch. Fresh fetch overwrites once it lands.
    suspend fun maybeShowCache() {
        val rowsKey = "hr_detail_rows_${range.name.lowercase()}"
        app.myvitals.data.JsonCache.read<List<DailySummary>>(context, rowsKey, rowsType)
            ?.let { rows = it.value; rowsRange = range; loading = false }
    }

    suspend fun fetch() {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            // Profile drives zone thresholds. Re-fetch on every load so a
            // birth-date update flows through to the chart immediately.
            runCatching { api.profile() }.getOrNull()?.let { maxHr = it.maxHr() }
            coroutineScope {
                if (range == VitalRange.DAY) {
                    // Anchor the 24h window to selectedDay (local midnight
                    // → next local midnight) so past-day views render the
                    // right HR data, not a sliding "last 24 hours".
                    val zone = java.time.ZoneId.systemDefault()
                    val now = Instant.now()
                    val isToday = selectedDay == java.time.LocalDate.now()
                    val dayEnd = if (isToday) now
                        else selectedDay.plusDays(1).atStartOfDay(zone).toInstant()
                    val dayStart = selectedDay.atStartOfDay(zone).toInstant()
                    val sinceIso = dayStart.toString()
                    val untilIso = dayEnd.toString()
                    val liveD = async(Dispatchers.IO) {
                        // 2-min buckets — ~720 points/day instead of ~5k
                        // raw samples. Chart was already downsampling
                        // client-side; doing it server-side cuts the
                        // payload + JSON parse 5-10x.
                        api.heartRateSeries(
                            since = sinceIso, until = untilIso,
                            bucketSeconds = 120,
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
                    val annoD = async(Dispatchers.IO) {
                        runCatching {
                            api.journalList(since = sinceIso, until = untilIso, limit = 50)
                        }.getOrDefault(emptyList())
                    }
                    val liveSeries = liveD.await()
                    live = liveSeries.points
                    liveMin = liveSeries.minBpm
                    liveMax = liveSeries.maxBpm
                    annotations = annoD.await()

                    // Build event bands for the day's window. Off-wrist
                    // bands were removed in v0.7.272 — wear-state timing
                    // from HA was unreliable enough that bands often
                    // covered actual on-wrist periods.
                    val windowStart = dayStart.toEpochMilli()
                    val windowEnd = dayEnd.toEpochMilli()
                    val list = mutableListOf<HrEventBand>()
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
                            color = Vital.WORKOUT.accent)
                    }
                    bands = list
                    rows = emptyList()
                } else {
                    val since = LocalDate.now().minusDays(range.days.toLong() - 1).toString()
                    val fresh = withContext(Dispatchers.IO) { api.summaryRange(since = since) }
                    rows = fresh
                    rowsRange = range
                    app.myvitals.data.JsonCache.write(
                        context,
                        "hr_detail_rows_${range.name.lowercase()}",
                        rowsType, fresh,
                    )
                    live = emptyList()
                }
            }
            Timber.i("HR detail: range=%s live=%d rows=%d", range, live.size, rows.size)
        } catch (e: Exception) {
            Timber.w(e, "HR detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(range, selectedDay) {
        // Drop the outgoing range's data before anything renders under the new
        // title. maybeShowCache() puts it straight back when this range has
        // been seen before, so the SWR warm-start still holds.
        if (rowsRange != null && rowsRange != range) {
            rows = emptyList(); rowsRange = null; loading = true
        }
        maybeShowCache()
        fetch()
    }

    Column(Modifier.fillMaxSize().background(tok.bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = tok.onSurface)
            }
            Icon(Vital.HR.icon, contentDescription = null, tint = Vital.HR.accent,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Heart rate", color = tok.onSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            VitalRange.entries.forEach { r ->
                FilterChip(
                    selected = r == range,
                    onClick = {
                        range = r
                        if (r != VitalRange.DAY) selectedDay = java.time.LocalDate.now()
                    },
                    label = { Text(r.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = Vital.HR.accent.copy(alpha = 0.20f),
                        selectedLabelColor = tok.onSurface,
                    ),
                )
            }
        }
        if (range == VitalRange.DAY) {
            app.myvitals.ui.common.DayNav(
                selected = selectedDay,
                onSelectedChange = { selectedDay = it },
            )
        }
        when {
            loading -> Text("Loading…", color = tok.onSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null && rows.isEmpty() && live.isEmpty() ->
                Text(error!!, color = tok.red, modifier = Modifier.padding(16.dp))
            else -> app.myvitals.ui.common.PullableMetricBox(
                refreshing = refreshing,
                onRefresh = {
                    refreshing = true
                    try { fetch() } finally { refreshing = false }
                },
            ) {
            LazyColumn(
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (range == VitalRange.DAY) {
                    item { LiveHrChart(live, maxHr, bands, annotations, selectedDay, liveMin, liveMax) }
                    item { TimeInZone(live, maxHr) }
                    item { HrHistogram(live) }
                } else {
                    item { RestingHrTrend(rows, range, bandLow, bandHigh) }
                    item { WeekdayPattern(rows) }
                }
            }
            }
        }
    }
}

private fun annotationEmoji(kind: String): String = when (kind) {
    "caffeine" -> "☕"
    "alcohol"  -> "🍺"
    "mood"     -> "🙂"
    "food"     -> "🍽️"
    "meds"     -> "💊"
    "note"     -> "📝"
    else        -> "•"
}

@Composable
private fun LiveHrChart(
    points: List<TimePoint>,
    maxHr: Int,
    bands: List<HrEventBand> = emptyList(),
    annotations: List<app.myvitals.sync.Annotation> = emptyList(),
    day: java.time.LocalDate = java.time.LocalDate.now(),
    trueMin: Double? = null,
    trueMax: Double? = null,
) {
    val tok = LocalAppTokens.current
    // The same window fetch() asked the backend for, so the x-axis and the
    // data agree about what "this day" means.
    val zone = java.time.ZoneId.systemDefault()
    val dayStartMs = day.atStartOfDay(zone).toInstant().toEpochMilli()
    val dayEndMs = if (day == java.time.LocalDate.now()) Instant.now().toEpochMilli()
                   else day.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            // DayNav can scroll back to any past day, so "LAST 24H" was a
            // lie on every day but today.
            val isToday = day == java.time.LocalDate.now()
            Text(
                if (isToday) "LAST 24H"
                else "${day.dayOfWeek.name.take(3)} ${day.monthValue}/${day.dayOfMonth}",
                color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (points.size < 2) {
                Text(
                    if (isToday) "No HR samples in the last 24h."
                    else "No HR samples on this day.",
                    color = tok.onSurfaceVariant, fontSize = 12.sp); return@Card
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
            val textMeasurer = rememberTextMeasurer()
            // Pre-parse annotation timestamps so we can drop emoji glyphs
            // at the top of the chart at their exact x-position (LOG-4
            // phone parity).
            val parsedAnnotations = remember(annotations) {
                annotations.mapNotNull { a ->
                    val t = runCatching { Instant.parse(a.ts).toEpochMilli() }
                        .getOrNull() ?: return@mapNotNull null
                    t to annotationEmoji(a.type)
                }
            }
            Box(Modifier.fillMaxWidth().height(220.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val padX = 32.dp.toPx()
                    val padTop = 8.dp.toPx()
                    val padBot = 16.dp.toPx()
                    val plotW = size.width - padX
                    val plotH = size.height - padTop - padBot
                    // Anchor x to the DAY, not to first/last sample. Using the
                    // sample extent stretched a short run of readings across
                    // the full width: a watch worn 09:00-11:00 drew a chart
                    // that looked like 24 hours of data, and the workout bands
                    // (which ARE positioned by wall-clock) landed on the wrong
                    // part of it.
                    val tStart = dayStartMs
                    val tEnd = dayEndMs
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
                            color = tok.onSurfaceDim.copy(alpha = 0.15f),
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
                        color = tok.onSurfaceVariant.copy(alpha = 0.55f),
                        start = Offset(padX, avgY), end = Offset(size.width, avgY),
                        strokeWidth = 1.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(
                            floatArrayOf(4.dp.toPx(), 3.dp.toPx())
                        ),
                    )
                    // Annotation emoji markers — drop above the chart so
                    // caffeine / mood / etc. entries align with the HR
                    // trace they affected (LOG-4 phone parity).
                    val emojiStyle = TextStyle(fontSize = 12.sp)
                    for ((t, glyph) in parsedAnnotations) {
                        if (t < tStart || t > tEnd) continue
                        val x = padX + ((t - tStart).toFloat() / tSpan) * plotW
                        drawText(
                            textMeasurer = textMeasurer,
                            text = glyph,
                            topLeft = Offset(x - 6.dp.toPx(), 0f),
                            style = emojiStyle,
                        )
                    }

                    // Clock labels. The 16dp bottom gutter was reserved and
                    // left empty, so a 24h trace had no time axis at all —
                    // you could see a spike but not when it happened.
                    val axisStyle = TextStyle(
                        color = tok.onSurfaceDim, fontSize = 9.sp,
                        fontWeight = FontWeight.Medium,
                    )
                    val zoneId = java.time.ZoneId.systemDefault()
                    for (frac in listOf(0f, 0.25f, 0.5f, 0.75f, 1f)) {
                        val ms = tStart + ((tEnd - tStart) * frac).toLong()
                        val lt = Instant.ofEpochMilli(ms).atZone(zoneId)
                        val h = lt.hour
                        val label = when {
                            h == 0 -> "12a"
                            h < 12 -> "${h}a"
                            h == 12 -> "12p"
                            else -> "${h - 12}p"
                        }
                        val lay = textMeasurer.measure(label, axisStyle)
                        val x = (padX + frac * plotW - lay.size.width / 2f)
                            .coerceIn(0f, size.width - lay.size.width)
                        drawText(lay, topLeft = Offset(x, size.height - padBot + 2.dp.toPx()))
                    }
                }
                // Y-axis label column
                Column(Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.SpaceBetween) {
                    Text("${(maxV + 8).toInt()}",
                        color = tok.onSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("${((minV + maxV) / 2).toInt()}",
                        color = tok.onSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("${(minV - 8).coerceAtLeast(40.0).toInt()}",
                        color = tok.onSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp, bottom = 12.dp))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                // Server's raw-row extremes when available: minV/maxV are
                // taken from 2-minute bucket means, which flatten a short
                // sprint and put this card at odds with the Activities feed's
                // per-activity max_hr for the same session.
                Stat("Min", "${kotlin.math.round(trueMin ?: minV).toInt()} bpm")
                Stat("Avg", "%.0f bpm".format(avgV))
                Stat("Max", "${kotlin.math.round(trueMax ?: maxV).toInt()} bpm")
                // These are 2-minute windows, not raw samples.
                Stat("Readings", "${points.size}")
            }
        }
    }
}

@Composable
private fun TimeInZone(points: List<TimePoint>, maxHr: Int) {
    val tok = LocalAppTokens.current
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
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TIME IN ZONE — 24H", color = tok.onSurfaceVariant,
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
                    Text(zoneLabel(zi), color = tok.onSurface, fontSize = 11.sp,
                        modifier = Modifier.weight(1f))
                    Text(fmtSec(zoneSecs[zi]), color = tok.onSurfaceVariant, fontSize = 11.sp,
                        modifier = Modifier.width(72.dp))
                    Text("$pct%", color = tok.onSurfaceDim, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
private fun RestingHrTrend(
    rows: List<DailySummary>,
    range: VitalRange,
    bandLow: Double? = null,
    bandHigh: Double? = null,
) {
    val tok = LocalAppTokens.current
    val measurer = rememberTextMeasurer()
    val accent = Vital.HR.accent
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("RESTING HR — ${range.label.uppercase()}",
                color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val pts = rows.map { it.restingHr?.toFloat() }
            val real = pts.filterNotNull()
            if (real.size < 2) {
                Text("No resting HR data in this window.",
                    color = tok.onSurfaceVariant, fontSize = 12.sp); return@Card
            }
            Row(verticalAlignment = Alignment.Bottom) {
                Text("%.0f".format(real.last()), color = tok.onSurface,
                    fontSize = 30.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(4.dp))
                Text("bpm", color = tok.onSurfaceDim, fontSize = 11.sp,
                    modifier = Modifier.padding(bottom = 5.dp))
                Spacer(Modifier.weight(1f))
                // Where the latest reading sits against the window, so the big
                // number means something without reading the chart.
                val avg = real.average().toFloat()
                val d = real.last() - avg
                Text(
                    if (kotlin.math.abs(d) < 0.5f) "at your ${range.label} average"
                    else "%+.0f vs ${range.label} avg".format(d),
                    color = tok.onSurfaceVariant, fontSize = 11.sp,
                    modifier = Modifier.padding(bottom = 5.dp),
                )
            }
            Spacer(Modifier.height(10.dp))
            Box(Modifier.fillMaxWidth().height(170.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    // Force the server's band inside the domain. Left to the
                    // data's own min..max, a band wider than the window (usual
                    // on 7d) got clipped at the top edge and read as "every
                    // reading is abnormal" — the opposite of the truth.
                    val domain = niceDomain(
                        lo = real.min(), hi = real.max(),
                        includeLo = bandLow?.toFloat(), includeHi = bandHigh?.toFloat(),
                        minStep = 1f,   // labels are "%.0f" bpm
                    )
                    val g = chartGeom(domain, ChartInsets(
                        left = 26.dp.toPx(), top = 6.dp.toPx(),
                        right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                    ))
                    drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface) {
                        "%.0f".format(it)
                    }
                    if (bandLow != null && bandHigh != null) {
                        drawNormalBand(g, bandLow.toFloat(), bandHigh.toFloat(), accent)
                    }

                    // Area fill under the line, then the line itself. Gaps are
                    // bridged with a dash so a missing day reads as a gap
                    // rather than as a broken chart.
                    val line = androidx.compose.ui.graphics.Path()
                    val area = androidx.compose.ui.graphics.Path()
                    var lastPt: Offset? = null
                    var lastIdx = -1
                    var latest: Offset? = null
                    for ((i, v) in pts.withIndex()) {
                        if (v == null) continue
                        val p = Offset(g.x(i, pts.size), g.y(v))
                        val prev = lastPt
                        if (prev == null) {
                            line.moveTo(p.x, p.y)
                            area.moveTo(p.x, g.bottom); area.lineTo(p.x, p.y)
                        } else if (i - lastIdx > 1) {
                            // At least one day with no reading sits between
                            // these two samples: dash across it instead of
                            // drawing a solid segment that implies data.
                            drawGapBridge(prev, p, accent)
                            line.moveTo(p.x, p.y)
                            area.lineTo(p.x, p.y)
                        } else {
                            line.lineTo(p.x, p.y)
                            area.lineTo(p.x, p.y)
                        }
                        lastPt = p
                        lastIdx = i
                        latest = p
                        if (pts.size <= 31) {
                            drawCircle(accent.copy(alpha = 0.9f),
                                radius = 1.8.dp.toPx(), center = p)
                        }
                    }
                    lastPt?.let { area.lineTo(it.x, g.bottom); area.close() }
                    drawPath(
                        area,
                        brush = androidx.compose.ui.graphics.Brush.verticalGradient(
                            listOf(accent.copy(alpha = 0.26f), accent.copy(alpha = 0f)),
                            startY = g.top, endY = g.bottom,
                        ),
                    )
                    drawPath(line, color = accent,
                        style = Stroke(width = 2.dp.toPx(),
                            cap = androidx.compose.ui.graphics.StrokeCap.Round,
                            join = androidx.compose.ui.graphics.StrokeJoin.Round))
                    latest?.let { drawLatestMarker(it, accent, tok.surfaceContainer) }

                    drawXLabels(g, measurer, tok.onSurfaceDim, xTicks(rows))
                }
            }
            if (bandLow != null && bandHigh != null) {
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(width = 14.dp, height = 8.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(accent.copy(alpha = 0.22f)))
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "Usual range ${bandLow.toInt()}–${bandHigh.toInt()} bpm",
                        color = tok.onSurfaceVariant, fontSize = 11.sp,
                    )
                }
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                // Round, don't truncate. The hero above uses "%.0f" (HALF_UP),
                // so with a max of 58.9 the hero said 59 and this said 58 —
                // a headline number larger than the stated maximum.
                Stat("Min", "${kotlin.math.round(real.min()).toInt()} bpm")
                Stat("Avg", "%.0f bpm".format(real.average()))
                Stat("Max", "${kotlin.math.round(real.max()).toInt()} bpm")
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
    val tok = LocalAppTokens.current
    Column {
        Text(label, color = tok.onSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = tok.onSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun HrHistogram(points: List<TimePoint>, bucketSeconds: Int = 120) {
    val tok = LocalAppTokens.current
    val measurer = rememberTextMeasurer()
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
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("HR DISTRIBUTION — 24H", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(2.dp))
            // The series is 2-minute buckets, not raw samples, so "N samples"
            // was counting the wrong thing. Each bucket is a fixed slice of
            // time, which makes MINUTES the honest — and more useful — y-axis:
            // "how long was I in this band", not "how many rows landed here".
            Text("5-bpm bins · time in band", color = tok.onSurfaceDim, fontSize = 10.sp)
            Spacer(Modifier.height(8.dp))
            val perBucketMin = bucketSeconds / 60f
            val mins = bins.map { it.second * perBucketMin }
            Canvas(Modifier.fillMaxWidth().height(150.dp)) {
                val domain = niceDomain(
                    lo = 0f, hi = (mins.maxOrNull() ?: 1f).coerceAtLeast(1f),
                    zeroAnchored = true, targetTicks = 3, minStep = 1f,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 30.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                // Bar heights were unreadable: the tallest bin always touched
                // the top of the box, so a day spent flat at 58 bpm and a day
                // with a broad spread drew the same picture.
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 3) {
                    if (it >= 60f) "%.0fh".format(it / 60f) else "%.0fm".format(it)
                }
                val barW = g.slot(bins.size) * 0.8f
                mins.forEachIndexed { i, m ->
                    if (m <= 0f) return@forEachIndexed
                    drawBar(g, g.xBar(i, bins.size), barW, g.y(m), Vital.HR.accent)
                }
                drawXLabels(g, measurer, tok.onSurfaceDim, buildList {
                    add(0f to "${bins.first().first}")
                    if (bins.size >= 5) {
                        add(0.5f to "${bins[bins.size / 2].first}")
                    }
                    add(1f to "${bins.last().first + 5}")
                })
            }
        }
    }
}

/** Start / middle / end dates for a daily-series x-axis. */
private fun xTicks(rows: List<DailySummary>): List<Pair<Float, String>> {
    if (rows.isEmpty()) return emptyList()
    fun md(iso: String?): String? = runCatching {
        val d = java.time.LocalDate.parse(iso)
        "${d.monthValue}/${d.dayOfMonth}"
    }.getOrNull()
    val out = mutableListOf<Pair<Float, String>>()
    md(rows.first().date)?.let { out += 0f to it }
    if (rows.size >= 5) md(rows[rows.size / 2].date)?.let { out += 0.5f to it }
    if (rows.size >= 2) md(rows.last().date)?.let { out += 1f to it }
    return out
}

@Composable
private fun WeekdayPattern(rows: List<DailySummary>) {
    val tok = LocalAppTokens.current
    val measurer = rememberTextMeasurer()
    val accent = Vital.HR.accent
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
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("RESTING HR · BY WEEKDAY", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val nonNull = byDow.filterNotNull()
            val labels = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
            val todayDow = java.time.LocalDate.now().dayOfWeek.value % 7  // Sun = 0
            val mean = nonNull.average().toFloat()

            // One Canvas for the whole chart. The previous layout put value +
            // bar + day label in a Column inside a fixed-height Row: the
            // tallest bar overflowed the Row, which pushed its day label off
            // the bottom of the card. "Wed" was simply missing from the chart
            // on every range, and the two tallest bars hung below the others'
            // baseline. A single Canvas can't overflow — the bars are drawn
            // into a plot rect that leaves the gutters alone.
            Canvas(Modifier.fillMaxWidth().height(150.dp)) {
                // Scaled against the same nice domain as the trend chart, not
                // against the weekday min. Anchoring the shortest bar at zero
                // height made a 62-vs-71 bpm spread look like a 5x difference.
                val domain = niceDomain(
                    lo = nonNull.min().toFloat(), hi = nonNull.max().toFloat(),
                    targetTicks = 3, padFraction = 0.30f, minStep = 1f,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 26.dp.toPx(), top = 14.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 3) {
                    "%.0f".format(it)
                }
                val slot = g.slot(7)
                val barW = slot * 0.58f
                for (i in 0..6) {
                    val v = byDow[i] ?: continue
                    val cx = g.xBar(i, 7)
                    val isToday = i == todayDow
                    drawBar(
                        g, cx, barW, g.y(v.toFloat()),
                        accent.copy(alpha = if (isToday) 0.95f else 0.45f),
                    )
                    val lay = measurer.measure(
                        "${kotlin.math.round(v).toInt()}",
                        androidx.compose.ui.text.TextStyle(
                            color = if (isToday) tok.onSurface else tok.onSurfaceVariant,
                            fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
                        ),
                    )
                    drawText(lay, topLeft = Offset(
                        cx - lay.size.width / 2f,
                        (g.y(v.toFloat()) - lay.size.height - 2.dp.toPx())
                            .coerceAtLeast(0f),
                    ))
                }
                // No label: drawReferenceLine puts it at the right edge, which
                // is exactly where Saturday's bar value sits. The caption
                // under the chart carries the number instead.
                drawReferenceLine(g, mean, tok.onSurfaceDim)
                // Day labels live in the reserved bottom gutter, so a tall bar
                // can never displace them.
                drawXLabels(g, measurer, tok.onSurfaceDim,
                    labels.indices.map { (it + 0.5f) / 7f to labels[it] })
            }
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(width = 14.dp, height = 1.dp)
                    .background(tok.onSurfaceDim))
                Spacer(Modifier.width(6.dp))
                Text("Average ${kotlin.math.round(mean).toInt()} bpm across this window",
                    color = tok.onSurfaceVariant, fontSize = 11.sp)
            }
        }
    }
}
