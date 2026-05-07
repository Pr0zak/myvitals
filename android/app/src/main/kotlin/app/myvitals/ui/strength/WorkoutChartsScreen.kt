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
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModelProducer
import com.patrykandpatrick.vico.core.cartesian.data.lineSeries
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate

@Composable
fun WorkoutChartsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    var days by remember { mutableStateOf(90) }
    var stats by remember { mutableStateOf<StrengthStats?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(days) {
        if (!settings.isConfigured()) {
            error = "Backend not configured."; loading = false; return@LaunchedEffect
        }
        loading = true; error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            stats = withContext(Dispatchers.IO) { api.strengthStats(days = days) }
            Timber.i("strength stats: %dd → %d workouts, %d sets, %.0f lb",
                days, stats?.nWorkouts ?: 0,
                stats?.nSets ?: 0, stats?.totalVolumeLb ?: 0.0)
        } catch (e: Exception) {
            Timber.w(e, "strength stats load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Text("Workout charts", color = MV.OnSurface, fontSize = 16.sp,
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
                        selectedContainerColor = MV.BrandRed.copy(alpha = 0.20f),
                        selectedLabelColor = MV.OnSurface,
                    ),
                )
            }
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red,
                modifier = Modifier.padding(16.dp))
            stats == null -> Text("No data", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            else -> {
                val s = stats!!
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { OverviewCard(s) }
                    item { DailyVolumeCard(s) }
                    item { MuscleGroupCard(s) }
                    item { ProgressionCard(s) }
                }
            }
        }
    }
}

@Composable
private fun OverviewCard(s: StrengthStats) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("OVERVIEW · ${s.days}d", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Workouts", "${s.nWorkouts}")
                Stat("Sets", "${s.nSets}")
                Stat("Volume", "%,.0f lb".format(s.totalVolumeLb))
                s.rpeAvg?.let { Stat("Avg RPE", "%.1f".format(it)) }
            }
        }
    }
}

@Composable
private fun DailyVolumeCard(s: StrengthStats) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("DAILY VOLUME", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (s.daily.size < 2) {
                Text("Not enough sessions yet.", color = MV.OnSurfaceVariant, fontSize = 12.sp)
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
private fun MuscleGroupCard(s: StrengthStats) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("VOLUME BY MUSCLE", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (s.perMuscle.isEmpty()) {
                Text("—", color = MV.OnSurfaceVariant, fontSize = 12.sp); return@Card
            }
            val total = s.perMuscle.sumOf { it.volumeLb }.coerceAtLeast(1.0)
            for (m in s.perMuscle.take(8)) {
                Row(Modifier.padding(vertical = 3.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        m.muscle.replaceFirstChar { it.titlecase() },
                        color = MV.OnSurface, fontSize = 12.sp,
                        modifier = Modifier.width(96.dp), maxLines = 1,
                    )
                    Box(Modifier.weight(1f).height(8.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(MV.SurfaceContainerLow)
                    ) {
                        Box(
                            Modifier
                                .fillMaxWidth(fraction = (m.volumeLb / total).toFloat())
                                .height(8.dp)
                                .background(muscleColor(m.muscle)),
                        )
                    }
                    Spacer(Modifier.width(8.dp))
                    Text("%,.0f".format(m.volumeLb), color = MV.OnSurfaceVariant,
                        fontSize = 11.sp, modifier = Modifier.width(60.dp))
                }
            }
        }
    }
}

@Composable
private fun ProgressionCard(s: StrengthStats) {
    if (s.progression.isEmpty()) return
    var selected by remember(s) {
        mutableStateOf(s.progression.keys.firstOrNull() ?: "")
    }
    var menuOpen by remember { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("WEIGHT PROGRESSION", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Box {
                TextButton(onClick = { menuOpen = true }) {
                    Text(
                        s.progressionNames[selected] ?: selected,
                        color = MV.OnSurface, fontSize = 13.sp,
                    )
                    Text(" ▾", color = MV.OnSurfaceDim, fontSize = 13.sp)
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
                    color = MV.OnSurfaceVariant, fontSize = 12.sp); return@Card
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
private fun Stat(label: String, value: String) {
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun muscleColor(m: String): Color = when (m.lowercase()) {
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
