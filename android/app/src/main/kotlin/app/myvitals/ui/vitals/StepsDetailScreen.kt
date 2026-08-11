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
import androidx.compose.foundation.lazy.LazyColumn
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.data.JsonCache
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.TimePoint
import app.myvitals.ui.MV
import app.myvitals.ui.common.PullableMetricBox
import com.squareup.moshi.Types
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import app.myvitals.ui.LocalAppTokens

@Composable
fun StepsDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val tok = LocalAppTokens.current
    val context = androidx.compose.ui.platform.LocalContext.current
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var goal by remember { mutableStateOf(10_000) }
    var hourly by remember { mutableStateOf<IntArray?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    // Day selector — scrolls the hourly chart + hero through past days
    // without losing the day-of layout. Default = today.
    var selectedDay by remember { mutableStateOf(LocalDate.now()) }

    val rowsType = Types.newParameterizedType(List::class.java, DailySummary::class.java)
    val hourlyType = IntArray::class.java

    suspend fun loadHourly(day: LocalDate) {
        // Per-day hourly fetch: window = local 00:00 → 23:59 of `day`.
        // Cache keyed by date so revisiting a past day is instant.
        val cacheKey = "steps_detail_hourly_$day"
        JsonCache.read<IntArray>(context, cacheKey, hourlyType)?.let { hourly = it.value }
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val zone = java.time.ZoneId.systemDefault()
            val start = day.atStartOfDay(zone).toInstant().toString()
            val end = day.plusDays(1).atStartOfDay(zone).toInstant().toString()
            val series = withContext(Dispatchers.IO) {
                runCatching { api.stepsSeries(since = start, until = end) }.getOrNull()
            }
            if (series != null) {
                val h = bucketByHour(series.points, day)
                hourly = h
                JsonCache.write(context, cacheKey, hourlyType, h)
            }
        } catch (e: Exception) {
            Timber.w(e, "steps hourly load failed for %s", day)
        }
    }

    suspend fun load(force: Boolean) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            runCatching { api.profile() }.getOrNull()?.let { goal = it.stepsGoal() }
            val since = LocalDate.now().minusDays(29).toString()
            val freshRows = withContext(Dispatchers.IO) { api.summaryRange(since = since) }
            rows = freshRows
            JsonCache.write(context, "steps_detail_rows", rowsType, freshRows)
            loadHourly(selectedDay)
            error = null
            Timber.i("steps detail: %d rows day=%s (force=%s)", rows.size, selectedDay, force)
        } catch (e: Exception) {
            Timber.w(e, "steps detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(Unit) {
        // 1. Read cache → render immediately (no spinner if there's anything)
        JsonCache.read<List<DailySummary>>(context, "steps_detail_rows", rowsType)
            ?.let { rows = it.value; loading = false }
        // 2. Always fetch fresh in parallel — render swaps when it lands.
        load(force = false)
    }
    // Reload hourly whenever the selected day changes.
    LaunchedEffect(selectedDay) {
        if (rows.isNotEmpty()) loadHourly(selectedDay)
    }

    val color = Vital.STEPS.accent
    Column(Modifier.fillMaxSize().background(tok.bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = tok.onSurface)
            }
            Text("Steps", color = tok.onSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        app.myvitals.ui.common.DayNav(
            selected = selectedDay,
            onSelectedChange = { selectedDay = it },
        )
        when {
            loading -> Text("Loading…", color = tok.onSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null && rows.isEmpty() -> Text(error!!, color = tok.red,
                modifier = Modifier.padding(16.dp))
            else -> PullableMetricBox(
                refreshing = refreshing,
                onRefresh = {
                    refreshing = true
                    try { load(force = true) } finally { refreshing = false }
                },
            ) {
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item {
                        // Pick the row matching selectedDay; fall back to
                        // the last row when there's no summary yet.
                        val dayRow = rows.firstOrNull { it.date == selectedDay.toString() }
                            ?: rows.lastOrNull()
                        TodayHero(dayRow, goal, color)
                    }
                    hourly?.let { hr ->
                        if (hr.sum() > 0) item {
                            HourlyColumns(
                                hr, color,
                                isToday = selectedDay == LocalDate.now(),
                            )
                        }
                    }
                    item { DailyColumns(rows, goal, color) }
                    item { StepsStats(rows, goal) }
                }
            }
        }
    }
}

@Composable
private fun TodayHero(today: DailySummary?, goal: Int, color: Color) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TODAY", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            val n = today?.stepsTotal ?: 0
            Text("%,d".format(n), color = tok.onSurface,
                fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
            val pct = (n.toFloat() / goal.toFloat()).coerceAtLeast(0f).coerceAtMost(2f)
            Box(Modifier.fillMaxWidth().height(8.dp)
                .background(color.copy(alpha = 0.15f))) {
                Box(Modifier.fillMaxWidth(fraction = pct.coerceAtMost(1f)).height(8.dp)
                    .background(color))
            }
            Spacer(Modifier.height(4.dp))
            Text("${(pct * 100).toInt()}% of ${"%,d".format(goal)} goal",
                color = tok.onSurfaceDim, fontSize = 11.sp)
        }
    }
}

