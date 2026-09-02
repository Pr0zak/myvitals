package app.myvitals.ui.strength

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
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.PathParser
import app.myvitals.sync.BackendClient
import app.myvitals.sync.MuscleVolumeResponse
import app.myvitals.sync.MuscleVolumeRow
import app.myvitals.sync.StrengthRecord
import app.myvitals.sync.StrengthRecordsResponse
import app.myvitals.sync.StrengthStats
import app.myvitals.sync.StrengthVolumeTrend
import app.myvitals.sync.StrengthWeeklyPoint
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLabelComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberColumnCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.fill
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModelProducer
import com.patrykandpatrick.vico.core.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.core.cartesian.data.columnSeries
import com.patrykandpatrick.vico.core.cartesian.data.lineSeries
import com.patrykandpatrick.vico.core.cartesian.layer.LineCartesianLayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate

@Composable
fun WorkoutChartsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val neon = settings.neonShellEnabled
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val bad = if (neon) NeonMV.Bad else MV.Red
    var days by remember { mutableStateOf(90) }
    var stats by remember { mutableStateOf<StrengthStats?>(null) }
    var records by remember { mutableStateOf<List<StrengthRecord>>(emptyList()) }
    var muscleVol by remember { mutableStateOf<Map<String, MuscleVolumeRow>>(emptyMap()) }
    var volumeTrend by remember { mutableStateOf<List<StrengthWeeklyPoint>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    // Which range `stats` was fetched for. Without it, tapping a different
    // range chip left the PREVIOUS range's charts on screen under the new
    // chip — the same defect the heart-rate screen had, where 90d rendered
    // 30 days of history.
    var statsRange by remember { mutableStateOf<Int?>(null) }

    LaunchedEffect(days) {
        if (statsRange != null && statsRange != days) {
            stats = null; statsRange = null; loading = true
        }
        if (!settings.isConfigured()) {
            error = "Backend not configured."; loading = false; return@LaunchedEffect
        }
        val cacheKey = "strength_stats_${days}d"
        app.myvitals.data.JsonCache.read<StrengthStats>(
            context, cacheKey, StrengthStats::class.java,
        )?.let {
            stats = it.value
            statsRange = days
            loading = false
        }
        if (stats == null) { loading = true }
        error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val fresh = withContext(Dispatchers.IO) { api.strengthStats(days = days) }
            stats = fresh
            statsRange = days
            app.myvitals.data.JsonCache.write(
                context, cacheKey, StrengthStats::class.java, fresh,
            )
            Timber.i("strength stats: %dd → %d workouts, %d sets, %.0f lb",
                days, fresh.nWorkouts, fresh.nSets, fresh.totalVolumeLb)
        } catch (e: Exception) {
            Timber.w(e, "strength stats load failed")
            if (stats == null) error = e.message?.take(160)
        } finally { loading = false }
    }

    // PR-1: all-time records — SWR (cache then fetch), range-independent.
    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) return@LaunchedEffect
        app.myvitals.data.JsonCache.read<StrengthRecordsResponse>(
            context, "strength_records", StrengthRecordsResponse::class.java,
        )?.let { records = it.value.records }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val fresh = withContext(Dispatchers.IO) { api.strengthRecords() }
            records = fresh.records
            app.myvitals.data.JsonCache.write(
                context, "strength_records", StrengthRecordsResponse::class.java, fresh,
            )
        } catch (e: Exception) {
            Timber.w(e, "strength records load failed")
        }
    }

    // MMAP-1: 7-day muscle-volume status for the body map — SWR, fixed window.
    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) return@LaunchedEffect
        app.myvitals.data.JsonCache.read<MuscleVolumeResponse>(
            context, "muscle_volume_7d", MuscleVolumeResponse::class.java,
        )?.let { muscleVol = it.value.muscles }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val fresh = withContext(Dispatchers.IO) { api.strengthMuscleVolume(days = 7) }
            muscleVol = fresh.muscles
            app.myvitals.data.JsonCache.write(
                context, "muscle_volume_7d", MuscleVolumeResponse::class.java, fresh,
            )
        } catch (e: Exception) {
            Timber.w(e, "muscle volume load failed")
        }
    }

    // VOLT-1: 16-week mesocycle volume trend — SWR, fixed window.
    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) return@LaunchedEffect
        app.myvitals.data.JsonCache.read<StrengthVolumeTrend>(
            context, "volume_trend_16w", StrengthVolumeTrend::class.java,
        )?.let { volumeTrend = it.value.trend }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val fresh = withContext(Dispatchers.IO) { api.strengthVolumeTrend(weeks = 16) }
            volumeTrend = fresh.trend
            app.myvitals.data.JsonCache.write(
                context, "volume_trend_16w", StrengthVolumeTrend::class.java, fresh,
            )
        } catch (e: Exception) {
            Timber.w(e, "volume trend load failed")
        }
    }

    Column(Modifier.fillMaxSize().background(bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = ink)
            }
            Text("Workout charts", color = ink, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (d in listOf(7, 30, 90, 365)) {
                FilterChip(
                    selected = days == d,
                    onClick = { days = d },
                    label = { Text(if (d >= 365) "1y" else "${d}d") },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = accent.copy(alpha = 0.20f),
                        selectedLabelColor = ink,
                    ),
                )
            }
        }
        when {
            loading -> Text("Loading…", color = muted,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = bad,
                modifier = Modifier.padding(16.dp))
            stats == null -> Text("No data", color = muted,
                modifier = Modifier.padding(16.dp))
            else -> {
                val s = stats!!
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    // CONS-1 sits first and deliberately does NOT respond to
                    // the range selector — these are full-history figures, and
                    // placing them below the range-bounded cards without
                    // saying so would imply otherwise.
                    s.consistency?.let { c -> item { ConsistencyCard(c, neon) } }
                    item { OverviewCard(s, neon) }
                    item { BodyMapCard(muscleVol, neon) }
                    item { DailyVolumeCard(s, neon) }
                    // Only when >=2 weeks have real training (backend zero-fills
                    // the full 16-week spine, so size is always 16).
                    if (volumeTrend.count { it.volumeLb > 0 } >= 2) {
                        item { WeeklyVolumeCard(volumeTrend, neon) }
                    }
                    item { MuscleGroupCard(s, neon) }
                    item { ProgressionCard(s, neon) }
                    if (records.isNotEmpty()) item { RecordsCard(records, neon) }
                }
            }
        }
    }
}

