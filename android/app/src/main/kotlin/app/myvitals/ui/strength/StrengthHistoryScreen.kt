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
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.ui.MV
import kotlinx.coroutines.launch
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
                else "Strength history",
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
