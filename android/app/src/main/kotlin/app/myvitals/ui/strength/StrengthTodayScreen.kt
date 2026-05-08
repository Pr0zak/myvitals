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
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.QueryStats
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.IconButton
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
import androidx.compose.material.icons.outlined.Block
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Restore
import androidx.compose.material.icons.outlined.ThumbDownOffAlt
import app.myvitals.sync.BackendClient
import app.myvitals.sync.ExercisePrefBody
import app.myvitals.sync.LogSetRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
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
    onOpenCatalog: () -> Unit = {},
    onOpenTrainingPrefs: () -> Unit = {},
    onOpenDay: (dateIso: String) -> Unit = {},
    onOpenCharts: () -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repo = remember(settings) { StrengthRepository(context, settings) }

    // Keep the screen awake during the active workout — phones go to
    // sleep mid-set otherwise. The flag is cleared on screen exit.
    androidx.compose.runtime.DisposableEffect(Unit) {
        val activity = context as? android.app.Activity
        activity?.window?.addFlags(
            android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
        )
        onDispose {
            activity?.window?.clearFlags(
                android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
            )
        }
    }

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
        // Compact header — single 36dp row, eyebrow + title inline,
        // overflow menu replaces the three icon buttons + Charts/Skip row.
        var headerMenuOpen by remember { mutableStateOf(false) }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "WORKOUT",
                color = MV.OnSurfaceVariant,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.6.sp,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                workout?.splitFocus?.replace('_', ' ')?.replaceFirstChar(Char::titlecase)
                    ?: "Today",
                color = MV.OnSurface,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            // Quick stats pip when a plan exists
            workout?.let { p ->
                val total = p.exercises.sumOf { it.targetSets }
                val done = p.exercises.flatMap { it.sets }
                    .count { it.actualReps != null || it.skipped }
                Box(
                    Modifier.clip(RoundedCornerShape(50))
                        .background(MV.SurfaceContainerLow)
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                ) {
                    Text("$done/$total sets",
                        color = MV.OnSurfaceVariant, fontSize = 11.sp)
                }
                Spacer(Modifier.width(4.dp))
            }
            Box {
                IconButton(onClick = { headerMenuOpen = true }) {
                    Icon(
                        Icons.Outlined.MoreVert,
                        contentDescription = "More",
                        tint = MV.OnSurfaceVariant,
                    )
                }
                androidx.compose.material3.DropdownMenu(
                    expanded = headerMenuOpen,
                    onDismissRequest = { headerMenuOpen = false },
                ) {
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("Catalog") },
                        leadingIcon = { Icon(Icons.Filled.MenuBook, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = { headerMenuOpen = false; onOpenCatalog() },
                    )
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("Charts") },
                        leadingIcon = { Icon(Icons.Filled.QueryStats, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = { headerMenuOpen = false; onOpenCharts() },
                    )
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("History") },
                        leadingIcon = { Icon(Icons.Filled.History, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = { headerMenuOpen = false; onOpenHistory() },
                    )
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("Training prefs") },
                        leadingIcon = { Icon(Icons.Filled.Tune, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = { headerMenuOpen = false; onOpenTrainingPrefs() },
                    )
                    if (workout?.status == "planned" || workout?.status == "in_progress") {
                        androidx.compose.material3.DropdownMenuItem(
                            text = { Text("Skip workout day",
                                color = MV.BrandRed) },
                            leadingIcon = { Icon(Icons.Filled.SkipNext, null,
                                modifier = Modifier.size(16.dp), tint = MV.BrandRed) },
                            onClick = {
                                headerMenuOpen = false
                                scope.launch {
                                    deferring = true
                                    try { repo.deferWorkout(workout!!.id); reload() }
                                    catch (e: Exception) { error = e.message?.take(160) }
                                    finally { deferring = false }
                                }
                            },
                        )
                    }
                }
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
            onDayClick = { dateIso -> onOpenDay(dateIso) },
        )
        Spacer(Modifier.height(6.dp))

        // ContextRow / Why / Variety-nudge / Charts / History / Skip
        // were all removed from the top. Why + Variety nudge are now
        // appended *below* the exercise list (search "// Bottom-of-screen
        // helpers"); the rest moved into the header overflow menu.

        if (plan.status == "skipped") {
            Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainerLow),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Skipped today's workout day.",
                            color = MV.OnSurface, fontWeight = FontWeight.SemiBold)
                        Text("Tomorrow will generate fresh.",
                            color = MV.OnSurfaceVariant, fontSize = 12.sp)
                    }
                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                deferring = true
                                try { repo.unskipWorkout(plan.id); reload() }
                                catch (e: Exception) { error = e.message?.take(160) }
                                finally { deferring = false }
                            }
                        },
                        enabled = !deferring,
                    ) {
                        Icon(Icons.Filled.Refresh, contentDescription = null)
                        Spacer(Modifier.width(4.dp))
                        Text(if (deferring) "Restoring…" else "Undo")
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }

        // Float incomplete exercises to the top so the active set card
        // is always visible without scrolling. Within a superset, the
        // partner with FEWER completed sets surfaces first — so after
        // you log set 1 of A, set 1 of B floats up, then set 2 of A,
        // and so on. Done exercises drop to the bottom for reference.
        val orderedExercises = remember(plan.exercises) {
            fun completedCount(w: app.myvitals.sync.StrengthWorkoutExerciseRow): Int =
                w.sets.count { it.actualReps != null || it.skipped }
            fun isDone(w: app.myvitals.sync.StrengthWorkoutExerciseRow): Boolean =
                completedCount(w) >= w.targetSets

            val incomplete = plan.exercises.filter { !isDone(it) }
            val complete = plan.exercises.filter { isDone(it) }
                .sortedBy { it.orderIndex }

            // Group incomplete by superset id (null = singleton group),
            // alternate within each group by completed-count, then sort
            // groups by their lowest-orderIndex member.
            val groupedIncomplete = incomplete
                .groupBy { it.supersetId }
                .map { (_, exs) ->
                    exs.sortedWith(
                        compareBy({ completedCount(it) }, { it.orderIndex }),
                    )
                }
                .sortedBy { it.first().orderIndex }
                .flatten()

            groupedIncomplete + complete
        }
        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = loading,
            onRefresh = { scope.launch { reload() } },
            modifier = Modifier.weight(1f),
        ) {
        LazyColumn(
            contentPadding = PaddingValues(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(orderedExercises, key = { it.id }) { wex ->
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
                                // Within-round rest (35s) if this is a superset and
                                // the partner hasn't completed this set yet; full
                                // target_rest_s otherwise.
                                var restMs = wex.targetRestS * 1000L
                                val ssId = wex.supersetId
                                if (ssId != null) {
                                    val partner = workout?.exercises?.firstOrNull {
                                        it.supersetId == ssId && it.id != wex.id
                                    }
                                    val partnerDone = partner?.sets?.any {
                                        it.setNumber == setNum && it.actualReps != null && !it.skipped
                                    } ?: false
                                    if (!partnerDone) restMs = 35_000L
                                }
                                restTotal = restMs
                                restEndsAt = System.currentTimeMillis() + restTotal
                            }
                            reload()
                        }
                    },
                    onYouTube = { slug, name ->
                        openYouTube(context, slug, name)
                    },
                    onSwap = { swapWexId = wex.id },
                    onSetPref = { pref ->
                        scope.launch {
                            try {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                kotlinx.coroutines.withContext(
                                    kotlinx.coroutines.Dispatchers.IO
                                ) {
                                    api.setExercisePref(
                                        wex.exerciseId, ExercisePrefBody(pref),
                                    )
                                }
                                Timber.i("exercise pref set: %s = %s",
                                    wex.exerciseId, pref)
                                error = null
                            } catch (e: Exception) {
                                Timber.w(e, "set exercise pref failed")
                                error = "Pref save failed: ${e.message?.take(80)}"
                            }
                        }
                    },
                    partnerName = wex.supersetId?.let { ss ->
                        plan.exercises.firstOrNull { it.supersetId == ss && it.id != wex.id }
                            ?.let { catalog[it.exerciseId]?.name ?: it.exerciseId.replace('_', ' ') }
                    },
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
            // Bottom-of-screen helpers — Why + Variety nudge live here
            // (collapsed by default) instead of as persistent top chrome.
            if (plan.status == "planned" || plan.status == "in_progress") {
                item {
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Box(Modifier.weight(1f)) {
                            WhyWorkoutCard(settings = settings, workoutId = plan.id)
                        }
                        Box(Modifier.weight(1f)) {
                            VarietyNudgeCard(
                                settings = settings,
                                workoutId = plan.id,
                                onAccept = { targetExId, replacementExId ->
                                    val wex2 = plan.exercises.firstOrNull {
                                        it.exerciseId == targetExId
                                    }
                                    if (wex2 != null) {
                                        scope.launch {
                                            try {
                                                val api = BackendClient.create(
                                                    settings.backendUrl,
                                                    settings.bearerToken,
                                                )
                                                kotlinx.coroutines.withContext(
                                                    kotlinx.coroutines.Dispatchers.IO,
                                                ) {
                                                    api.swapStrengthExercise(
                                                        wex2.id,
                                                        app.myvitals.sync.SwapBody(
                                                            replacementExId,
                                                        ),
                                                    )
                                                }
                                                reload()
                                            } catch (e: Exception) {
                                                Timber.w(e, "nudge swap failed")
                                                error = "Swap failed: " +
                                                    "${e.message?.take(80)}"
                                            }
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
        }  // end PullToRefreshBox
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
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "${plan.splitFocus.replaceFirstChar { it.titlecase() }} day · "
                + muscleGroupsFor(plan.splitFocus),
            color = MV.OnSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ContextChip("$completedSets/$target sets")
            plan.recoveryScoreUsed?.let { ContextChip("recovery ${it.toInt()}") }
            plan.sleepHUsed?.let { ContextChip("sleep ${"%.1f".format(it)}h") }
        }
    }
}

@Composable
internal fun WhyWorkoutCard(
    settings: SettingsRepository,
    workoutId: Long,
) {
    var expanded by remember(workoutId) { mutableStateOf(false) }
    var explain by remember(workoutId) { mutableStateOf<app.myvitals.sync.StrengthExplain?>(null) }
    var loading by remember(workoutId) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainerLow),
        modifier = Modifier.fillMaxWidth().clickable {
            expanded = !expanded
            if (expanded && explain == null && !loading && settings.isConfigured()) {
                loading = true
                scope.launch {
                    try {
                        val api = BackendClient.create(
                            settings.backendUrl, settings.bearerToken,
                        )
                        explain = withContext(Dispatchers.IO) {
                            api.strengthExplain(workoutId)
                        }
                    } catch (e: Exception) {
                        Timber.w(e, "explain workout failed")
                    } finally { loading = false }
                }
            }
        },
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Why this workout?",
                    color = MV.OnSurface, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f))
                Text(if (expanded) "▾" else "▸",
                    color = MV.OnSurfaceVariant, fontSize = 14.sp)
            }
            if (expanded) {
                Spacer(Modifier.height(6.dp))
                if (loading && explain == null) {
                    Text("…", color = MV.OnSurfaceDim, fontSize = 12.sp)
                } else if (explain != null) {
                    Spacer(Modifier.height(2.dp))
                    val lines = listOf(
                        explain!!.whySplit, explain!!.whyExercises, explain!!.whyTargets,
                    )
                    for ((i, line) in lines.withIndex()) {
                        Text(
                            // strip <strong> for plain phone display
                            line.replace("<strong>", "").replace("</strong>", ""),
                            color = MV.OnSurfaceVariant, fontSize = 12.sp,
                        )
                        if (i < lines.lastIndex) Spacer(Modifier.height(4.dp))
                    }
                } else {
                    Text("No rationale available.",
                        color = MV.OnSurfaceDim, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
internal fun VarietyNudgeCard(
    settings: SettingsRepository,
    workoutId: Long,
    onAccept: (targetExerciseId: String, replacementExerciseId: String) -> Unit,
) {
    var expanded by remember(workoutId) { mutableStateOf(false) }
    var swaps by remember(workoutId) {
        mutableStateOf<List<app.myvitals.sync.StrengthSwapSuggestion>?>(null)
    }
    var loading by remember(workoutId) { mutableStateOf(false) }
    var failed by remember(workoutId) { mutableStateOf(false) }
    val dismissed = remember(workoutId) { mutableStateMapOf<String, Boolean>() }
    val scope = rememberCoroutineScope()

    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainerLow),
        modifier = Modifier.fillMaxWidth().clickable {
            expanded = !expanded
            if (expanded && swaps == null && !loading && settings.isConfigured()) {
                loading = true
                failed = false
                scope.launch {
                    try {
                        val api = BackendClient.create(
                            settings.backendUrl, settings.bearerToken,
                        )
                        val resp = withContext(Dispatchers.IO) {
                            api.strengthNudge(workoutId)
                        }
                        swaps = resp.nudge.swaps
                    } catch (e: Exception) {
                        Timber.w(e, "variety nudge failed")
                        failed = true
                        swaps = emptyList()
                    } finally { loading = false }
                }
            }
        },
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("✦ Variety nudge",
                    color = MV.OnSurface, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f))
                val visibleCount = swaps?.count { dismissed[it.targetExerciseId] != true } ?: 0
                if (!expanded && visibleCount > 0) {
                    Text("$visibleCount", color = MV.OnSurfaceVariant, fontSize = 12.sp,
                        modifier = Modifier.padding(end = 6.dp))
                }
                Text(if (expanded) "▾" else "▸",
                    color = MV.OnSurfaceVariant, fontSize = 14.sp)
            }
            if (expanded) {
                Spacer(Modifier.height(6.dp))
                when {
                    loading -> Text("Thinking…", color = MV.OnSurfaceDim, fontSize = 12.sp)
                    failed -> Text("AI nudge unavailable. Check Settings → AI.",
                        color = MV.OnSurfaceDim, fontSize = 12.sp)
                    swaps == null -> {}
                    swaps!!.isEmpty() -> Text("Plan looks balanced — no swaps suggested.",
                        color = MV.OnSurfaceDim, fontSize = 12.sp)
                    else -> {
                        for (s in swaps!!) {
                            if (dismissed[s.targetExerciseId] == true) continue
                            Spacer(Modifier.height(4.dp))
                            Column(
                                Modifier.fillMaxWidth()
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(MV.SurfaceContainer)
                                    .padding(10.dp),
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(s.targetExerciseId.replace('_', ' ')
                                            .replaceFirstChar(Char::titlecase),
                                        color = MV.OnSurface, fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold)
                                    Text(" → ", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                                    Text(s.replacementExerciseId.replace('_', ' ')
                                            .replaceFirstChar(Char::titlecase),
                                        color = MV.Green, fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold)
                                }
                                Spacer(Modifier.height(2.dp))
                                Text(s.reason, color = MV.OnSurfaceVariant, fontSize = 11.sp)
                                Spacer(Modifier.height(6.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Button(
                                        onClick = {
                                            onAccept(s.targetExerciseId, s.replacementExerciseId)
                                            dismissed[s.targetExerciseId] = true
                                        },
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = MV.BrandRed,
                                            contentColor = MV.OnSurface,
                                        ),
                                    ) { Text("Accept", fontSize = 11.sp) }
                                    OutlinedButton(
                                        onClick = { dismissed[s.targetExerciseId] = true },
                                    ) { Text("Dismiss", fontSize = 11.sp) }
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
    onSetPref: (String) -> Unit = {},
    partnerName: String? = null,
) {
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    val nextSet = (1..wex.targetSets).firstOrNull { n ->
        wex.sets.none { it.setNumber == n && (it.actualReps != null || it.skipped) }
    }
    val done = nextSet == null
    val supersetColor = wex.supersetId?.let {
        // Stable hash → hue (HSL)
        val h = it.fold(0) { acc, c -> (acc * 31 + c.code) % 360 }
        Color(android.graphics.Color.HSVToColor(floatArrayOf(h.toFloat(), 0.55f, 0.85f)))
    }
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (done) MV.SurfaceContainerLow else MV.SurfaceContainer
        ),
        modifier = Modifier
            .fillMaxWidth()
            .then(if (supersetColor != null) Modifier.border(
                width = 2.dp, color = supersetColor.copy(alpha = 0.5f),
                shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp),
            ) else Modifier),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            if (wex.supersetId != null && partnerName != null) {
                Text(
                    "⇄ Superset ${wex.supersetId} — alternate with $partnerName",
                    color = supersetColor ?: MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(bottom = 4.dp),
                )
            }
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
                        "${wex.targetSets}×$rep$w  ·  ${wex.targetRestS}s rest",
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
            Row(verticalAlignment = Alignment.CenterVertically) {
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
                Spacer(Modifier.weight(1f))
                ExercisePrefMenu(onSetPref)
            }
            // Sets
            for (n in 1..wex.targetSets) {
                val key = "${wex.id}-$n"
                val logged = wex.sets.firstOrNull { it.setNumber == n && it.actualReps != null }
                if (logged != null) {
                    LoggedSetRow(n, logged.actualWeightLb, logged.actualReps ?: 0, logged.rating ?: 0)
                } else if (n == nextSet) {
                    // Inherit weight/reps from the most recently logged
                    // set of THIS exercise so an edit on set 1 carries
                    // forward to sets 2…N. Fall back to the planned
                    // target on the very first set.
                    val priorLogged = wex.sets
                        .filter { it.actualReps != null }
                        .maxByOrNull { it.setNumber }
                    val input = inputs.getOrPut(key) { SetInput(
                        weight = priorLogged?.actualWeightLb?.toString()
                            ?: wex.targetWeightLb?.toString().orEmpty(),
                        reps = (priorLogged?.actualReps
                            ?: wex.targetRepsLow).toString(),
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
                        onFailed = {
                            // Shortcut: rating=1, log with whatever's in the input
                            onLogSet(
                                n,
                                input.weight.toDoubleOrNull(),
                                input.reps.toIntOrNull(),
                                1,
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
    onRating: (Int) -> Unit, canLog: Boolean,
    onLog: () -> Unit, onFailed: () -> Unit,
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
                val color = ratingColor(r)
                Box(
                    Modifier
                        .weight(1f)
                        .height(48.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (on) color else MV.SurfaceContainerLow)
                        .border(1.dp,
                            if (on) color else color.copy(alpha = 0.45f),
                            RoundedCornerShape(8.dp))
                        .clickable { onRating(r) },
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("$r",
                            color = if (on) MV.OnSurface else color,
                            fontWeight = FontWeight.Bold, fontSize = 14.sp)
                        Text(
                            when (r) {
                                1 -> "fail"; 2 -> "0-1"; 3 -> "2-3"
                                4 -> "4-5"; 5 -> "6+"; else -> ""
                            },
                            color = if (on) MV.OnSurface.copy(alpha = 0.85f) else MV.OnSurfaceDim,
                            fontSize = 9.sp, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                        )
                    }
                }
            }
        }
        Text(
            "Reps in reserve — how many more you could've done. 1 = failed, 5 = easy",
            color = MV.OnSurfaceDim, fontSize = 10.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        )
        Row(
            Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                onClick = onLog, enabled = canLog,
                modifier = Modifier.weight(2f),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                ),
            ) { Text("Log set $n") }
            OutlinedButton(
                onClick = onFailed,
                modifier = Modifier.weight(1f),
            ) { Text("Failed") }
        }
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
    onDayClick: (dateIso: String) -> Unit = {},
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
                    .clickable(enabled = !isToday) { onDayClick(iso) }
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

@Composable
private fun ExercisePrefMenu(onSetPref: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) {
            Icon(
                Icons.Outlined.MoreVert,
                contentDescription = "Exercise preference",
                tint = MV.OnSurfaceVariant,
                modifier = Modifier.size(18.dp),
            )
        }
        androidx.compose.material3.DropdownMenu(
            expanded = open, onDismissRequest = { open = false },
        ) {
            androidx.compose.material3.DropdownMenuItem(
                leadingIcon = {
                    Icon(
                        Icons.Outlined.FavoriteBorder,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = MV.OnSurface,
                    )
                },
                text = { Text("Favorite — show more often") },
                onClick = { open = false; onSetPref("favorite") },
            )
            androidx.compose.material3.DropdownMenuItem(
                leadingIcon = {
                    Icon(
                        Icons.Outlined.ThumbDownOffAlt,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = MV.OnSurface,
                    )
                },
                text = { Text("Avoid — show less often") },
                onClick = { open = false; onSetPref("avoid") },
            )
            androidx.compose.material3.DropdownMenuItem(
                leadingIcon = {
                    Icon(
                        Icons.Outlined.Block,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = MV.OnSurface,
                    )
                },
                text = { Text("Disable — never include") },
                onClick = { open = false; onSetPref("disabled") },
            )
            androidx.compose.material3.DropdownMenuItem(
                leadingIcon = {
                    Icon(
                        Icons.Outlined.Restore,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = MV.OnSurface,
                    )
                },
                text = { Text("Reset to neutral") },
                onClick = { open = false; onSetPref("neutral") },
            )
        }
    }
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
