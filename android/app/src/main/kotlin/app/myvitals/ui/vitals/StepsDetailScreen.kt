package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.RangeStats
import app.myvitals.sync.StepsRangeStats
import app.myvitals.sync.VitalTile
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonRing
import app.myvitals.ui.neon.NeonRingCaption
import app.myvitals.ui.neon.NeonScreen
import com.squareup.moshi.Types
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Steps detail (UI-4). Neon scaffold; the hero is the selected day's count,
 * the server's verdict chip, a goal ring against THAT day's own target and
 * the day's hourly bars. Below: the window's stats (server
 * `/summary/range/stats`, rendered verbatim), the daily bars and the
 * weekday pattern.
 *
 * Nothing here adds, averages or buckets. The hourly bins, the totals, the
 * average and the goal-day count used to be computed in this file and,
 * separately, in Steps.vue — two formulas for the same number.
 */
@Composable
fun StepsDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var stats by remember { mutableStateOf<RangeStats?>(null) }
    var tile by remember { mutableStateOf<VitalTile?>(null) }
    var hourly by remember { mutableStateOf<List<Int>?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var selectedDay by remember { mutableStateOf(LocalDate.now()) }

    val rowsType = Types.newParameterizedType(List::class.java, DailySummary::class.java)
    val hourlyType = Types.newParameterizedType(List::class.java, Integer::class.java)

    suspend fun loadHourly(day: LocalDate) {
        val cacheKey = "steps_detail_hourly_v2_$day"
        hourly = JsonCache.read<List<Int>>(context, cacheKey, hourlyType)?.value
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val zone = ZoneId.systemDefault()
            val start = day.atStartOfDay(zone).toInstant().toString()
            val end = day.plusDays(1).atStartOfDay(zone).toInstant().toString()
            val series = withContext(Dispatchers.IO) { api.stepsSeries(since = start, until = end) }
            hourly = series.hourly
            series.hourly?.let { JsonCache.write(context, cacheKey, hourlyType, it) }
        } catch (e: Exception) {
            Timber.w(e, "steps hourly load failed for %s", day)
        }
    }

    suspend fun load() {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val today = LocalDate.now()
            val since = today.minusDays(29).toString()
            coroutineScope {
                val rowsD = async(Dispatchers.IO) { api.summaryRange(since = since) }
                val statsD = async(Dispatchers.IO) {
                    runCatching { api.summaryRangeStats(since = since, until = today.toString()) }
                        .getOrNull()
                }
                val tileD = async(Dispatchers.IO) {
                    runCatching { api.summaryTiles().tiles.firstOrNull { it.key == "steps" } }
                        .getOrNull()
                }
                rows = rowsD.await()
                JsonCache.write(context, "steps_detail_rows", rowsType, rows)
                statsD.await()?.let {
                    stats = it
                    JsonCache.write(context, "steps_detail_stats", RangeStats::class.java, it)
                }
                tile = tileD.await()
            }
            loadHourly(selectedDay)
            error = null
        } catch (e: Exception) {
            Timber.w(e, "steps detail load failed")
            error = e.message?.take(160) ?: "Couldn't reach the backend."
        } finally { loading = false }
    }

    LaunchedEffect(Unit) {
        JsonCache.read<List<DailySummary>>(context, "steps_detail_rows", rowsType)
            ?.let { rows = it.value; loading = false }
        JsonCache.read<RangeStats>(context, "steps_detail_stats", RangeStats::class.java)
            ?.let { stats = it.value }
        load()
    }
    LaunchedEffect(selectedDay) { if (rows.isNotEmpty()) loadHourly(selectedDay) }

    StepsDetailContent(
        rows = rows, stats = stats?.steps, tile = tile, hourly = hourly,
        selectedDay = selectedDay, today = LocalDate.now(),
        loading = loading, refreshing = refreshing, error = error,
        onBack = onBack,
        onRefresh = {
            scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
        dayNav = {
            app.myvitals.ui.common.DayNav(
                selected = selectedDay, onSelectedChange = { selectedDay = it },
            )
        },
    )
}

/**
 * Stateless Steps detail. [rows] empty with [loading] = cold load (skeleton);
 * an [error] with nothing cached is a banner, with something cached it is a
 * banner ABOVE the cached content, never instead of it.
 */
