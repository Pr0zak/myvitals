package app.myvitals.ui.strength

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateMapOf
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.LogSetRequest
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthReviewBody
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutExerciseRow
import app.myvitals.ui.MV
import app.myvitals.update.Notifier
import coil.compose.AsyncImage
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import timber.log.Timber

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun StrengthTodayScreen(
    settings: SettingsRepository,
    onOpenHistory: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repo = remember(settings) { StrengthRepository(context, settings) }

    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var catalog by remember { mutableStateOf<Map<String, StrengthExerciseInfo>>(emptyMap()) }
    var recoveryReason by remember { mutableStateOf<String?>(null) }
    var history by remember { mutableStateOf<List<app.myvitals.sync.StrengthWorkoutSummary>>(emptyList()) }
    var daysPerWeek by remember { mutableStateOf(3) }
    var loading by remember { mutableStateOf(true) }
    var generating by remember { mutableStateOf(false) }
    var deferring by remember { mutableStateOf(false) }
    var swapWexId by remember { mutableStateOf<Long?>(null) }
    var swapping by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    var review by remember { mutableStateOf<StrengthReviewBody?>(null) }
    var reviewLoading by remember { mutableStateOf(false) }
    var reviewError by remember { mutableStateOf<String?>(null) }

    // Per-set transient input + rest-timer state
    val setInputs = remember { mutableStateMapOf<String, SetInput>() }
    var restEndsAt by remember { mutableLongStateOf(0L) }
    var restTotal by remember { mutableLongStateOf(0L) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun reload() {
        loading = true
        error = null
        try {
            val plan = repo.today()
            val rec = if (plan == null) repo.recovery() else null
            workout = plan
            recoveryReason = rec?.restDayReason
            if (catalog.isEmpty()) catalog = repo.catalog()
            history = repo.listHistory()
            try { daysPerWeek = repo.equipment().payload.training.daysPerWeek } catch (_: Exception) {}
        } catch (e: Exception) {
            Timber.w(e, "today reload failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(Unit) { reload() }
    LaunchedEffect(Unit) {
        while (true) { delay(1000); nowMs = System.currentTimeMillis() }
    }

    val restRemainingS = remember(nowMs, restEndsAt) {
        derivedStateOf { ((restEndsAt - nowMs) / 1000).coerceAtLeast(0L) }
    }

    // Fire haptic + notification at the moment the timer reaches 0.
    var lastNotifiedFor by remember { mutableLongStateOf(0L) }
    LaunchedEffect(restRemainingS.value, restEndsAt) {
        if (restEndsAt > 0L && restRemainingS.value <= 0L && restEndsAt != lastNotifiedFor) {
            lastNotifiedFor = restEndsAt
            Notifier.postRestTimerDone(context, (restTotal / 1000).toInt())
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MV.Bg)
            .padding(horizontal = 16.dp),
    ) {
        // Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text(
                    "STRENGTH",
                    color = MV.OnSurfaceVariant,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 2.sp,
                )
                Text(
                    workout?.splitFocus?.replace('_', ' ')?.replaceFirstChar(Char::titlecase)
                        ?: "Today",
                    color = MV.OnSurface,
                    fontSize = 22.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            TextButton(onClick = onOpenHistory) {
                Icon(Icons.Filled.History, contentDescription = null, tint = MV.OnSurfaceVariant)
                Spacer(Modifier.width(4.dp))
                Text("History", color = MV.OnSurfaceVariant)
            }
        }

        if (loading) {
            Text("Loading…", color = MV.OnSurfaceVariant, modifier = Modifier.padding(16.dp))
            return@Column
        }

        error?.let { Text(it, color = MV.Red, modifier = Modifier.padding(8.dp)) }

        // States: rest day, no plan, or plan
        if (workout == null) {
            if (recoveryReason != null) {
                RestDayCard(
                    reason = recoveryReason!!,
                    generating = generating,
                    onForceGenerate = {
                        scope.launch {
                            generating = true
                            try { workout = repo.regenerate(true); reload() }
                            catch (e: Exception) { error = e.message?.take(160) }
                            finally { generating = false }
                        }
                    },
                )
            } else {
                Button(
                    onClick = {
                        scope.launch {
                            generating = true
                            try { workout = repo.regenerate(false); reload() }
                            catch (e: Exception) { error = e.message?.take(160) }
                            finally { generating = false }
                        }
                    },
                    enabled = !generating,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(if (generating) "Generating…" else "Generate today's plan")
                }
            }
            return@Column
        }

        val plan = workout!!

        // Sticky-ish rest timer
        if (restRemainingS.value > 0 || restTotal > 0L) {
            RestTimerBar(
                remainingS = restRemainingS.value,
                totalS = restTotal / 1000,
                onAdd30 = { restEndsAt += 30_000 },
                onSkip = { restEndsAt = nowMs; restTotal = 0L },
            )
            Spacer(Modifier.height(6.dp))
        }

        // 7-day strip
        WeekStrip(
            history = history,
            daysPerWeek = daysPerWeek,
            todayStatus = plan.status,
        )
        Spacer(Modifier.height(8.dp))

        // Context line
        ContextRow(plan, plan.exercises.flatMap { it.sets }.size)

        Spacer(Modifier.height(4.dp))

        if (plan.status == "planned" || plan.status == "in_progress") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = {
                        scope.launch {
                            deferring = true
                            try { repo.deferWorkout(plan.id); reload() }
                            catch (e: Exception) { error = e.message?.take(160) }
                            finally { deferring = false }
                        }
                    },
                    enabled = !deferring,
                ) {
                    Icon(Icons.Filled.SkipNext, contentDescription = null)
                    Spacer(Modifier.width(4.dp))
                    Text(if (deferring) "Deferring…" else "Skip workout day")
                }
            }
            Spacer(Modifier.height(8.dp))
        }

        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(plan.exercises, key = { it.id }) { wex ->
                val canSwap = wex.sets.none { it.actualReps != null && !it.skipped }
                ExerciseCard(
                    wex = wex,
                    info = catalog[wex.exerciseId],
                    inputs = setInputs,
                    canSwap = canSwap,
                    onLogSet = { setNum, weight, reps, rating ->
                        scope.launch {
                            val ok = repo.logSet(LogSetRequest(
                                workoutExerciseId = wex.id,
                                setNumber = setNum,
                                targetWeightLb = wex.targetWeightLb,
                                targetReps = wex.targetRepsLow,
                                actualWeightLb = weight,
                                actualReps = reps,
                                rating = rating,
                            ))
                            if (ok) {
                                // Start rest timer locally
                                restTotal = wex.targetRestS * 1000L
                                restEndsAt = System.currentTimeMillis() + restTotal
                            }
                            reload()
                        }
                    },
                    onYouTube = { slug, name ->
                        openYouTube(context, slug, name)
                    },
                    onSwap = { swapWexId = wex.id },
                )
            }
            item {
                if (plan.status != "completed") {
                    Button(
                        onClick = {
                            scope.launch {
                                try { workout = repo.completeWorkout(plan.id); reload() }
                                catch (e: Exception) { error = e.message?.take(160) }
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 12.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = MV.Green),
                    ) { Text("Complete workout") }
                }
                if (plan.status == "completed") {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(
                                "✓ Workout complete — see you tomorrow",
                                color = MV.Green, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                            )
                            Spacer(Modifier.height(12.dp))
                            ReviewBlock(
                                review = review,
                                loading = reviewLoading,
                                error = reviewError,
                                onLoad = {
                                    scope.launch {
                                        reviewLoading = true
                                        reviewError = null
                                        try { review = repo.aiReview(plan.id).review }
                                        catch (e: Exception) {
                                            reviewError = e.message?.take(160)
                                        } finally { reviewLoading = false }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }

    // Swap bottom sheet
    if (swapWexId != null && workout != null) {
        val wex = workout!!.exercises.firstOrNull { it.id == swapWexId }
        val current = wex?.let { catalog[it.exerciseId] }
        if (wex != null && current != null) {
            val inWorkout = workout!!.exercises.map { it.exerciseId }.toSet()
            val alternatives = catalog.values
                .filter {
                    it.id != wex.exerciseId
                        && it.id !in inWorkout
                        && (it.primaryMuscle == current.primaryMuscle
                            || it.movementPattern == current.movementPattern)
                }
                .sortedWith(compareBy(
                    { if (it.movementPattern == current.movementPattern) 0 else 1 },
                    { it.name },
                ))
                .take(12)
            androidx.compose.material3.ModalBottomSheet(
                onDismissRequest = { swapWexId = null },
                containerColor = MV.SurfaceContainer,
            ) {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Text(
                        "Swap exercise",
                        color = MV.OnSurface, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "Currently: ${current.name}",
                        color = MV.OnSurfaceVariant, fontSize = 12.sp,
                        modifier = Modifier.padding(top = 2.dp, bottom = 8.dp),
                    )
                    if (alternatives.isEmpty()) {
                        Text("No alternatives in your equipment for this slot.",
                            color = MV.OnSurfaceVariant, fontSize = 13.sp)
                    } else {
                        alternatives.forEach { alt ->
                            Card(
                                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainerLow),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp)
                                    .clickable(enabled = !swapping) {
                                        scope.launch {
                                            swapping = true
                                            try {
                                                repo.swapExercise(wex.id, alt.id)
                                                reload()
                                                swapWexId = null
                                            } catch (e: Exception) {
                                                error = e.message?.take(160)
                                            } finally { swapping = false }
                                        }
                                    },
                            ) {
                                Column(modifier = Modifier.padding(12.dp)) {
                                    Text(alt.name, color = MV.OnSurface, fontSize = 14.sp,
                                        fontWeight = FontWeight.SemiBold)
                                    Text(
                                        "${alt.movementPattern.replace('_', ' ')} · ${alt.primaryMuscle}",
                                        color = MV.OnSurfaceVariant, fontSize = 11.sp,
                                    )
                                }
                            }
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }
}

// ── Pieces ──────────────────────────────────────────────────────

@Composable
private fun RestDayCard(reason: String, generating: Boolean, onForceGenerate: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Rest day recommended",
                color = MV.Amber, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Text(reason, color = MV.OnSurfaceVariant, fontSize = 14.sp)
            Spacer(Modifier.height(12.dp))
            OutlinedButton(
                onClick = onForceGenerate,
                enabled = !generating,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (generating) "Generating…" else "Generate anyway") }
        }
    }
}

@Composable
private fun ContextRow(plan: StrengthWorkoutDetail, totalSets: Int) {
    val completedSets = plan.exercises.flatMap { it.sets }
        .count { !it.skipped && it.actualReps != null }
    val target = plan.exercises.sumOf { it.targetSets }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ContextChip("$completedSets/$target sets")
        plan.recoveryScoreUsed?.let { ContextChip("recovery ${it.toInt()}") }
        plan.sleepHUsed?.let { ContextChip("sleep ${"%.1f".format(it)}h") }
    }
}

@Composable
private fun ContextChip(text: String) {
    Box(
        Modifier
            .clip(RoundedCornerShape(50))
            .background(MV.SurfaceContainerLow)
            .border(1.dp, MV.OutlineVariant, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) { Text(text, color = MV.OnSurfaceVariant, fontSize = 12.sp) }
}

@Composable
private fun RestTimerBar(
    remainingS: Long, totalS: Long,
    onAdd30: () -> Unit, onSkip: () -> Unit,
) {
    val done = remainingS <= 0
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (done) MV.Green.copy(alpha = 0.18f) else MV.BrandRed.copy(alpha = 0.18f)
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            val mm = remainingS / 60
            val ss = (remainingS % 60).toString().padStart(2, '0')
            Text(
                "$mm:$ss",
                color = if (done) MV.Green else MV.BrandRed,
                fontSize = 28.sp, fontWeight = FontWeight.Bold,
            )
            Text("/ ${totalS / 60}:${(totalS % 60).toString().padStart(2, '0')}",
                color = MV.OnSurfaceVariant)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onAdd30) {
                Icon(Icons.Filled.Add, contentDescription = null, tint = MV.OnSurface)
                Text(" 30s", color = MV.OnSurface)
            }
            TextButton(onClick = onSkip) {
                Icon(Icons.Filled.SkipNext, contentDescription = null, tint = MV.OnSurface)
                Text(" Skip", color = MV.OnSurface)
            }
        }
    }
}

private data class SetInput(
    var weight: String = "",
    var reps: String = "",
    var rating: Int? = null,
)

@Composable
private fun ExerciseCard(
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    inputs: androidx.compose.runtime.snapshots.SnapshotStateMap<String, SetInput>,
    canSwap: Boolean,
    onLogSet: (setNum: Int, weight: Double?, reps: Int?, rating: Int?) -> Unit,
    onYouTube: (slug: String, name: String) -> Unit,
    onSwap: () -> Unit,
) {
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    val nextSet = (1..wex.targetSets).firstOrNull { n ->
        wex.sets.none { it.setNumber == n && (it.actualReps != null || it.skipped) }
    }
    val done = nextSet == null
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (done) MV.SurfaceContainerLow else MV.SurfaceContainer
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "${wex.orderIndex + 1}. $name",
                        color = MV.OnSurface, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                    )
                    val rep = if (wex.targetRepsLow == wex.targetRepsHigh)
                        "${wex.targetRepsLow}" else "${wex.targetRepsLow}-${wex.targetRepsHigh}"
                    val w = wex.targetWeightLb?.let { " @ ${it}lb" } ?: ""
                    Text(
                        "${wex.targetSets}×$rep$w  ·  ${wex.targetRestS}s rest" +
                                (wex.supersetId?.let { " · superset $it" } ?: ""),
                        color = MV.OnSurfaceVariant, fontSize = 12.sp,
                    )
                }
                if (info?.imageFront != null) {
                    val baseUrl = LocalContext.current
                        .getSharedPreferences("myvitals_prefs", android.content.Context.MODE_PRIVATE)
                        .getString("backend_url", "")?.trimEnd('/') ?: ""
                    if (baseUrl.isNotEmpty()) {
                        AsyncImage(
                            model = baseUrl + info.imageFront,
                            contentDescription = name,
                            modifier = Modifier
                                .size(64.dp)
                                .clip(RoundedCornerShape(8.dp)),
                        )
                    }
                }
            }

            Spacer(Modifier.height(6.dp))
            Row {
                TextButton(onClick = { onYouTube(wex.exerciseId, name) }) {
                    Text("YouTube ↗", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                }
                if (canSwap) {
                    TextButton(onClick = onSwap) {
                        Icon(Icons.Filled.SwapHoriz, contentDescription = null,
                            tint = MV.OnSurfaceVariant, modifier = Modifier.size(14.dp))
                        Text(" Swap", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                    }
                }
            }
            // Sets
            for (n in 1..wex.targetSets) {
                val key = "${wex.id}-$n"
                val logged = wex.sets.firstOrNull { it.setNumber == n && it.actualReps != null }
                if (logged != null) {
                    LoggedSetRow(n, logged.actualWeightLb, logged.actualReps ?: 0, logged.rating ?: 0)
                } else if (n == nextSet) {
                    val input = inputs.getOrPut(key) { SetInput(
                        weight = wex.targetWeightLb?.toString().orEmpty(),
                        reps = wex.targetRepsLow.toString(),
                    ) }
                    SetEntryRow(
                        n = n, input = input,
                        onWeight = { inputs[key] = input.copy(weight = it) },
                        onReps = { inputs[key] = input.copy(reps = it) },
                        onRating = { inputs[key] = input.copy(rating = it) },
                        canLog = input.rating != null && input.reps.isNotBlank(),
                        onLog = {
                            onLogSet(
                                n,
                                input.weight.toDoubleOrNull(),
                                input.reps.toIntOrNull(),
                                input.rating,
                            )
                            inputs.remove(key)
                        },
                    )
                } else {
                    PendingSetRow(n)
                }
            }
        }
    }
}