/** Sum the per-minute series into 24 hour-of-day bins (local TZ),
 *  scoped to the given calendar day so the chart shows "when did I
 *  step on this day". Returns an IntArray of length 24. */
private fun bucketByHour(points: List<TimePoint>, day: LocalDate): IntArray {
    val out = IntArray(24)
    val zone = ZoneId.systemDefault()
    for (p in points) {
        val ldt = runCatching {
            Instant.parse(p.time).atZone(zone).toLocalDateTime()
        }.getOrNull() ?: continue
        if (ldt.toLocalDate() != day) continue
        out[ldt.hour] += p.value.toInt()
    }
    return out
}

@Composable
private fun HourlyColumns(hourly: IntArray, color: Color, isToday: Boolean) {
    val measurer = rememberTextMeasurer()
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text(if (isToday) "TODAY BY HOUR" else "BY HOUR",
                color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            Canvas(Modifier.fillMaxWidth().height(150.dp)) {
                // Zero-anchored: for a count, the bar length IS the quantity,
                // so the axis has to start at zero or the bars lie about
                // ratios. (Physiology charts do the opposite — see niceDomain.)
                val domain = niceDomain(
                    lo = 0f, hi = hourly.max().coerceAtLeast(1).toFloat(),
                    zeroAnchored = true, targetTicks = 3,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 30.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 3) {
                    if (it >= 1000f) "%.0fk".format(it / 1000f) else "%.0f".format(it)
                }
                val barW = g.slot(24) * 0.7f
                for (h in 0 until 24) {
                    val v = hourly[h].toFloat()
                    if (v <= 0f) continue
                    drawBar(g, g.xBar(h, 24), barW, g.y(v), color)
                }
                drawXLabels(g, measurer, tok.onSurfaceDim, listOf(
                    (0.5f / 24f) to "12a", (6.5f / 24f) to "6a",
                    (12.5f / 24f) to "12p", (18.5f / 24f) to "6p",
                    (23.5f / 24f) to "11p",
                ))
            }
        }
    }
}

@Composable
private fun DailyColumns(rows: List<DailySummary>, goal: Int, color: Color) {
    val measurer = rememberTextMeasurer()
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            // Title counts the rows actually rendered. It was hard-coded
            // "LAST 30 DAYS" no matter what the window held, so a short
            // history advertised days it never drew.
            Text("LAST ${rows.size} DAYS", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (rows.isEmpty()) {
                Text("No data.", color = tok.onSurfaceVariant, fontSize = 12.sp); return@Card
            }
            Canvas(Modifier.fillMaxWidth().height(170.dp)) {
                val domain = niceDomain(
                    lo = 0f,
                    hi = (rows.maxOfOrNull { it.stepsTotal ?: 0 } ?: 0)
                        .coerceAtLeast(goal).toFloat(),
                    zeroAnchored = true, targetTicks = 4,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 30.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface, maxLabels = 4) {
                    if (it >= 1000f) "%.0fk".format(it / 1000f) else "%.0f".format(it)
                }
                val barW = (g.slot(rows.size) * 0.72f).coerceAtLeast(1f)
                for ((i, r) in rows.withIndex()) {
                    val v = (r.stepsTotal ?: 0).toFloat()
                    if (v <= 0f) continue
                    drawBar(
                        g, g.xBar(i, rows.size), barW, g.y(v),
                        if (v >= goal) color else color.copy(alpha = 0.45f),
                    )
                }
                drawReferenceLine(g, goal.toFloat(), color, measurer,
                    "goal ${"%,d".format(goal)}")
                drawXLabels(g, measurer, tok.onSurfaceDim, buildList {
                    rows.firstOrNull()?.date?.let { add(0f to shortDay(it)) }
                    if (rows.size >= 5) rows[rows.size / 2].date
                        ?.let { add(0.5f to shortDay(it)) }
                    rows.lastOrNull()?.date?.let { add(1f to shortDay(it)) }
                })
            }
        }
    }
}

@Composable
private fun StepsStats(rows: List<DailySummary>, goal: Int) {
    val tok = LocalAppTokens.current
    val totals = rows.mapNotNull { it.stepsTotal }
    val total = totals.sum()
    val avg = if (totals.isNotEmpty()) totals.average() else 0.0
    val daysHit = totals.count { it >= goal }
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("STATS", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                StatPair("Total", "%,d".format(total))
                StatPair("Daily avg", "%,.0f".format(avg))
                StatPair("Days ≥ goal", "$daysHit/${rows.size}")
            }
        }
    }
}

@Composable
private fun StatPair(label: String, value: String) {
    val tok = LocalAppTokens.current
    Column {
        Text(label, color = tok.onSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = tok.onSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun shortDay(iso: String): String =
    runCatching {
        val d = LocalDate.parse(iso)
        DateTimeFormatter.ofPattern("M/d").format(d)
    }.getOrDefault(iso)