@Composable
fun StepsDetailContent(
    rows: List<DailySummary>,
    stats: StepsRangeStats?,
    tile: VitalTile?,
    hourly: List<Int>?,
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
    val accent = Vital.STEPS.accent
    NeonScreen(
        title = "Steps",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
        headerTrailing = { DetailTitleIcon(Vital.STEPS) },
    ) {
        dayNav()
        Spacer(Modifier.height(6.dp))
        val hasContent = rows.isNotEmpty() || stats != null
        if (!hasContent) {
            if (error != null && !loading) NeonErrorBanner(error, title = "Couldn't load steps") { onRefresh() }
            else DetailSkeleton(accent)
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        if (error != null) {
            NeonErrorBanner("Showing your last saved copy. $error", title = "Couldn't refresh") { onRefresh() }
        }

        // No fallback to the most recent row: a day with no summary is shown
        // as a day with no data, not as some other day's count.
        val dayRow = rows.firstOrNull { it.date == selectedDay.toString() }
        val isToday = selectedDay == today
        val goal = dayRow?.stepsGoal ?: tile?.target?.toInt()
        StepsHero(dayRow, goal, if (isToday) tile else null, hourly, selectedDay, isToday, accent)

        DetailStatRow(
            listOf(
                stats?.avg?.let { "%,d".format(it) } to "Daily avg",
                stats?.let { "${it.goalDays}/${it.daysWithData}" } to "Days ≥ goal",
                stats?.total?.let { compactCount(it) } to "Total",
            ),
            accentFirst = accent,
        )

        DetailCard(if (rows.size == 1) "Last day" else "Last ${rows.size} days") {
            DailyStepsBars(rows, accent)
        }
        stats?.weekdayMeans?.takeIf { w -> w.any { it.mean != null } }?.let { wm ->
            DetailCard("Weekday pattern", subtitle = "Average steps on each weekday in this window") {
                WeekdayBars(wm.map { it.dow to it.mean }, accent, format = { compactCount(it.toInt()) })
            }
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun StepsHero(
    row: DailySummary?,
    goal: Int?,
    todayTile: VitalTile?,
    hourly: List<Int>?,
    day: LocalDate,
    isToday: Boolean,
    accent: Color,
) {
    NeonHeroCard(accent) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                NeonEyebrow(
                    if (isToday) "Today"
                    else day.format(DateTimeFormatter.ofPattern("EEE MMM d")),
                    Modifier.padding(top = 0.dp),
                )
                val n = row?.stepsTotal
                NeonNumber(n?.let { "%,d".format(it) } ?: "—", color = accent, size = 52)
                Text(
                    when {
                        n == null -> "No step data for this day"
                        goal != null -> "of ${"%,d".format(goal)} goal"
                        else -> "steps"
                    },
                    color = NeonMV.Muted, fontSize = 12.sp,
                )
                Spacer(Modifier.height(8.dp))
                // The server's own words for today's count; a past day has no
                // verdict endpoint, so it has no chip rather than a local one.
                DetailStatusChip(todayTile?.status, todayTile?.statusReason)
            }
            if (goal != null && goal > 0) {
                NeonRing(
                    // Geometry only — how far round to draw. The figure the
                    // user reads is the server's status_reason above.
                    fraction = ((row?.stepsTotal ?: 0).toFloat() / goal).coerceIn(0f, 1f),
                    color = accent, size = 96.dp, stroke = 9.dp,
                ) {
                    NeonNumber(compactCount(goal), size = 16)
                    NeonRingCaption("goal")
                }
            }
        }
        Spacer(Modifier.height(14.dp))
        NeonEyebrow(if (isToday) "Today by hour" else "By hour", Modifier.padding(top = 0.dp))
        if (hourly == null || hourly.all { it == 0 }) {
            DetailNote(if (row?.stepsTotal == null) "Nothing recorded." else "No hourly detail synced for this day.")
        } else {
            HourlyStepBars(hourly, accent)
        }
    }
}

@Composable
private fun HourlyStepBars(hourly: List<Int>, color: Color) {
    val measurer = rememberTextMeasurer()
    Canvas(Modifier.fillMaxWidth().height(130.dp)) {
        // Zero-anchored: for a count the bar length IS the quantity.
        val domain = niceDomain(
            lo = 0f, hi = (hourly.maxOrNull() ?: 1).coerceAtLeast(1).toFloat(),
            zeroAnchored = true, targetTicks = 3, minStep = 1f,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 30.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { compactCount(it.toInt()) }
        val barW = g.slot(24) * 0.7f
        for (h in 0 until minOf(24, hourly.size)) {
            val v = hourly[h].toFloat()
            if (v <= 0f) continue
            drawBar(g, g.xBar(h, 24), barW, g.y(v), color)
        }
        drawXLabels(g, measurer, NeonMV.Muted, listOf(
            (0.5f / 24f) to "12a", (6.5f / 24f) to "6a", (12.5f / 24f) to "12p",
            (18.5f / 24f) to "6p", (23.5f / 24f) to "11p",
        ))
    }
}

@Composable
private fun DailyStepsBars(rows: List<DailySummary>, color: Color) {
    val measurer = rememberTextMeasurer()
    if (rows.isEmpty()) { DetailNote("No data."); return }
    val lineGoal = rows.lastOrNull()?.stepsGoal
    Canvas(Modifier.fillMaxWidth().height(170.dp)) {
        val domain = niceDomain(
            lo = 0f,
            hi = (rows.maxOfOrNull { it.stepsTotal ?: 0 } ?: 0).coerceAtLeast(lineGoal ?: 1).toFloat(),
            zeroAnchored = true, targetTicks = 4, minStep = 1f,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 30.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 4) { compactCount(it.toInt()) }
        val barW = (g.slot(rows.size) * 0.72f).coerceAtLeast(1f)
        for ((i, r) in rows.withIndex()) {
            val v = (r.stepsTotal ?: 0).toFloat()
            if (v <= 0f) continue
            // Each bar against its OWN day's target (UX-D10). Under-goal days
            // sit in the Track colour rather than a faded accent, so a met
            // day is the only thing lit.
            val hit = r.stepsGoal != null && v >= r.stepsGoal
            drawBar(g, g.xBar(i, rows.size), barW, g.y(v), if (hit) color else NeonMV.Track)
        }
        lineGoal?.let {
            drawReferenceLine(g, it.toFloat(), NeonMV.Ink, measurer, "goal ${"%,d".format(it)}")
        }
        drawXLabels(g, measurer, NeonMV.Muted, buildList {
            rows.firstOrNull()?.date?.let { add(0f to detailMd(it)) }
            if (rows.size >= 5) rows[rows.size / 2].date.let { add(0.5f to detailMd(it)) }
            rows.lastOrNull()?.date?.let { add(1f to detailMd(it)) }
        })
    }
    Spacer(Modifier.height(8.dp))
    DetailLegend(listOf(color to "goal met", NeonMV.Track to "under goal"))
}

/** Seven server-computed weekday means as bars; a null mean is a gap. */
@Composable
internal fun WeekdayBars(
    means: List<Pair<String, Double?>>,
    color: Color,
    zeroAnchored: Boolean = true,
    format: (Double) -> String,
) {
    val measurer = rememberTextMeasurer()
    val vals = means.mapNotNull { it.second }
    if (vals.isEmpty()) return
    Canvas(Modifier.fillMaxWidth().height(140.dp)) {
        val domain = niceDomain(
            lo = if (zeroAnchored) 0f else vals.min().toFloat(), hi = vals.max().toFloat(),
            zeroAnchored = zeroAnchored, targetTicks = 3,
            padFraction = if (zeroAnchored) 0.12f else 0.30f, minStep = 1f,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 30.dp.toPx(), top = 14.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { format(it.toDouble()) }
        val barW = g.slot(7) * 0.58f
        for ((i, p) in means.withIndex()) {
            val v = p.second ?: continue
            drawBar(g, g.xBar(i, 7), barW, g.y(v.toFloat()), color.copy(alpha = 0.85f))
        }
        drawXLabels(g, measurer, NeonMV.Muted, means.indices.map { (it + 0.5f) / 7f to means[it].first })
    }
}

/** 12,345 → "12.3k"; small numbers stay whole. */
internal fun compactCount(n: Int): String = when {
    n >= 100_000 -> "%.0fk".format(n / 1000.0)
    n >= 1000 -> "%.1fk".format(n / 1000.0).replace(".0k", "k")
    else -> n.toString()
}

internal fun detailMd(iso: String): String =
    runCatching { DateTimeFormatter.ofPattern("M/d").format(LocalDate.parse(iso)) }.getOrDefault(iso)
