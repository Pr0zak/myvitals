package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.shape.RoundedCornerShape
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.MuscleVolumeRow
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun StrengthHistoryScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repo = remember(settings) { StrengthRepository(context, settings) }

    var rows by remember { mutableStateOf<List<StrengthWorkoutSummary>>(emptyList()) }
    var detail by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var catalog by remember { mutableStateOf<Map<String, StrengthExerciseInfo>>(emptyMap()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            rows = repo.history()
            catalog = repo.catalog()
        } catch (e: Exception) {
            Timber.w(e, "history load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MV.Bg)
            .padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = if (detail != null) ({ detail = null }) else onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = MV.OnSurface)
            }
            Spacer(Modifier.width(4.dp))
            Text(
                if (detail != null)
                    "${fmtDate(detail!!.date)} · ${detail!!.splitFocus.replace('_', ' ')}"
                else "Workout history",
                color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
            )
        }

        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant)
            error != null -> Text(error!!, color = MV.Red)
            detail != null -> DetailList(detail!!, catalog)
            rows.isEmpty() -> Text(
                "No workouts logged yet. Start one from the Today tab.",
                color = MV.OnSurfaceVariant, modifier = Modifier.padding(16.dp),
            )
            else -> LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item { MuscleVolumeCard(settings = settings) }
                item { WorkoutCalendar(rows) }
                items(rows, key = { it.id }) { r ->
                    HistoryRow(r) {
                        scope.launch {
                            try { detail = repo.workoutDetail(r.id) }
                            catch (e: Exception) { error = e.message?.take(160) }
                        }
                    }
                }
            }
        }
    }
}

/** #WP-4 — Weekly muscle volume audit. Sets-per-primary-muscle over
 *  the last 7 days, coloured by under/in-range/over vs research-backed
 *  MEV/MAV ranges. Mirrors web's MuscleVolume.vue. */
@Composable
private fun MuscleVolumeCard(settings: SettingsRepository) {
    var rows by remember { mutableStateOf<List<Pair<String, MuscleVolumeRow>>>(emptyList()) }
    var windowDays by remember { mutableStateOf(7) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.strengthMuscleVolume(7) }
            windowDays = resp.windowDays
            // Sort: non-zero by descending sets, then zero-volume alphabetical.
            rows = resp.muscles.toList().sortedWith(
                compareBy<Pair<String, MuscleVolumeRow>> { it.second.sets == 0 }
                    .thenByDescending { it.second.sets }
                    .thenBy { it.first }
            )
        } catch (e: Exception) {
            Timber.w(e, "muscle volume load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(
                "Weekly muscle volume",
                color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            )
            Text(
                "Last $windowDays days vs research-backed MEV / MAV",
                color = MV.OnSurfaceVariant, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 6.dp),
            )
            when {
                loading -> Text("Loading…", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                error != null -> Text(error!!, color = MV.Red, fontSize = 11.sp)
                rows.isEmpty() -> Text("No data.", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                else -> for ((muscle, r) in rows) {
                    val accent = when (r.status) {
                        "under" -> Color(0xFFFACC15)
                        "in_range" -> Color(0xFF22C55E)
                        "over" -> Color(0xFFEF4444)
                        else -> MV.OnSurfaceVariant
                    }
                    val fillPct = if (r.mav > 0) {
                        (r.sets.toFloat() / r.mav.toFloat()).coerceAtMost(1f)
                    } else 0f
                    Column(Modifier.padding(vertical = 3.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                muscle.replace('_', ' '),
                                color = MV.OnSurface, fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                "${r.sets} / ${r.mev}–${r.mav}",
                                color = MV.OnSurfaceVariant, fontSize = 11.sp,
                            )
                        }
                        Spacer(Modifier.height(2.dp))
                        Box(
                            Modifier
                                .fillMaxWidth()
                                .height(4.dp)
                                .clip(RoundedCornerShape(2.dp))
                                .background(MV.SurfaceContainerLow),
                        ) {
                            Box(
                                Modifier
                                    .fillMaxWidth(fillPct)
                                    .height(4.dp)
                                    .clip(RoundedCornerShape(2.dp))
                                    .background(accent),
                            )
                        }
                    }
                }
            }
        }
    }
}


/** Year-strip calendar of completed workouts. Each cell is a day;
 *  color encodes split_focus (strength=red, yoga=violet, cardio=blue).
 *  Mirrors the web Workout-history calendar. */
