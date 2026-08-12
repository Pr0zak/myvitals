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
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.drawText
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.SleepNight
import app.myvitals.sync.SleepRawSegment
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import app.myvitals.ui.LocalAppTokens

private val STAGE_COLORS = mapOf(
    "deep" to Color(0xFF1E40AF),
    "rem" to Color(0xFFA78BFA),
    "light" to Color(0xFF60A5FA),
    "awake" to Color(0xFFF97316),
    "wake" to Color(0xFFF97316),
    // Fitbit's CLASSIC sleep levels (asleep / restless / awake), as opposed to
    // its stages (light / deep / rem / wake). Both vocabularies are in the
    // database — 5.3k "asleep" and 5.1k "restless" segments — and neither had
    // a colour or a hypnogram row, so a night recorded in classic levels drew
    // an almost empty hypnogram above a stage-breakdown bar showing a full
    // night's sleep. Two charts on one screen disagreeing.
    "asleep" to Color(0xFF3B82F6),
    "restless" to Color(0xFF93C5FD),
    "out_of_bed" to Color(0xFF94A3B8),
    "unmeasurable" to Color(0xFF64748B),
    "unknown" to Color(0xFF64748B),
)

/** Spellings of the same thing. `wake` had a colour but no row, so 1.8k
 *  segments were drawn as nothing at all. */
private val STAGE_SYNONYMS = mapOf("wake" to "awake")

private fun canonicalStage(raw: String): String {
    val s = raw.lowercase()
    return STAGE_SYNONYMS[s] ?: s
}

/** Vertical order (top → bottom), shallowest first. Rows are chosen from the
 *  stages actually present, so a classic-levels night shows
 *  awake/restless/asleep and a staged night shows awake/rem/light/deep,
 *  instead of a fixed four that silently discarded 39% of all segments. */
private val HYPNO_ORDER = listOf(
    "awake", "restless", "rem", "light", "asleep", "deep",
    "out_of_bed", "unmeasurable", "unknown",
)

