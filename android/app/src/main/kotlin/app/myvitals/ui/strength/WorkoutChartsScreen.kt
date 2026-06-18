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
import app.myvitals.sync.BackendClient
import app.myvitals.sync.StrengthStats
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.compose.common.fill
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModelProducer
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
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(days) {
        if (!settings.isConfigured()) {
            error = "Backend not configured."; loading = false; return@LaunchedEffect
        }
        val cacheKey = "strength_stats_${days}d"
        app.myvitals.data.JsonCache.read<StrengthStats>(
            context, cacheKey, StrengthStats::class.java,
        )?.let {
            stats = it.value
            loading = false
        }
        if (stats == null) { loading = true }
        error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val fresh = withContext(Dispatchers.IO) { api.strengthStats(days = days) }
            stats = fresh
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
                    item { OverviewCard(s, neon) }
                    item { DailyVolumeCard(s, neon) }
                    item { MuscleGroupCard(s, neon) }
                    item { ProgressionCard(s, neon) }
                }
            }
        }
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
                s.rpeAvg?.let { Stat("Avg RPE", "%.1f".format(it), neon) }
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
            val producer = remember(s) { CartesianChartModelProducer() }
            LaunchedEffect(s) {
                val pairs = s.daily.mapIndexedNotNull { _, d ->
                    runCatching {
                        LocalDate.parse(d.date).toEpochDay().toDouble() to d.volumeLb
                    }.getOrNull()
                }
                if (pairs.isEmpty()) return@LaunchedEffect
                val origin = pairs.first().first
                val xs = pairs.map { it.first - origin }
                val ys = pairs.map { it.second }
                producer.runTransaction { lineSeries { series(x = xs, y = ys) } }
            }
            // Default Vico line layer (stable across data shapes + devices).
            // The neon feel comes from the obsidian card + lime muscle bars;
            // the custom LineProvider/rememberLine path was a crash risk.
            CartesianChartHost(
                chart = rememberCartesianChart(
                    rememberLineCartesianLayer(),
                    startAxis = VerticalAxis.rememberStart(),
                    bottomAxis = HorizontalAxis.rememberBottom(),
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
            val total = s.perMuscle.sumOf { it.volumeLb }.coerceAtLeast(1.0)
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
            val producer = remember(selected, s) { CartesianChartModelProducer() }
            LaunchedEffect(selected, s) {
                val pairs = pts.mapNotNull { p ->
                    runCatching {
                        LocalDate.parse(p.date).toEpochDay().toDouble() to p.topWeightLb
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
                    startAxis = VerticalAxis.rememberStart(),
                    bottomAxis = HorizontalAxis.rememberBottom(),
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