@Composable
private fun LoggedSetRow(n: Int, weightLb: Double?, reps: Int, rating: Int) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("$n", color = MV.OnSurfaceVariant, modifier = Modifier.width(20.dp))
        Text(
            "${weightLb ?: "—"}lb × $reps",
            color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(1f),
        )
        Text("RPE $rating", color = ratingColor(rating), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.width(8.dp))
        Text("✓", color = MV.Green, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun PendingSetRow(n: Int) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("$n", color = MV.OnSurfaceDim, modifier = Modifier.width(20.dp))
        Text("waiting", color = MV.OnSurfaceDim, fontSize = 13.sp)
    }
}

@Composable
private fun SetEntryRow(
    n: Int, input: SetInput,
    onWeight: (String) -> Unit, onReps: (String) -> Unit,
    onRating: (Int) -> Unit, canLog: Boolean, onLog: () -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Set $n", color = MV.OnSurface, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.width(56.dp))
            OutlinedTextField(
                value = input.weight, onValueChange = onWeight,
                label = { Text("lb", fontSize = 11.sp) },
                modifier = Modifier.weight(1f),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
            )
            Spacer(Modifier.width(8.dp))
            OutlinedTextField(
                value = input.reps, onValueChange = onReps,
                label = { Text("reps", fontSize = 11.sp) },
                modifier = Modifier.weight(1f),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
            )
        }
        Row(
            Modifier.fillMaxWidth().padding(top = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            for (r in 1..5) {
                val on = input.rating == r
                Box(
                    Modifier
                        .weight(1f)
                        .height(40.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (on) ratingColor(r) else MV.SurfaceContainerLow)
                        .border(1.dp, if (on) ratingColor(r) else MV.OutlineVariant, RoundedCornerShape(8.dp))
                        .clickable { onRating(r) },
                    contentAlignment = Alignment.Center,
                ) {
                    Text("$r", color = if (on) MV.OnSurface else MV.OnSurfaceVariant,
                        fontWeight = FontWeight.Bold)
                }
            }
        }
        Text(
            "1 Failed · 2 Very hard · 3 Hard · 4 Moderate · 5 Easy",
            color = MV.OnSurfaceDim, fontSize = 10.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        )
        Button(
            onClick = onLog, enabled = canLog,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = MV.BrandRed, contentColor = MV.OnSurface,
            ),
        ) { Text("Log set $n") }
    }
}