@Composable
fun SleepDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val tok = LocalAppTokens.current
    val context = androidx.compose.ui.platform.LocalContext.current
    var nights by remember { mutableStateOf<List<SleepNight>>(emptyList()) }
    var selectedRaw by remember { mutableStateOf<List<SleepRawSegment>>(emptyList()) }
    var goalH by remember { mutableStateOf(8.0) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    // Night picker — defaults to today (the most-recent night). Tapping
    // back/forward scrolls through past nights' hypnogram + stats.
    var selectedDay by remember { mutableStateOf(LocalDate.now()) }

    val nightsType = com.squareup.moshi.Types.newParameterizedType(
        List::class.java, SleepNight::class.java,
    )
    val rawType = com.squareup.moshi.Types.newParameterizedType(
        List::class.java, SleepRawSegment::class.java,
    )

    // Match nights list to the selected day. Sleep that *ended* on this
    // date is what the user expects to see (e.g. today = last night).
    fun nightForDay(day: LocalDate): SleepNight? =
        nights.firstOrNull { it.date == day.toString() }
            ?: nights.lastOrNull()

    suspend fun fetchRawForDay(day: LocalDate) {
        // Pull raw stage segments scoped to the night ending on `day`.
        // Window: 18:00 prev-day → 14:00 day (matches the backend's
        // canonical "night ending on" boundary).
        val zone = ZoneId.systemDefault()
        val cacheKey = "sleep_detail_raw_$day"
        app.myvitals.data.JsonCache.read<List<SleepRawSegment>>(
            context, cacheKey, rawType,
        )?.let { selectedRaw = it.value }
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val start = day.minusDays(1).atTime(18, 0).atZone(zone).toInstant().toString()
            val end = day.atTime(14, 0).atZone(zone).toInstant().toString()
            val r = withContext(Dispatchers.IO) {
                api.sleepRaw(since = start, until = end)
            }
            selectedRaw = r
            app.myvitals.data.JsonCache.write(context, cacheKey, rawType, r)
        } catch (e: Exception) {
            Timber.w(e, "sleep raw load failed for %s", day)
        }
    }

    suspend fun fetch() {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            runCatching { api.profile() }.getOrNull()?.let { goalH = it.sleepGoalH() }
            val since = LocalDate.now().minusDays(13).toString()
            val n = withContext(Dispatchers.IO) { api.sleepRange(since = since) }
            nights = n
            app.myvitals.data.JsonCache.write(context, "sleep_detail_nights", nightsType, n)
            fetchRawForDay(selectedDay)
            error = null
            Timber.i("sleep detail: %d nights, %d raw segments for %s",
                nights.size, selectedRaw.size, selectedDay)
        } catch (e: Exception) {
            Timber.w(e, "sleep detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(Unit) {
        app.myvitals.data.JsonCache.read<List<SleepNight>>(context, "sleep_detail_nights", nightsType)
            ?.let { nights = it.value; loading = false }
        fetch()
    }
    // Refetch raw segments whenever the picked night changes.
    LaunchedEffect(selectedDay) {
        if (nights.isNotEmpty()) fetchRawForDay(selectedDay)
    }

    Column(Modifier.fillMaxSize().background(tok.bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = tok.onSurface)
            }
            Text("Sleep", color = tok.onSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        app.myvitals.ui.common.DayNav(
            selected = selectedDay,
            onSelectedChange = { selectedDay = it },
        )
        when {
            loading -> Text("Loading…", color = tok.onSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null && nights.isEmpty() ->
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
                    val isToday = selectedDay == LocalDate.now()
                    item { LastNightHero(nightForDay(selectedDay), isToday = isToday) }
                    item { Hypnogram(selectedRaw) }
                    item { StageBreakdownChart(nights.takeLast(14)) }
                    item { DurationTrend(nights.takeLast(14), goalH) }
                    item {
                        StageLegend(
                            nights.flatMap { n -> n.stages.map { canonicalStage(it.stage) } }
                                .toSet(),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LastNightHero(n: SleepNight?, isToday: Boolean = true) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text(if (isToday) "LAST NIGHT" else "NIGHT OF " + (n?.date ?: "—"),
                color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            if (n == null) {
                Text("—", color = tok.onSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                return@Card
            }
            val totalH = n.totalS / 3600
            val totalM = (n.totalS % 3600) / 60
            Text("${totalH}h ${totalM}m", color = tok.onSurface,
                fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
            Text(formatStartEnd(n), color = tok.onSurfaceVariant, fontSize = 12.sp)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                val byStage = n.stages.associate { it.stage to it.durationS }
                for (st in HYPNO_ORDER) {
                    val s = byStage[st] ?: continue
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(8.dp)
                                .clip(RoundedCornerShape(2.dp))
                                .background(STAGE_COLORS[st] ?: tok.onSurfaceDim))
                            Spacer(Modifier.width(4.dp))
                            Text(st.replaceFirstChar { it.titlecase() },
                                color = tok.onSurfaceDim, fontSize = 10.sp,
                                fontWeight = FontWeight.Bold)
                        }
                        Text("${s / 60}m", color = tok.onSurface, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}

@Composable
private fun Hypnogram(segments: List<SleepRawSegment>) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("HYPNOGRAM", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (segments.isEmpty()) {
                Text("No stage detail synced for this night yet.",
                    color = tok.onSurfaceVariant, fontSize = 12.sp)
                return@Card
            }
            val measurer = androidx.compose.ui.text.rememberTextMeasurer()
            val parsed = remember(segments) {
                segments.mapNotNull { s ->
                    val t = runCatching { Instant.parse(s.time).toEpochMilli() }
                        .getOrNull() ?: return@mapNotNull null
                    Triple(t, t + s.durationS * 1000L, canonicalStage(s.stage))
                }
            }
            // Only rows that actually occur tonight, so a classic-levels night
            // isn't padded with four empty stage lanes (and vice versa).
            val rows = remember(parsed) {
                val present = parsed.mapTo(HashSet()) { it.third }
                HYPNO_ORDER.filter { it in present }
                    .ifEmpty { HYPNO_ORDER.take(1) }
            }
            val tStart = parsed.minOfOrNull { it.first } ?: return@Card
            val tEnd = parsed.maxOfOrNull { it.second } ?: return@Card
            val chartH = (rows.size * 30).coerceAtLeast(90).dp
            Canvas(Modifier.fillMaxWidth().height(chartH)) {
                // Labels used to be a Column laid OVER the canvas, printing on
                // top of the first ~40 minutes of every night. They get their
                // own gutter now.
                val gutter = 44.dp.toPx()
                val axisH = 14.dp.toPx()
                val plotW = size.width - gutter
                val plotH = size.height - axisH
                val span = (tEnd - tStart).toFloat().coerceAtLeast(1f)
                val rowH = plotH / rows.size
                val labelStyle = androidx.compose.ui.text.TextStyle(
                    color = tok.onSurfaceDim, fontSize = 9.sp,
                    fontWeight = FontWeight.Bold,
                )
                for ((i, st) in rows.withIndex()) {
                    val y = i * rowH
                    drawLine(
                        color = tok.onSurfaceDim.copy(alpha = 0.14f),
                        start = Offset(gutter, y + rowH), end = Offset(size.width, y + rowH),
                        strokeWidth = 0.7.dp.toPx(),
                    )
                    val lay = measurer.measure(st, labelStyle)
                    drawText(lay, topLeft = Offset(
                        (gutter - 6.dp.toPx() - lay.size.width).coerceAtLeast(0f),
                        y + (rowH - lay.size.height) / 2f,
                    ))
                }
                for ((s, e, stage) in parsed) {
                    val idx = rows.indexOf(stage).takeIf { it >= 0 } ?: continue
                    val x0 = gutter + ((s - tStart).toFloat() / span) * plotW
                    val x1 = gutter + ((e - tStart).toFloat() / span) * plotW
                    val y0 = idx * rowH + rowH * 0.18f
                    drawRect(
                        color = STAGE_COLORS[stage] ?: tok.onSurfaceDim,
                        topLeft = Offset(x0, y0),
                        size = Size((x1 - x0).coerceAtLeast(1f), rowH * 0.64f),
                    )
                }
                // Hourly ticks rather than three rounded labels, so you can
                // actually read WHEN a stage happened.
                val axisStyle = androidx.compose.ui.text.TextStyle(
                    color = tok.onSurfaceDim, fontSize = 9.sp,
                )
                val hourMs = 3_600_000L
                val zoneId = java.time.ZoneId.systemDefault()
                var tick = java.time.Instant.ofEpochMilli(tStart).atZone(zoneId)
                    .withMinute(0).withSecond(0).withNano(0)
                    .plusHours(1).toInstant().toEpochMilli()
                val stepH = if (tEnd - tStart > 8 * hourMs) 2L else 1L
                while (tick <= tEnd) {
                    val x = gutter + ((tick - tStart).toFloat() / span) * plotW
                    drawLine(
                        color = tok.onSurfaceDim.copy(alpha = 0.10f),
                        start = Offset(x, 0f), end = Offset(x, plotH),
                        strokeWidth = 0.7.dp.toPx(),
                    )
                    val lay = measurer.measure(formatLocalHour(tick), axisStyle)
                    drawText(lay, topLeft = Offset(
                        (x - lay.size.width / 2f).coerceIn(0f, size.width - lay.size.width),
                        plotH + 2.dp.toPx(),
                    ))
                    tick += stepH * hourMs
                }
            }
        }
    }
}

@Composable
private fun StageBreakdownChart(nights: List<SleepNight>) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            // Count NIGHTS, not sessions. An afternoon nap is a sleep session
            // but it is not a night, and counting it both inflated this number
            // and dropped a 40-minute bar into a chart of full nights.
            val nightCount = nights.count { it.kind != "nap" }
            val napCount = nights.size - nightCount
            Text(
                "STAGE BREAKDOWN — $nightCount NIGHTS" +
                    if (napCount > 0) " + $napCount NAP${if (napCount > 1) "S" else ""}" else "",
                color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (nights.isEmpty()) {
                Text("No data.", color = tok.onSurfaceVariant, fontSize = 12.sp)
                return@Card
            }
            val measurer = androidx.compose.ui.text.rememberTextMeasurer()
            // Stack order, deepest at the bottom. Built from the canonical
            // vocabulary so Fitbit's classic levels (asleep / restless) are
            // stacked too — the old hard-coded list omitted them, so a night
            // recorded that way drew an almost-empty bar.
            val stackOrder = listOf(
                "deep", "asleep", "light", "rem", "restless", "awake",
                "out_of_bed", "unmeasurable", "unknown",
            )
            // Scale by the STACKED height, not by totalS. totalS is asleep-only
            // on most sources while the stack includes awake, so a restless
            // night's bar overflowed the top of the box.
            val stackTotals = nights.map { n ->
                n.stages.sumOf { it.durationS }.toFloat() / 3600f
            }.ifEmpty { listOf(1f) }
            Canvas(Modifier.fillMaxWidth().height(170.dp)) {
                val domain = niceDomain(
                    lo = 0f, hi = (stackTotals.maxOrNull() ?: 1f).coerceAtLeast(1f),
                    zeroAnchored = true, targetTicks = 3, minStep = 1f,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 26.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 3) {
                    "%.0fh".format(it)
                }
                // Bars sit on the same continuous day axis as the trend line:
                // a missing night leaves an empty slot instead of pulling the
                // next night's bar up against the previous one.
                val slots = onDayAxis(nights)
                val barW = g.slot(slots.size) * 0.74f
                for ((i, n) in slots.withIndex()) {
                    if (n == null) continue
                    val cx = g.xBar(i, slots.size)
                    var acc = 0f
                    for (st in stackOrder) {
                        val secs = n.stages
                            .firstOrNull { canonicalStage(it.stage) == st }?.durationS ?: continue
                        val hrs = secs.toFloat() / 3600f
                        val yTop = g.y(acc + hrs)
                        val yBot = g.y(acc)
                        drawRect(
                            color = STAGE_COLORS[st] ?: tok.onSurfaceDim,
                            topLeft = Offset(cx - barW / 2f, yTop),
                            size = Size(barW, (yBot - yTop).coerceAtLeast(0f)),
                        )
                        acc += hrs
                    }
                }
                // Labels placed under the bars they name. The old strip used
                // SpaceBetween over a FILTERED subset, so the dates spread
                // evenly across the width and sat under the wrong bars.
                drawXLabels(g, measurer, tok.onSurfaceDim, buildList {
                    val n = slots.size
                    slots.firstOrNull { it != null }?.let {
                        add((0.5f / n) to shortDate(it.date))
                    }
                    if (n >= 5) slots[n / 2]?.let {
                        add(((n / 2 + 0.5f) / n) to shortDate(it.date))
                    }
                    if (n >= 2) slots.lastOrNull { it != null }?.let {
                        add(((n - 0.5f) / n) to shortDate(it.date))
                    }
                })
            }
        }
    }
}

@Composable
private fun DurationTrend(nights: List<SleepNight>, goalH: Double) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("DURATION", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(4.dp))
            // Nights only. A 45-minute nap averaged in with eight-hour nights
            // pulled the headline down and made "Min" the nap's length rather
            // than that of the shortest night. Explains a 5.6h average over a
            // window whose bars are mostly 7-8h.
            val actualNights = nights.filter { it.kind != "nap" }
            if (actualNights.isEmpty()) {
                Text("—", color = tok.onSurface, fontSize = 16.sp); return@Card
            }
            val avgH = actualNights.map { it.totalS }.average() / 3600.0
            val minN = actualNights.minByOrNull { it.totalS }
            val maxN = actualNights.maxByOrNull { it.totalS }
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Avg", "%.1f h".format(avgH))
                if (minN != null) Stat("Min", "%.1f h".format(minN.totalS / 3600.0))
                if (maxN != null) Stat("Max", "%.1f h".format(maxN.totalS / 3600.0))
                Stat("Goal", "%.1f h".format(goalH))
            }
            Spacer(Modifier.height(8.dp))
            // Not a stage colour: drawn in "light sleep" blue directly above a
            // legend mapping that blue to light sleep, this line read as a
            // light-sleep series rather than total duration.
            Box(Modifier.fillMaxWidth().height(96.dp)) {
                SleepDurationLine(actualNights, goalH = goalH.toFloat(),
                    color = Vital.SLEEP.accent)
            }
        }
    }
}