/**
 * CONS-1 — mirrors `frontend/src/components/ConsistencyCard.vue`.
 *
 * Renders only; every number here is computed by the backend over full
 * history in the user's timezone. Deriving any of it from the loaded
 * stats window is what made the streak change when the range chip did.
 */
@Composable
private fun ConsistencyCard(c: app.myvitals.sync.TrainingConsistency, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val good = if (neon) NeonMV.Lime else MV.Green

    // Most-rested first: that ordering answers "what should I train?",
    // which is the question the number is for.
    val rested = remember(c) { c.daysSinceByMuscle.entries.sortedByDescending { it.value } }

    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("CONSISTENCY", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                StatCell("${c.currentStreakDays}d", "current streak", ink, muted)
                StatCell("${c.longestStreakDays}d", "longest", ink, muted)
                StatCell("${c.sessionsPerWeekActual}", "per week", ink, muted)
                StatCell("${c.sessionsLast28d}", "last 28d", ink, muted)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                when {
                    c.currentStreakDays == 0 ->
                        c.lastActive?.let { "Last session $it" } ?: "No history yet"
                    // The distinction todayPending carries: a streak resting
                    // on yesterday is alive but not yet banked, and saying
                    // "banked" would be wrong by a day.
                    c.todayPending -> "Train today to keep the streak"
                    else -> "Today is banked"
                },
                color = if (c.todayPending) muted else good, fontSize = 11.sp,
            )
            Text(
                "Frequency over ${c.frequencyWindowDays} days — not the "
                    + "selected range.",
                color = muted, fontSize = 10.sp,
                modifier = Modifier.padding(top = 2.dp),
            )

            if (rested.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Text("DAYS RESTED", color = muted,
                    fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
                Spacer(Modifier.height(4.dp))
                for (chunk in rested.chunked(3)) {
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        for ((muscle, days) in chunk) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    muscle.replace('_', ' '),
                                    color = muted, fontSize = 10.sp, maxLines = 1,
                                )
                                Text(
                                    "${days}d",
                                    color = if (days >= 7) good else ink,
                                    fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                                )
                            }
                        }
                        // Pad a short final row so columns stay aligned.
                        repeat(3 - chunk.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatCell(value: String, label: String, ink: Color, muted: Color) {
    Column {
        Text(value, color = ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        Text(label, color = muted, fontSize = 10.sp)
    }
}

@Composable
private fun OverviewCard(s: StrengthStats, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("OVERVIEW · ${s.days}d", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Workouts", "${s.nWorkouts}", neon)
                Stat("Sets", "${s.nSets}", neon)
                Stat("Volume", "%,.0f lb".format(s.totalVolumeLb), neon)
                // OG2-C4: the average carries its denominator. A rating is
                // optional, so a partly-rated history is the normal case and
                // the mean must not silently speak for sets nobody rated.
                s.rpeAvg?.let {
                    val denom = s.ratedSets?.let { r -> " ($r/${s.nSets})" } ?: ""
                    Stat("Avg rating", "%.1f".format(it) + denom, neon)
                }
            }
        }
    }
}

@Composable
private fun DailyVolumeCard(s: StrengthStats, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("DAILY VOLUME", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (s.daily.size < 2) {
                Text("Not enough sessions yet.", color = muted, fontSize = 12.sp)
                return@Card
            }
            // The producer MUST be a single stable instance for the lifetime of
            // this CartesianChartHost — Vico throws IllegalStateException if a new
            // producer is handed to an existing host. Create it ONCE (no key) and
            // push every data change through runTransaction below; keying the
            // remember on `s` recreated it when SWR swapped cached→fresh stats,
            // which is what crashed the screen.
            // Vico's default axis label colour follows the SYSTEM dark-mode
            // flag, but this app is always dark — so on a phone set to light
            // mode the axis numbers were painted near-black on the obsidian
            // card and simply could not be read.
            val axisInk = app.myvitals.ui.LocalAppTokens.current.onSurfaceVariant
            val producer = remember { CartesianChartModelProducer() }
            // x is an offset from the first day, so the axis printed 0, 5, 10…
            // — numbers that mean nothing without knowing the origin. Keep the
            // origin so the formatter can turn them back into dates.
            var xOrigin by remember { mutableStateOf(0L) }
            LaunchedEffect(s) {
                val pairs = s.daily.mapIndexedNotNull { _, d ->
                    runCatching {
                        LocalDate.parse(d.date).toEpochDay().toDouble() to d.volumeLb
                    }.getOrNull()
                }
                if (pairs.isEmpty()) return@LaunchedEffect
                val origin = pairs.first().first
                xOrigin = origin.toLong()
                val xs = pairs.map { it.first - origin }
                val ys = pairs.map { it.second }
                producer.runTransaction { lineSeries { series(x = xs, y = ys) } }
            }
            val dateFormatter = remember(xOrigin) {
                CartesianValueFormatter { _, value, _ ->
                    runCatching {
                        val d = LocalDate.ofEpochDay(xOrigin + value.toLong())
                        "${d.monthValue}/${d.dayOfMonth}"
                    }.getOrDefault("")
                }
            }
            // Default Vico line layer (stable across data shapes + devices).
            // The neon feel comes from the obsidian card + lime muscle bars;
            // the custom LineProvider/rememberLine path was a crash risk.
            CartesianChartHost(
                chart = rememberCartesianChart(
                    rememberLineCartesianLayer(),
                    startAxis = VerticalAxis.rememberStart(
                        label = rememberAxisLabelComponent(color = axisInk),
                    ),
                    bottomAxis = HorizontalAxis.rememberBottom(
                        label = rememberAxisLabelComponent(color = axisInk),
                        valueFormatter = dateFormatter,
                    ),
                ),
                modelProducer = producer,
                scrollState = rememberVicoScrollState(),
                zoomState = rememberVicoZoomState(),
                modifier = Modifier.fillMaxWidth().height(200.dp),
            )
        }
    }
}

