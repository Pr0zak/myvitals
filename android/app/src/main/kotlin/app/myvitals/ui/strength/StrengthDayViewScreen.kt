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
import app.myvitals.ui.neon.NeonMV
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
    val context = androidx.compose.ui.platform.LocalContext.current
    val neon = settings.neonShellEnabled
    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var notFound by remember { mutableStateOf(false) }

    LaunchedEffect(dateIso) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
        val cacheKey = "strength_day_$dateIso"
        app.myvitals.data.JsonCache.read<StrengthWorkoutDetail>(
            context, cacheKey, StrengthWorkoutDetail::class.java,
        )?.let {
            workout = it.value
            loading = false
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.strengthWorkoutByDate(dateIso) }
            when {
                resp.isSuccessful -> {
                    workout = resp.body()
                    workout?.let {
                        app.myvitals.data.JsonCache.write(
                            context, cacheKey, StrengthWorkoutDetail::class.java, it,
                        )
                    }
                }
                resp.code() == 404 -> if (workout == null) notFound = true
                else -> if (workout == null) error = "Load failed (HTTP ${resp.code()})"
            }
            Timber.i("workout-day-view %s: status=%d hasBody=%s",
                dateIso, resp.code(), workout != null)
        } catch (e: Exception) {
            Timber.w(e, "workout-day-view load failed")
            if (workout == null) error = e.message?.take(160)
        } finally { loading = false }
    }

    val parsed = remember(dateIso) {
        runCatching { LocalDate.parse(dateIso) }.getOrNull()
    }
    val titleFmt = DateTimeFormatter.ofPattern("EEE, MMM d")

    val bg = if (neon) NeonMV.Bg else MV.Bg
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val bad = if (neon) NeonMV.Bad else MV.Red

    Column(Modifier.fillMaxSize().background(bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = ink)
            }
            Text(parsed?.format(titleFmt) ?: dateIso,
                color = ink, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        when {
            loading -> Text("Loading…", color = muted,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = bad,
                modifier = Modifier.padding(16.dp))
            notFound -> Card(
                colors = CardDefaults.cardColors(containerColor = card),
                modifier = Modifier.padding(16.dp).fillMaxWidth(),
            ) {
                Text("No workout recorded for this day.",
                    color = muted,
                    modifier = Modifier.padding(14.dp), fontSize = 13.sp)
            }
            workout != null -> {
                val w = workout!!
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { DayHeader(w, neon) }
                    items(w.exercises, key = { it.id }) { wex ->
                        DayExerciseCard(wex, neon)
                    }
                }
            }
        }
    }
}

@Composable
private fun DayHeader(w: StrengthWorkoutDetail, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val isPreview = w.id < 0 || w.status == "preview"
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(14.dp)) {
            Text(w.splitFocus.replaceFirstChar { it.titlecase() }
                + (if (isPreview) " · Preview" else ""),
                color = ink, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold)
            Text(muscleGroupsFor(w.splitFocus),
                color = muted, fontSize = 12.sp)
            if (w.status != "preview") {
                Spacer(Modifier.height(4.dp))
                val pip = when (w.status) {
                    "completed" -> "Complete"
                    "in_progress" -> "In progress"
                    "skipped" -> "Skipped"
                    "planned" -> "Planned"
                    else -> w.status
                }
                // Neon: status-semantic color (completed=Lime/open, in_progress=
                // Cyan/info, skipped=Bad, planned=Muted). Classic: single dim ink.
                val pipColor = if (neon) when (w.status) {
                    "completed" -> NeonMV.Lime
                    "in_progress" -> NeonMV.Cyan
                    "skipped" -> NeonMV.Bad
                    "planned" -> NeonMV.Muted
                    else -> NeonMV.Muted
                } else MV.OnSurfaceDim
                Text(pip, color = pipColor, fontSize = 11.sp,
                    fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun DayExerciseCard(wex: app.myvitals.sync.StrengthWorkoutExerciseRow, neon: Boolean) {
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val setInk = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    Card(colors = CardDefaults.cardColors(containerColor = card)) {
        Column(Modifier.padding(12.dp)) {
            Text(wex.exerciseId.replace('_', ' '),
                color = ink, fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold)
            val rep = if (wex.targetRepsLow == wex.targetRepsHigh)
                "${wex.targetRepsLow}" else "${wex.targetRepsLow}-${wex.targetRepsHigh}"
            val w = wex.targetWeightLb?.let { " @ ${it}lb" } ?: ""
            Text("${wex.targetSets}×$rep$w",
                color = muted, fontSize = 12.sp)
            // Logged sets (if any)
            for (s in wex.sets.sortedBy { it.setNumber }) {
                if (s.actualReps != null) {
                    Spacer(Modifier.height(2.dp))
                    if (neon && s.rating != null) {
                        // Neon: split the rating off so it carries its own
                        // set-rating semantic color (good/easy=Lime, hard=Amber,
                        // failed=Bad), while the rest stays muted ink.
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "  set ${s.setNumber}: ${s.actualWeightLb ?: "—"}lb × ${s.actualReps}",
                                color = setInk, fontSize = 11.sp,
                            )
                            Text(
                                " · RPE ${s.rating}",
                                color = setRatingColor(s.rating),
                                fontSize = 11.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    } else {
                        Text(
                            "  set ${s.setNumber}: ${s.actualWeightLb ?: "—"}lb × ${s.actualReps}"
                                + (s.rating?.let { " · RPE $it" } ?: ""),
                            color = setInk, fontSize = 11.sp,
                        )
                    }
                }
            }
        }
    }
}

/**
 * Neon set-rating color. The four-button rating ladder is
 * Failed / Hard / Good / Easy; legacy numeric RPE may also flow through.
 * Good/Easy -> Lime, Hard -> Amber (caution), Failed -> Bad. Numeric RPE:
 * high effort (>=9) -> Amber, very high (>=10) -> Bad, else Lime.
 */
private fun setRatingColor(rating: Any?): androidx.compose.ui.graphics.Color {
    val label = rating?.toString()?.trim()?.lowercase() ?: return NeonMV.Muted
    return when (label) {
        "good", "easy" -> NeonMV.Lime
        "hard" -> NeonMV.Amber
        "failed", "fail" -> NeonMV.Bad
        else -> {
            val n = label.toDoubleOrNull()
            when {
                n == null -> NeonMV.Muted
                n >= 10.0 -> NeonMV.Bad
                n >= 9.0 -> NeonMV.Amber
                else -> NeonMV.Lime
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