/**
 * Expand a sparse night list onto a CONTINUOUS day axis, one slot per calendar
 * day from the first night to the last, with null where no night was recorded.
 *
 * Both sleep charts placed points and bars by LIST INDEX, so a week with two
 * missing nights closed the gap up: the nights either side rendered as
 * neighbours and the line drew a smooth slope across days that have no data.
 * A gap in the record is not a trend.
 */
private fun onDayAxis(nights: List<SleepNight>): List<SleepNight?> {
    val byDate = nights.associateBy { it.date }
    val days = nights.mapNotNull { runCatching { java.time.LocalDate.parse(it.date) }.getOrNull() }
    val first = days.minOrNull() ?: return nights
    val last = days.maxOrNull() ?: return nights
    val span = java.time.temporal.ChronoUnit.DAYS.between(first, last).toInt()
    // Guard against a pathological range blowing the chart up.
    if (span < 0 || span > 400) return nights
    return (0..span).map { byDate[first.plusDays(it.toLong()).toString()] }
}

@Composable
private fun SleepDurationLine(nights: List<SleepNight>, goalH: Float, color: Color) {
    val tok = LocalAppTokens.current
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    Canvas(Modifier.fillMaxSize()) {
        if (nights.size < 2) return@Canvas
        val slots = onDayAxis(nights)
        val ys = slots.map { it?.let { n -> n.totalS.toFloat() / 3600f } }
        val real = ys.filterNotNull()
        if (real.isEmpty()) return@Canvas
        // The goal has to be INSIDE the domain or it is drawn off-canvas. The
        // old scale was the data's own min..max, so on any window where every
        // night fell short of the goal the goal line was painted above the top
        // edge and vanished — exactly the stretch where you want to see how
        // far short you are. The axis was also absent entirely, so a 20-minute
        // wobble filled the full height and looked like a collapse.
        // Zero-anchored: a duration is a count, and padding below the minimum
        // produced a "-5h" gridline — there is no such thing as negative sleep.
        val domain = niceDomain(
            lo = 0f, hi = maxOf(real.max(), goalH),
            targetTicks = 3, minStep = 1f, zeroAnchored = true,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 24.dp.toPx(), top = 6.dp.toPx(),
            right = 4.dp.toPx(), bottom = 4.dp.toPx(),
        ))
        drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 3) {
            "%.0fh".format(it)
        }
        // Goal line — sourced from /profile.extra.sleep_goal_h.
        drawReferenceLine(g, goalH, color, measurer, "goal ${"%.1f".format(goalH)}h")
        val path = androidx.compose.ui.graphics.Path()
        var prev: Offset? = null
        var prevIdx = -1
        for ((i, y) in ys.withIndex()) {
            if (y == null) continue
            val p = Offset(g.x(i, ys.size), g.y(y))
            val p0 = prev
            when {
                p0 == null -> path.moveTo(p.x, p.y)
                // A night with no record sits between these two.
                i - prevIdx > 1 -> { drawGapBridge(p0, p, color); path.moveTo(p.x, p.y) }
                else -> path.lineTo(p.x, p.y)
            }
            drawCircle(color = color, radius = 2.dp.toPx(), center = p)
            prev = p; prevIdx = i
        }
        drawPath(path = path, color = color, style = Stroke(
            width = 2.dp.toPx(),
            cap = androidx.compose.ui.graphics.StrokeCap.Round,
            join = androidx.compose.ui.graphics.StrokeJoin.Round,
        ))
    }
}