@Composable
private fun WeeklyVolumeCard(trend: List<StrengthWeeklyPoint>, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("WEEKLY VOLUME · 16-WEEK MESOCYCLE", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            // Same stable-keyless-producer discipline as DailyVolumeCard — a
            // single producer for the host's lifetime, data pushed via
            // runTransaction. Column layer instead of line (bars read as a
            // mesocycle load trend). x = week index, y = volume lb.
            // Vico's default axis label colour follows the SYSTEM dark-mode
            // flag, but this app is always dark — so on a phone set to light
            // mode the axis numbers were painted near-black on the obsidian
            // card and simply could not be read.
            val axisInk = app.myvitals.ui.LocalAppTokens.current.onSurfaceVariant
            val producer = remember { CartesianChartModelProducer() }
            LaunchedEffect(trend) {
                if (trend.size < 2) return@LaunchedEffect
                val xs = trend.indices.map { it.toDouble() }
                val ys = trend.map { it.volumeLb }
                producer.runTransaction { columnSeries { series(x = xs, y = ys) } }
            }
            CartesianChartHost(
                chart = rememberCartesianChart(
                    rememberColumnCartesianLayer(),
                    startAxis = VerticalAxis.rememberStart(
                        label = rememberAxisLabelComponent(color = axisInk),
                    ),
                    bottomAxis = HorizontalAxis.rememberBottom(
                        label = rememberAxisLabelComponent(color = axisInk),
                    ),
                ),
                modelProducer = producer,
                scrollState = rememberVicoScrollState(),
                zoomState = rememberVicoZoomState(),
                modifier = Modifier.fillMaxWidth().height(200.dp),
            )
        }
    }
}