@Composable
private fun ReviewBlock(
    review: StrengthReviewBody?,
    loading: Boolean,
    error: String?,
    onLoad: () -> Unit,
) {
    when {
        loading -> Text("Generating review…", color = MV.OnSurfaceVariant)
        error != null -> Text(error, color = MV.Red, fontSize = 12.sp)
        review == null -> OutlinedButton(
            onClick = onLoad, modifier = Modifier.fillMaxWidth(),
        ) { Text("Get AI workout review") }
        else -> Column {
            Text(
                review.headline,
                color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            )
            for (h in review.highlights) {
                Text("• $h", color = MV.OnSurfaceVariant, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp))
            }
            for (c in review.concerns) {
                Text("⚠ $c", color = MV.Amber, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp))
            }
            Spacer(Modifier.height(6.dp))
            Text(
                "Next session: ${review.nextSessionSuggestion}",
                color = MV.OnSurface, fontSize = 12.sp, fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun WeekStrip(
    history: List<app.myvitals.sync.StrengthWorkoutSummary>,
    daysPerWeek: Int,
    todayStatus: String,
) {
    val today = java.time.LocalDate.now()
    val statusByDate = history.associate { it.date to it.status }
    // Mon-first weekday pattern; mirrors web strip
    val pattern = when (daysPerWeek) {
        2 -> setOf(0, 3); 3 -> setOf(0, 2, 4); 4 -> setOf(0, 1, 3, 4)
        5 -> setOf(0, 1, 2, 3, 4); 6 -> setOf(0, 1, 2, 3, 4, 5)
        else -> setOf(0, 2, 4)
    }
    fun monFirst(jsDow: Int) = (jsDow + 6) % 7

    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for (offset in -3..3) {
            val d = today.plusDays(offset.toLong())
            val isToday = offset == 0
            val iso = d.toString()
            val historyStatus = statusByDate[iso]
            val effectiveStatus = if (isToday) todayStatus else historyStatus
            val isPast = d.isBefore(today)
            val projected = !isPast && effectiveStatus == null
                && pattern.contains(monFirst(d.dayOfWeek.value % 7))

            val dotColor = when {
                effectiveStatus == "completed" -> Color(0xFF22C55E)
                effectiveStatus == "in_progress" -> MV.Amber
                effectiveStatus == "skipped" -> MV.OnSurfaceVariant
                effectiveStatus == "planned" -> MV.BrandRed
                projected -> Color.Transparent
                else -> MV.OnSurfaceDim
            }

            Column(
                modifier = Modifier
                    .weight(1f)
                    .clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
                    .border(
                        1.dp,
                        if (isToday) MV.BrandRed else MV.OutlineVariant,
                        androidx.compose.foundation.shape.RoundedCornerShape(8.dp),
                    )
                    .background(MV.SurfaceContainerLow)
                    .padding(vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    if (isToday) "Today" else d.dayOfWeek.name.take(3),
                    color = if (isToday) MV.OnSurface else MV.OnSurfaceVariant,
                    fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
                )
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(dotColor)
                        .then(
                            if (projected) Modifier.border(
                                1.5.dp, MV.BrandRed, CircleShape,
                            ) else Modifier
                        ),
                )
            }
        }
    }
}

private fun ratingColor(r: Int) = when (r) {
    1 -> MV.Red
    2 -> androidx.compose.ui.graphics.Color(0xFFF97316)
    3 -> MV.Amber
    4 -> androidx.compose.ui.graphics.Color(0xFF84CC16)
    5 -> MV.Green
    else -> MV.OnSurfaceDim
}

private fun openYouTube(context: android.content.Context, slug: String, name: String) {
    val q = Uri.encode("$name form")
    val app = Intent(Intent.ACTION_VIEW, Uri.parse("vnd.youtube://results?search_query=$q"))
        .setPackage("com.google.android.youtube")
    val web = Intent(Intent.ACTION_VIEW,
        Uri.parse("https://www.youtube.com/results?search_query=$q"))
    try { context.startActivity(app) } catch (_: Exception) {
        try { context.startActivity(web) } catch (e: Exception) {
            Timber.w(e, "no browser to open YouTube fallback")
        }
    }
}