@Composable
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
private fun StageLegend(present: Set<String> = emptySet()) {
    val tok = LocalAppTokens.current
    // Only the stages this window actually contains, and wrapping. The order
    // grew from four entries to nine to cover both Fitbit vocabularies, which
    // a single non-wrapping Row silently ran off the right edge of the card.
    val shown = HYPNO_ORDER.filter { present.isEmpty() || it in present }
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        androidx.compose.foundation.layout.FlowRow(
            Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            for (st in shown) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(STAGE_COLORS[st] ?: tok.onSurfaceDim))
                    Spacer(Modifier.width(4.dp))
                    Text(st, color = tok.onSurface, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    val tok = LocalAppTokens.current
    Column {
        Text(label, color = tok.onSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = tok.onSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun formatStartEnd(n: SleepNight): String {
    val zone = ZoneId.systemDefault()
    val s = n.start?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() }
    val e = n.end?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() }
    val fmt = DateTimeFormatter.ofPattern("h:mm a")
    return when {
        s == null || e == null -> n.date
        else -> "${fmt.format(s)} → ${fmt.format(e)}"
    }
}

private fun formatLocalHour(epochMs: Long): String {
    val zdt = Instant.ofEpochMilli(epochMs).atZone(ZoneId.systemDefault())
    return DateTimeFormatter.ofPattern("h a").format(zdt).lowercase()
}

private fun shortDate(iso: String): String =
    runCatching {
        val d = LocalDate.parse(iso)
        DateTimeFormatter.ofPattern("M/d").format(d)
    }.getOrDefault(iso)