@Composable
private fun MuscleGroupCard(s: StrengthStats, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val track = if (neon) NeonMV.Track else MV.SurfaceContainerLow
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("VOLUME BY MUSCLE", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (s.perMuscle.isEmpty()) {
                Text("—", color = muted, fontSize = 12.sp); return@Card
            }
            // Scale to the LARGEST muscle, not the sum of all of them. Against
            // the sum, the top muscle in an eight-way split fills a quarter of
            // its track and everything else is a stub — the chart compares
            // muscles to each other, not to the total.
            val total = s.perMuscle.maxOfOrNull { it.volumeLb }?.coerceAtLeast(1.0) ?: 1.0
            for (m in s.perMuscle.take(8)) {
                Row(Modifier.padding(vertical = 3.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        m.muscle.replaceFirstChar { it.titlecase() },
                        color = ink, fontSize = 12.sp,
                        modifier = Modifier.width(96.dp), maxLines = 1,
                    )
                    Box(Modifier.weight(1f).height(8.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(track)
                    ) {
                        Box(
                            Modifier
                                .fillMaxWidth(fraction = (m.volumeLb / total).toFloat())
                                .height(8.dp)
                                .background(muscleColor(m.muscle, neon)),
                        )
                    }
                    Spacer(Modifier.width(8.dp))
                    Text("%,.0f".format(m.volumeLb), color = muted,
                        fontSize = 11.sp, modifier = Modifier.width(60.dp))
                }
            }
        }
    }
}

