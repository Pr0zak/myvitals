package app.myvitals.ui.strength

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthWorkoutExerciseRow
import app.myvitals.ui.neon.NeonNumberFamily
import app.myvitals.ui.neon.NeonScreen
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonCardShape
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

    var catalog by remember { mutableStateOf<Map<String, StrengthExerciseInfo>>(emptyMap()) }
    LaunchedEffect(Unit) {
        // Names and photos. Cached by the repository, so this is usually free;
        // without it the cards fall back to the exercise id, which is legible.
        catalog = runCatching { StrengthRepository(context, settings).catalog() }
            .getOrDefault(emptyMap())
    }

    StrengthDayViewContent(
        dateIso = dateIso,
        workout = workout,
        loading = loading,
        error = error,
        notFound = notFound,
        catalog = catalog,
        backendBaseUrl = settings.backendUrl.trimEnd('/'),
        onBack = onBack,
    )
}

/** Stateless day view — the screenshot tests render this directly. */
@Composable
internal fun StrengthDayViewContent(
    dateIso: String,
    workout: StrengthWorkoutDetail?,
    loading: Boolean,
    error: String?,
    notFound: Boolean,
    catalog: Map<String, StrengthExerciseInfo>,
    backendBaseUrl: String,
    onBack: () -> Unit,
) {
    val parsed = remember(dateIso) { runCatching { LocalDate.parse(dateIso) }.getOrNull() }
    val dateLabel = parsed?.format(DateTimeFormatter.ofPattern("EEE, MMM d")) ?: dateIso
    val title = workout?.let { "${it.splitFocus.replace('_', ' ').replaceFirstChar(Char::titlecase)} day" }
        ?: dateLabel

    NeonScreen(title = title, contentPadding = PaddingValues(bottom = 24.dp), onBack = onBack) {
        when {
            loading && workout == null -> Text("Loading…", color = NeonMV.Muted, fontSize = 14.sp)
            error != null && workout == null -> Text(error, color = NeonMV.Bad, fontSize = 14.sp)
            notFound || workout == null -> DayNote("No workout recorded for this day.")
            else -> {
                val w = workout
                DaySubtitle(w, dateLabel)
                Spacer(Modifier.height(14.dp))
                if (w.sessionSummary != null) {
                    SessionStats(w, w.sessionSummary)
                    Spacer(Modifier.height(16.dp))
                }
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    for (wex in w.exercises.sortedBy { it.orderIndex }) {
                        DayExerciseCard(w, wex, catalog[wex.exerciseId], backendBaseUrl)
                    }
                }
            }
        }
    }
}

@Composable
private fun DayNote(text: String) {
    Box(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape).padding(16.dp),
    ) { Text(text, color = NeonMV.Muted, fontSize = 14.sp) }
}

/** "Mon, Sep 28 · Back · Biceps" and the status pill. */
@Composable
private fun DaySubtitle(w: StrengthWorkoutDetail, dateLabel: String) {
    val preview = w.id < 0 || w.status == "preview"
    val (label, color) = when {
        preview -> "Preview" to NeonMV.Muted
        w.status == "completed" -> "Complete" to NeonMV.Lime
        w.status == "in_progress" -> "In progress" to NeonMV.Cyan
        w.status == "skipped" -> "Skipped" to NeonMV.Amber
        w.status == "planned" -> "Planned" to NeonMV.Muted
        else -> w.status.replaceFirstChar(Char::titlecase) to NeonMV.Muted
    }
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 0.dp)) {
        Text("$dateLabel · ${muscleGroupsFor(w.splitFocus)}", color = NeonMV.Muted, fontSize = 13.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(8.dp))
        Pill(label, color)
    }
}

@Composable
private fun Pill(text: String, color: Color) {
    Text(
        text, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold,
        modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(color.copy(alpha = 0.12f))
            .border(1.dp, color.copy(alpha = 0.35f), RoundedCornerShape(10.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@Composable
private fun DayExerciseCard(
    w: StrengthWorkoutDetail,
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    backendBaseUrl: String,
) {
    val pal = LocalStrengthPalette.current
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    val timed = isTimedExercise(wex, info)
    val done = wex.sets.filter { it.actualReps != null || it.skipped }.sortedBy { it.setNumber }
    val future = w.id < 0 || w.status == "preview" || w.status == "planned"
    Column(
        Modifier.fillMaxWidth().clip(NeonCardShape)
            .background(if (wex.skipped) NeonMV.Card.copy(alpha = 0.6f) else NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ExerciseThumb(wex, info, backendBaseUrl, size = 44.dp, trailingGap = 12.dp) {}
            Column(Modifier.weight(1f)) {
                Text(name, color = if (wex.skipped) NeonMV.Muted else NeonMV.Ink,
                    fontSize = 16.sp, fontWeight = FontWeight.Bold,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(prescriptionLine(wex, info), color = NeonMV.Muted, fontSize = 12.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (wex.skipped) { Spacer(Modifier.width(8.dp)); Pill("Skipped", NeonMV.Amber) }
        }
        when {
            wex.skipped -> {}
            done.isEmpty() -> {
                Spacer(Modifier.height(8.dp))
                Text(if (future) "Planned" else "Not logged", color = NeonMV.Muted, fontSize = 12.sp)
            }
            else -> {
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
                    DayHead("SET", Modifier.width(40.dp))
                    DayHead(if (timed) "" else "LB", Modifier.weight(1f))
                    DayHead(if (timed) "HOLD" else "REPS", Modifier.weight(1f))
                    DayHead("", Modifier.width(64.dp))
                }
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    for (s in done) {
                        val skippedSet = s.actualReps == null
                        Row(
                            Modifier.fillMaxWidth().heightIn(min = 36.dp)
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (skippedSet) Color.Transparent else NeonMV.Bg.copy(alpha = 0.55f))
                                .padding(horizontal = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("${s.setNumber}", color = NeonMV.Muted, fontFamily = NeonNumberFamily,
                                fontSize = 14.sp, fontWeight = FontWeight.Bold, modifier = Modifier.width(40.dp))
                            if (skippedSet) {
                                Text("skipped", color = NeonMV.Muted, fontSize = 13.sp, modifier = Modifier.weight(2f))
                                Spacer(Modifier.width(64.dp))
                            } else {
                                Text(if (timed) "—" else s.actualWeightLb?.let { fmtLbPlain(it) } ?: "BW",
                                    color = NeonMV.Ink, fontFamily = NeonNumberFamily, fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                                Text(if (timed) "${s.actualReps}s" else "${s.actualReps}",
                                    color = NeonMV.Ink, fontFamily = NeonNumberFamily, fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                                Box(Modifier.width(64.dp), contentAlignment = Alignment.CenterEnd) {
                                    // WP-16 set rating (Fail/Hard/Good/Easy), not RPE —
                                    // this line used to print "RPE 4" for a Good set and
                                    // painted a failed set green.
                                    s.rating?.let { Pill(ratingLabel(it), ratingColor(it, pal)) }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DayHead(text: String, modifier: Modifier) {
    Text(text, color = NeonMV.Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold,
        letterSpacing = 1.2.sp, modifier = modifier)
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