@Composable
private fun WorkoutCalendar(rows: List<StrengthWorkoutSummary>) {
    val completed = remember(rows) {
        rows.filter { it.status == "completed" }
    }
    if (completed.isEmpty()) return
    val byDate = remember(completed) {
        completed.associateBy({ it.date }, { it.splitFocus.lowercase() })
    }
    val years = remember(byDate) {
        byDate.keys.map { it.take(4) }.distinct().sortedDescending()
    }
    androidx.compose.material3.Card(
        colors = androidx.compose.material3.CardDefaults.cardColors(
            containerColor = MV.SurfaceContainer,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "WORKOUT CALENDAR",
                    color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
                )
                Spacer(Modifier.width(8.dp))
                LegendDot(color = androidx.compose.ui.graphics.Color(0xFFEF4444), label = "Strength")
                Spacer(Modifier.width(6.dp))
                LegendDot(color = androidx.compose.ui.graphics.Color(0xFFA78BFA), label = "Yoga")
                Spacer(Modifier.width(6.dp))
                LegendDot(color = androidx.compose.ui.graphics.Color(0xFF38BDF8), label = "Cardio")
            }
            Spacer(Modifier.height(8.dp))
            for (y in years) {
                YearStrip(year = y, byDate = byDate)
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
private fun LegendDot(color: androidx.compose.ui.graphics.Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.foundation.layout.Box(
            modifier = Modifier
                .size(8.dp)
                .background(color, androidx.compose.foundation.shape.CircleShape),
        )
        Spacer(Modifier.width(3.dp))
        Text(label, color = MV.OnSurfaceVariant, fontSize = 9.sp)
    }
}

@Composable
private fun YearStrip(year: String, byDate: Map<String, String>) {
    // Build a 53-column × 7-row grid for the year. Walk every day from
    // Jan 1 → Dec 31 and place cells by ISO week + day-of-week.
    val firstDay = remember(year) {
        java.time.LocalDate.of(year.toInt(), 1, 1)
    }
    val daysInYear = remember(year) { firstDay.lengthOfYear() }
    val cellSize = 10.dp
    val cellGap = 2.dp
    androidx.compose.foundation.layout.Box {
        androidx.compose.foundation.Canvas(
            modifier = Modifier
                .height((cellSize.value * 7 + cellGap.value * 6).dp)
                .fillMaxWidth(),
        ) {
            val cellPx = cellSize.toPx()
            val gapPx = cellGap.toPx()
            val totalCols = 53
            val originX = 0f
            // Origin Jan 1 might not be a Sunday, so first column is partial.
            val startDow = firstDay.dayOfWeek.value % 7  // ISO Mon=1..Sun=7 → Sun=0
            for (i in 0 until daysInYear) {
                val date = firstDay.plusDays(i.toLong())
                val col = (i + startDow) / 7
                val row = (i + startDow) % 7
                if (col >= totalCols) break
                val isoDate = date.toString()
                val focus = byDate[isoDate]
                val color = when (focus) {
                    null -> androidx.compose.ui.graphics.Color(0x141A2332)
                    "yoga" -> androidx.compose.ui.graphics.Color(0xFFA78BFA)
                    "cardio" -> androidx.compose.ui.graphics.Color(0xFF38BDF8)
                    else -> androidx.compose.ui.graphics.Color(0xFFEF4444)
                }
                val x = originX + col * (cellPx + gapPx)
                val y = row * (cellPx + gapPx)
                drawRect(
                    color = color,
                    topLeft = androidx.compose.ui.geometry.Offset(x, y),
                    size = androidx.compose.ui.geometry.Size(cellPx, cellPx),
                )
            }
        }
        Text(
            year,
            color = MV.OnSurfaceDim, fontSize = 9.sp,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(end = 4.dp),
        )
    }
}

@Composable
private fun HistoryRow(r: StrengthWorkoutSummary, onClick: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = when (r.status) {
                "in_progress" -> MV.SurfaceContainerHigh
                "skipped" -> MV.SurfaceContainerLow
                else -> MV.SurfaceContainer
            },
        ),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    fmtDate(r.date),
                    color = MV.OnSurface, fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    r.status.replace('_', ' ').uppercase(),
                    color = MV.OnSurfaceVariant, fontSize = 10.sp,
                    letterSpacing = 1.sp, fontWeight = FontWeight.Bold,
                )
            }
            Text(
                r.splitFocus.replace('_', ' ').replaceFirstChar(Char::titlecase),
                color = MV.OnSurfaceVariant, fontSize = 13.sp,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

@Composable
private fun DetailList(plan: StrengthWorkoutDetail, catalog: Map<String, StrengthExerciseInfo>) {
    LazyColumn(
        contentPadding = PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(plan.exercises, key = { it.id }) { wex ->
            Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text(
                        "${wex.orderIndex + 1}. " +
                                (catalog[wex.exerciseId]?.name ?: wex.exerciseId.replace('_', ' ')),
                        color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    )
                    for (s in wex.sets.sortedBy { it.setNumber }) {
                        Text(
                            "Set ${s.setNumber}: ${s.actualWeightLb ?: "—"}lb × ${s.actualReps ?: "—"}" +
                                    (s.rating?.let { " · RPE $it" } ?: ""),
                            color = MV.OnSurfaceVariant, fontSize = 12.sp,
                        )
                    }
                    if (wex.sets.isEmpty()) {
                        Text("No sets logged.", color = MV.OnSurfaceDim, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}

private fun fmtDate(iso: String): String = try {
    LocalDate.parse(iso).format(DateTimeFormatter.ofPattern("EEE, MMM d"))
} catch (_: Exception) { iso }