@Composable
private fun ProgressionCard(s: StrengthStats, neon: Boolean) {
    if (s.progression.isEmpty()) return
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val dim = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    var selected by remember(s) {
        mutableStateOf(s.progression.keys.firstOrNull() ?: "")
    }
    var menuOpen by remember { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("WEIGHT PROGRESSION", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Box {
                TextButton(onClick = { menuOpen = true }) {
                    Text(
                        s.progressionNames[selected] ?: selected,
                        color = ink, fontSize = 13.sp,
                    )
                    Text(" ▾", color = dim, fontSize = 13.sp)
                }
                DropdownMenu(
                    expanded = menuOpen, onDismissRequest = { menuOpen = false },
                ) {
                    for (id in s.progression.keys) {
                        DropdownMenuItem(
                            text = { Text(s.progressionNames[id] ?: id) },
                            onClick = { selected = id; menuOpen = false },
                        )
                    }
                }
            }
            val pts = s.progression[selected] ?: emptyList()
            if (pts.size < 2) {
                Text("Need at least 2 sessions for this exercise.",
                    color = muted, fontSize = 12.sp); return@Card
            }
            // e1RM-1: toggle the single line between top weight and estimated
            // 1RM. One series at a time keeps the Vico producer simple (no
            // multi-series styling — see the v0.7.302/306 Vico notes).
            // OG2-C3: what this exercise's history is about, decided
            // server-side. A lift that has never carried weight plots reps
            // and a timed hold plots seconds — both used to be absent from
            // this picker entirely, because the series was built only from
            // sets carrying a weight.
            val shape = s.progressionMetric[selected]
                ?: app.myvitals.sync.ProgressionMetric()
            val weighted = shape.metric == "weight"
            var metric by remember(selected, weighted) {
                mutableStateOf(if (weighted) "e1rm" else "primary")
            }
            if (weighted) {
                Row(horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(4.dp)) {
                    for ((mv, ml) in listOf("e1rm" to "e1RM", "weight" to "Top weight")) {
                        androidx.compose.material3.FilterChip(
                            selected = metric == mv,
                            onClick = { metric = mv },
                            label = { Text(ml, fontSize = 10.sp) },
                        )
                    }
                }
            }
            // The chart says what it plots rather than leaving the reader to
            // infer it from an axis that used to be hard-named "lb".
            if (shape.caption.isNotBlank()) {
                Text(
                    shape.caption,
                    color = app.myvitals.ui.LocalAppTokens.current.onSurfaceVariant,
                    fontSize = 11.sp,
                )
            }
            // Single stable producer (see DailyVolumeCard) — data updates flow
            // through runTransaction keyed on (selected, s, metric), never a new producer.
            // Vico's default axis label colour follows the SYSTEM dark-mode
            // flag, but this app is always dark — so on a phone set to light
            // mode the axis numbers were painted near-black on the obsidian
            // card and simply could not be read.
            val axisInk = app.myvitals.ui.LocalAppTokens.current.onSurfaceVariant
            val producer = remember { CartesianChartModelProducer() }
            LaunchedEffect(selected, s, metric) {
                val pairs = pts.mapNotNull { p ->
                    runCatching {
                        val y: Double = when {
                            !weighted -> (p.topReps ?: 0).toDouble()
                            metric == "e1rm" -> (p.e1rm ?: p.topWeightLb) ?: return@runCatching null
                            else -> p.topWeightLb ?: return@runCatching null
                        }
                        LocalDate.parse(p.date).toEpochDay().toDouble() to y
                    }.getOrNull()
                }
                if (pairs.size < 2) return@LaunchedEffect
                val origin = pairs.first().first
                val xs = pairs.map { it.first - origin }
                val ys = pairs.map { it.second }
                producer.runTransaction { lineSeries { series(x = xs, y = ys) } }
            }
            // Default Vico line layer (stable across data shapes + devices).
            CartesianChartHost(
                chart = rememberCartesianChart(
                    rememberLineCartesianLayer(),
                    startAxis = VerticalAxis.rememberStart(
                        label = rememberAxisLabelComponent(color = axisInk),
                    ),
                    bottomAxis = HorizontalAxis.rememberBottom(
                        label = rememberAxisLabelComponent(color = axisInk),
                    ),
                ),
                modelProducer = producer,
                scrollState = rememberVicoScrollState(),
                zoomState = rememberVicoZoomState(),
                modifier = Modifier.fillMaxWidth().height(200.dp),
            )
        }
    }
}

private val REC_DATE_FMT = java.time.format.DateTimeFormatter.ofPattern("MMM d, yy")

private fun fmtRecDate(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
    return runCatching {
        java.time.LocalDate.parse(iso.take(10)).format(REC_DATE_FMT)
    }.getOrDefault("")
}

@Composable
private fun RecordsCard(records: List<StrengthRecord>, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("PERSONAL RECORDS", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            for (r in records) {
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(r.name, color = ink, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold)
                        fmtRecDate(r.lastPerformedDate).takeIf { it.isNotEmpty() }?.let {
                            Text("last $it", color = muted, fontSize = 10.sp)
                        }
                    }
                    // PR-1b: which best is meaningful depends on the kind.
                    // Rendering "0.0 lb · e1RM 0" for a push-up — which is
                    // what the old unconditional format produced — reads as
                    // broken data rather than as a rep record.
                    Column(horizontalAlignment = Alignment.End) {
                        val primary = when (r.kind) {
                            "hold" -> "${r.bestHoldS} s" to r.bestHoldDate
                            "bodyweight" -> "${r.bestReps} reps" to r.bestRepsDate
                            else -> "%.1f lb".format(r.bestWeightLb) to r.bestWeightDate
                        }
                        Text(
                            buildString {
                                append(primary.first)
                                fmtRecDate(primary.second).takeIf { it.isNotEmpty() }
                                    ?.let { append(" · $it") }
                            },
                            color = ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        )
                        val secondary: Pair<String, String?>? = when {
                            // Added load on a bodyweight movement. Never an
                            // e1RM — Epley on the added weight alone would
                            // report a one-rep max for a load that is only
                            // part of the total.
                            r.kind == "bodyweight" && r.bestWeightLb > 0 ->
                                "+%.1f lb".format(r.bestWeightLb) to r.bestWeightDate
                            r.kind == "loaded" ->
                                "e1RM %.0f".format(r.bestE1rm) to r.bestE1rmDate
                            else -> null
                        }
                        secondary?.let { (label, d) ->
                            Text(
                                buildString {
                                    append(label)
                                    fmtRecDate(d).takeIf { it.isNotEmpty() }
                                        ?.let { append(" · $it") }
                                },
                                color = muted, fontSize = 11.sp,
                            )
                        }
                    }
                }
            }
        }
    }
}

