package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun StrengthDayViewScreen(
    settings: SettingsRepository,
    dateIso: String,
    onBack: () -> Unit,
) {
    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var notFound by remember { mutableStateOf(false) }

    LaunchedEffect(dateIso) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.strengthWorkoutByDate(dateIso) }
            when {
                resp.isSuccessful -> workout = resp.body()
                resp.code() == 404 -> notFound = true
                else -> error = "Load failed (HTTP ${resp.code()})"
            }
            Timber.i("workout-day-view %s: status=%d hasBody=%s",
                dateIso, resp.code(), workout != null)
        } catch (e: Exception) {
            Timber.w(e, "workout-day-view load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    val parsed = remember(dateIso) {
        runCatching { LocalDate.parse(dateIso) }.getOrNull()
    }
    val titleFmt = DateTimeFormatter.ofPattern("EEE, MMM d")

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Text(parsed?.format(titleFmt) ?: dateIso,
                color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red,
                modifier = Modifier.padding(16.dp))
            notFound -> Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.padding(16.dp).fillMaxWidth(),
            ) {
                Text("No workout recorded for this day.",
                    color = MV.OnSurfaceVariant,
                    modifier = Modifier.padding(14.dp), fontSize = 13.sp)
            }
            workout != null -> {
                val w = workout!!
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { DayHeader(w) }
                    items(w.exercises, key = { it.id }) { wex ->
                        DayExerciseCard(wex)
                    }
                }
            }
        }
    }
}

@Composable
private fun DayHeader(w: StrengthWorkoutDetail) {
    val isPreview = w.id < 0 || w.status == "preview"
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text(w.splitFocus.replaceFirstChar { it.titlecase() }
                + (if (isPreview) " · Preview" else ""),
                color = MV.OnSurface, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold)
            Text(muscleGroupsFor(w.splitFocus),
                color = MV.OnSurfaceVariant, fontSize = 12.sp)
            if (w.status != "preview") {
                Spacer(Modifier.height(4.dp))
                val pip = when (w.status) {
                    "completed" -> "Complete"
                    "in_progress" -> "In progress"
                    "skipped" -> "Skipped"
                    "planned" -> "Planned"
                    else -> w.status
                }
                Text(pip, color = MV.OnSurfaceDim, fontSize = 11.sp,
                    fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun DayExerciseCard(wex: app.myvitals.sync.StrengthWorkoutExerciseRow) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(12.dp)) {
            Text(wex.exerciseId.replace('_', ' '),
                color = MV.OnSurface, fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold)
            val rep = if (wex.targetRepsLow == wex.targetRepsHigh)
                "${wex.targetRepsLow}" else "${wex.targetRepsLow}-${wex.targetRepsHigh}"
            val w = wex.targetWeightLb?.let { " @ ${it}lb" } ?: ""
            Text("${wex.targetSets}×$rep$w",
                color = MV.OnSurfaceVariant, fontSize = 12.sp)
            // Logged sets (if any)
            for (s in wex.sets.sortedBy { it.setNumber }) {
                if (s.actualReps != null) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        "  set ${s.setNumber}: ${s.actualWeightLb ?: "—"}lb × ${s.actualReps}"
                            + (s.rating?.let { " · RPE $it" } ?: ""),
                        color = MV.OnSurfaceDim, fontSize = 11.sp,
                    )
                }
            }
        }
    }
}

/** Map planner split focus to a human-readable muscle list. */
internal fun muscleGroupsFor(focus: String): String = when (focus.lowercase()) {
    "push" -> "Chest · Shoulders · Triceps"
    "pull" -> "Back · Biceps"
    "legs" -> "Quads · Hamstrings · Glutes · Calves"
    "upper" -> "Chest · Back · Shoulders · Arms"
    "lower" -> "Quads · Hamstrings · Glutes · Calves"
    "full_body", "fullbody", "full" -> "Full body — chest, back, legs"
    "rest" -> "Rest day"
    else -> focus.replace('_', ' ')
}
