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

@Composable
fun StepsDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
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
                val h = bucketByHour(series.points)
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

    val color = Vital.STEPS.color
    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Text("Steps", color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        app.myvitals.ui.common.DayNav(
            selected = selectedDay,
            onSelectedChange = { selectedDay = it },
        )
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null && rows.isEmpty() -> Text(error!!, color = MV.Red,
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
                        if (hr.sum() > 0) item { HourlyColumns(hr, color) }
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
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TODAY", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            val n = today?.stepsTotal ?: 0
            Text("%,d".format(n), color = MV.OnSurface,
                fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
            val pct = (n.toFloat() / goal.toFloat()).coerceAtLeast(0f).coerceAtMost(2f)
            Box(Modifier.fillMaxWidth().height(8.dp)
                .background(color.copy(alpha = 0.15f))) {
                Box(Modifier.fillMaxWidth(fraction = pct.coerceAtMost(1f)).height(8.dp)
                    .background(color))
            }
            Spacer(Modifier.height(4.dp))
            Text("${(pct * 100).toInt()}% of ${"%,d".format(goal)} goal",
                color = MV.OnSurfaceDim, fontSize = 11.sp)
        }
    }
}

/** Sum the per-minute series into 24 hour-of-day bins (local TZ),
 *  scoped to TODAY so we show "when did I step today" rather than a
 *  rolling 24h. Returns an IntArray of length 24. */
private fun bucketByHour(points: List<TimePoint>): IntArray {
    val out = IntArray(24)
    val zone = ZoneId.systemDefault()
    val today = LocalDate.now(zone)
    for (p in points) {
        val ldt = runCatching {
            Instant.parse(p.time).atZone(zone).toLocalDateTime()
        }.getOrNull() ?: continue
        if (ldt.toLocalDate() != today) continue
        out[ldt.hour] += p.value.toInt()
    }
    return out
}

@Composable
private fun HourlyColumns(hourly: IntArray, color: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TODAY BY HOUR", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val maxV = (hourly.max().coerceAtLeast(1)).toFloat()
            Box(Modifier.fillMaxWidth().height(120.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val gap = 1.5.dp.toPx()
                    val barW = (size.width - gap * 23) / 24f
                    for (h in 0 until 24) {
                        val v = hourly[h].toFloat()
                        val barH = (v / maxV) * size.height
                        drawRect(
                            color = if (v > 0) color else color.copy(alpha = 0.18f),
                            topLeft = Offset(h * (barW + gap), size.height - barH),
                            size = Size(barW, barH.coerceAtLeast(1f)),
                        )
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("00", color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text("06", color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text("12", color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text("18", color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text("23", color = MV.OnSurfaceDim, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun DailyColumns(rows: List<DailySummary>, goal: Int, color: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LAST 30 DAYS", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (rows.isEmpty()) {
                Text("No data.", color = MV.OnSurfaceVariant, fontSize = 12.sp); return@Card
            }
            val maxV = (rows.maxOfOrNull { it.stepsTotal ?: 0 }
                ?.coerceAtLeast(goal) ?: goal).toFloat()
            Box(Modifier.fillMaxWidth().height(150.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val gap = 2.dp.toPx()
                    val barW = (size.width - gap * (rows.size - 1)) / rows.size
                    // Goal dashed line
                    val gy = size.height - (goal / maxV) * size.height
                    drawLine(
                        color = color.copy(alpha = 0.4f),
                        start = Offset(0f, gy), end = Offset(size.width, gy),
                        strokeWidth = 1.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(
                            floatArrayOf(6.dp.toPx(), 4.dp.toPx())
                        ),
                    )
                    for ((i, r) in rows.withIndex()) {
                        val v = (r.stepsTotal ?: 0).toFloat()
                        val h = (v / maxV) * size.height
                        val barColor = if (v >= goal) color
                                       else color.copy(alpha = 0.55f)
                        drawRect(
                            color = barColor,
                            topLeft = Offset(i * (barW + gap), size.height - h),
                            size = Size(barW, h),
                        )
                    }
                }
            }
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                rows.firstOrNull()?.date?.let {
                    Text(shortDay(it), color = MV.OnSurfaceDim, fontSize = 9.sp)
                }
                rows.lastOrNull()?.date?.let {
                    Text(shortDay(it), color = MV.OnSurfaceDim, fontSize = 9.sp)
                }
            }
        }
    }
}

@Composable
private fun StepsStats(rows: List<DailySummary>, goal: Int) {
    val totals = rows.mapNotNull { it.stepsTotal }
    val total = totals.sum()
    val avg = if (totals.isNotEmpty()) totals.average() else 0.0
    val daysHit = totals.count { it >= goal }
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("STATS", color = MV.OnSurfaceVariant,
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
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun shortDay(iso: String): String =
    runCatching {
        val d = LocalDate.parse(iso)
        DateTimeFormatter.ofPattern("M/d").format(d)
    }.getOrDefault(iso)