// Pure (plain Color literals, no MaterialTheme/@Composable tokens) so it can be
// called from the non-composable DrawScope lambda. Hexes match web BodyMap.vue
// — untrained uses web's DARK-theme values (the phone is dark-only) so it
// recedes into the silhouette on both surfaces.
private fun muscleStatusColor(status: String?, neon: Boolean): Color = when (status) {
    "under" -> if (neon) Color(0xFFFFB52E) else Color(0xFFFACC15)
    "in_range" -> if (neon) Color(0xFF5DFF3B) else Color(0xFF22C55E)
    "over" -> if (neon) Color(0xFFFF5D7A) else Color(0xFFEF4444)
    else -> if (neon) Color(0xFF3A3F52) else Color(0xFF475569)  // untrained / absent
}

@Composable
private fun BodyMapCard(muscles: Map<String, MuscleVolumeRow>, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val sil = muted.copy(alpha = 0.22f)
    // Parse each SVG path once and resolve its status color HERE in the
    // composable body (same path data as web BodyMap.vue). The draw lambda
    // below stays pure geometry — resolving colors inside the DrawScope block
    // trips the Compose compiler.
    val silFront = remember { PathParser().parsePathString(BodyMapPaths.SILHOUETTE_FRONT).toPath() }
    val silBack = remember { PathParser().parsePathString(BodyMapPaths.SILHOUETTE_BACK).toPath() }
    val drawn = remember(muscles, neon) {
        BodyMapPaths.REGIONS.map { (m, d) ->
            PathParser().parsePathString(d).toPath() to muscleStatusColor(muscles[m]?.status, neon)
        }
    }
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text("MUSCLE BALANCE · 7-DAY", color = muted,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            Canvas(
                Modifier.fillMaxWidth()
                    .aspectRatio(BodyMapPaths.VIEWBOX_W / BodyMapPaths.VIEWBOX_H)
            ) {
                scale(
                    size.width / BodyMapPaths.VIEWBOX_W,
                    size.height / BodyMapPaths.VIEWBOX_H,
                    pivot = Offset.Zero,
                ) {
                    drawPath(silFront, sil)
                    drawPath(silBack, sil)
                    drawn.forEach { (p, c) -> drawPath(p, c) }
                }
            }
            Spacer(Modifier.height(10.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                LegendKey("Untrained", muscleStatusColor("untrained", neon), muted)
                LegendKey("Under", muscleStatusColor("under", neon), muted)
                LegendKey("In range", muscleStatusColor("in_range", neon), muted)
                LegendKey("Over", muscleStatusColor("over", neon), muted)
            }
        }
    }
}

@Composable
private fun LegendKey(label: String, color: Color, textColor: Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text("■", color = color, fontSize = 10.sp)
        Text(label, color = textColor, fontSize = 10.sp)
    }
}

@Composable
private fun Stat(label: String, value: String, neon: Boolean) {
    val dim = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    Column {
        Text(label, color = dim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun muscleColor(m: String, neon: Boolean): Color =
    if (neon) when (m.lowercase()) {
        "chest" -> NeonMV.Bad
        "back", "lats" -> NeonMV.Cyan
        "shoulders" -> NeonMV.Amber
        "biceps" -> NeonMV.Magenta
        "triceps" -> NeonMV.Periwinkle
        "quadriceps", "quads" -> NeonMV.Lime
        "hamstrings" -> NeonMV.Lime
        "glutes" -> NeonMV.Cyan
        "calves" -> NeonMV.Lime
        "abdominals", "abs", "core" -> NeonMV.Amber
        "forearms" -> NeonMV.Muted
        else -> NeonMV.Muted
    } else when (m.lowercase()) {
        "chest" -> Color(0xFFEF4444)
        "back", "lats" -> Color(0xFF3B82F6)
        "shoulders" -> Color(0xFFF59E0B)
        "biceps" -> Color(0xFFA855F7)
        "triceps" -> Color(0xFFEC4899)
        "quadriceps", "quads" -> Color(0xFF22C55E)
        "hamstrings" -> Color(0xFF10B981)
        "glutes" -> Color(0xFF14B8A6)
        "calves" -> Color(0xFF84CC16)
        "abdominals", "abs", "core" -> Color(0xFFFBBF24)
        "forearms" -> Color(0xFF94A3B8)
        else -> Color(0xFF64748B)
    }
