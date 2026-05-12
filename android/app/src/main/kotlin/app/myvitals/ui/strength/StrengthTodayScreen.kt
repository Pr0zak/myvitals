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
import androidx.compose.material.icons.filled.AddCircle
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import androidx.compose.material.icons.outlined.Block
import androidx.compose.material.icons.outlined.Close
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
import androidx.compose.ui.graphics.ColorFilter
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
    // Incremented after each regenerate. DeloadBannerCard keys its
    // LaunchedEffect on this, so the banner re-fetches /latest after
    // a regen and we POST a fresh /deload-check in parallel (cached
    // by signals hash — free when nothing actually moved).
    var deloadRefreshKey by remember { mutableStateOf(0) }
    // Coach card state — keyed by workout id at the screen level so the
    // state outlives any CoachCard re-creation. Earlier the state lived
    // inside CoachCard via `remember(workoutId)`, but apparently the
    // composable was getting disposed and re-created on some recomposition
    // path (LazyColumn slot churn), which dropped openVariety + dismissed
    // + swaps and made the AI look like it kept changing its mind.
    val coachState = remember(workout?.id) { CoachCardState() }

    fun bumpDeload() {
        deloadRefreshKey++
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                withContext(Dispatchers.IO) { api.strengthDeloadCheck() }
            } catch (e: Exception) {
                Timber.d(e, "deload re-check after regen failed")
            }
        }
    }
    var history by remember { mutableStateOf<List<app.myvitals.sync.StrengthWorkoutSummary>>(emptyList()) }
    var daysPerWeek by remember { mutableStateOf(3) }
    var loading by remember { mutableStateOf(true) }
    var generating by remember { mutableStateOf(false) }
    var deferring by remember { mutableStateOf(false) }
    var swapWexId by remember { mutableStateOf<Long?>(null) }
    var swapping by remember { mutableStateOf(false) }
    var customSheetOpen by remember { mutableStateOf(false) }
    var customGenerating by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    // Offline plumbing — banner above the workout shows "offline" when
    // network is down or "N pending sync" when set logs are buffered.
    val online by app.myvitals.ui.common.rememberOnlineState()
    var bufferedSets by remember { mutableIntStateOf(0) }
    var flushing by remember { mutableStateOf(false) }
    suspend fun refreshBuffered() {
        bufferedSets = runCatching { repo.bufferedCount() }.getOrDefault(0)
    }
    // After every onLogSet result, refresh the buffered-count so the
    // banner updates if the call hit the network buffer fallback.
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(5_000)
            refreshBuffered()
        }
    }

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

    LaunchedEffect(Unit) { reload(); refreshBuffered() }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { reload() } }

    // Workout-complete dialog. Pops the moment the last prescribed set
    // is logged. Declared AFTER reload() and `error` because the
    // confirmButton lambda refers to them; Kotlin local functions /
    // vars must be in scope at use site.
    var showCompleteDialog by remember(workout?.id) { mutableStateOf(false) }
    var completeDialogDismissed by remember(workout?.id) { mutableStateOf(false) }
    val totalSets = workout?.exercises?.sumOf { it.targetSets } ?: 0
    val completedSets = workout?.exercises?.flatMap { it.sets }
        ?.count { it.actualReps != null && !it.skipped } ?: 0
    val allSetsDone = totalSets > 0 && completedSets >= totalSets
    LaunchedEffect(allSetsDone, workout?.status) {
        if (allSetsDone
            && !completeDialogDismissed
            && workout?.status != "completed"
        ) showCompleteDialog = true
    }
    if (showCompleteDialog && workout != null) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = {
                showCompleteDialog = false
                completeDialogDismissed = true
            },
            title = { Text("Workout complete?") },
            text = {
                Text(
                    "All $totalSets prescribed sets logged. Finish and stamp " +
                    "the session, or keep going if you want to add bonus work.",
                )
            },
            confirmButton = {
                androidx.compose.material3.TextButton(
                    onClick = {
                        showCompleteDialog = false
                        scope.launch {
                            try { workout = repo.completeWorkout(workout!!.id); reload() }
                            catch (e: Exception) { error = e.message?.take(160) }
                        }
                    },
                ) { Text("Finish workout", color = MV.Green) }
            },
            dismissButton = {
                androidx.compose.material3.TextButton(
                    onClick = {
                        showCompleteDialog = false
                        completeDialogDismissed = true
                    },
                ) { Text("Keep going") }
            },
        )
    }

    // Auto-flush both buffers (set logs + workout-status patches) when
    // network returns. Sets first so the workout's logged-set list is
    // current before the patch applies; then status patches.
    LaunchedEffect(online) {
        if (online && bufferedSets > 0) {
            flushing = true
            try {
                repo.flushBufferedSets()
                repo.flushBufferedWorkoutWrites()
                refreshBuffered()
                if (bufferedSets == 0) reload()
            } finally { flushing = false }
        }
    }
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
            if (workout?.status == "planned") {
                // Visible regenerate button — mirrors the web header's
                // "Regenerate ↻". Re-pulls fresh recovery / HRV / sleep
                // signals and rebuilds the plan; dropdown copy below
                // stays as a fallback.
                IconButton(
                    onClick = {
                        scope.launch {
                            generating = true
                            try {
                                workout = repo.regenerate(true); reload()
                                bumpDeload()
                            }
                            catch (e: Exception) { error = e.message?.take(160) }
                            finally { generating = false }
                        }
                    },
                    enabled = !generating,
                ) {
                    Icon(
                        Icons.Filled.Refresh,
                        contentDescription = "Regenerate with latest signals",
                        tint = MV.OnSurfaceVariant,
                    )
                }
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
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("Custom workout") },
                        leadingIcon = { Icon(Icons.Filled.AddCircle, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = {
                            headerMenuOpen = false
                            customSheetOpen = true
                        },
                    )
                    if (workout?.status == "planned") {
                        // Dropdown copy of Regenerate — same action as the
                        // header IconButton, kept for users who reach for
                        // the menu first. Mirrors web's "Regenerate plan"
                        // entry inside the Swap day ▾ dropdown.
                        androidx.compose.material3.DropdownMenuItem(
                            text = { Text("Regenerate plan") },
                            leadingIcon = { Icon(Icons.Filled.Refresh, null,
                                modifier = Modifier.size(16.dp)) },
                            onClick = {
                                headerMenuOpen = false
                                scope.launch {
                                    generating = true
                                    try {
                                        workout = repo.regenerate(true); reload()
                                        bumpDeload()
                                    }
                                    catch (e: Exception) { error = e.message?.take(160) }
                                    finally { generating = false }
                                }
                            },
                        )
                    }
                    if (workout?.status == "planned" || workout?.status == "in_progress") {
                        // Discard — only meaningful when the workout has
                        // no logged sets yet. After a "Custom workout"
                        // generation this falls through to whatever was
                        // previously today's plan (e.g. the completed
                        // morning session) instead of leaving an empty
                        // skipped row.
                        val anyLogged = workout?.exercises?.any { ex ->
                            ex.sets.any { it.actualReps != null }
                        } == true
                        if (!anyLogged) {
                            androidx.compose.material3.DropdownMenuItem(
                                text = { Text("Discard workout",
                                    color = MV.OnSurface) },
                                leadingIcon = { Icon(Icons.Outlined.Close, null,
                                    modifier = Modifier.size(16.dp), tint = MV.OnSurface) },
                                onClick = {
                                    headerMenuOpen = false
                                    scope.launch {
                                        deferring = true
                                        try { repo.discardWorkout(workout!!.id); reload() }
                                        catch (e: Exception) { error = e.message?.take(160) }
                                        finally { deferring = false }
                                    }
                                },
                            )
                        }
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

        // Offline + buffered-sync banner. Visible when:
        //   - network is down (cached plan still loads from local prefs)
        //   - or buffered set logs are pending the next flush
        if (!online || bufferedSets > 0) {
            OfflineBanner(
                online = online,
                pending = bufferedSets,
                flushing = flushing,
                onSyncNow = {
                    scope.launch {
                        flushing = true
                        try {
                            repo.flushBufferedSets()
                            repo.flushBufferedWorkoutWrites()
                            refreshBuffered()
                            if (bufferedSets == 0) reload()
                        } finally { flushing = false }
                    }
                },
            )
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
                            try {
                                workout = repo.regenerate(true); reload()
                                bumpDeload()
                            }
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
                            try {
                                workout = repo.regenerate(false); reload()
                                bumpDeload()
                            }
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
        // is always visible without scrolling. Within a superset PAIR,
        // alternate by completed-set count (log set 1 of A, then 1 of B,
        // then 2 of A — that's the point of a superset). Non-superset
        // exercises stay in their natural order so the user finishes all
        // sets of A before moving to B — bouncing breaks focus on
        // compound lifts. Done exercises drop to the bottom for reference.
        val orderedExercises = remember(plan.exercises) {
            fun completedCount(w: app.myvitals.sync.StrengthWorkoutExerciseRow): Int =
                w.sets.count { it.actualReps != null || it.skipped }
            fun isDone(w: app.myvitals.sync.StrengthWorkoutExerciseRow): Boolean =
                completedCount(w) >= w.targetSets

            val incomplete = plan.exercises.filter { !isDone(it) }
            val complete = plan.exercises.filter { isDone(it) }
                .sortedBy { it.orderIndex }

            val groupedIncomplete = incomplete
                .groupBy { it.supersetId }
                .map { (ssId, exs) ->
                    if (ssId == null) {
                        // Non-supersetted exercises: keep orderIndex
                        // order. Each exercise stays at the top of its
                        // slice until all its sets are done.
                        exs.sortedBy { it.orderIndex }
                    } else {
                        // Superset partners: alternate by completed-count
                        // so the next set is always on the partner who's
                        // behind.
                        exs.sortedWith(
                            compareBy({ completedCount(it) }, { it.orderIndex }),
                        )
                    }
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
            if (plan.status == "planned" || plan.status == "in_progress") {
                item {
                    CoachCard(
                        settings = settings,
                        workoutId = plan.id,
                        state = coachState,
                        refreshKey = deloadRefreshKey,
                        onAcceptSwap = { targetExId, replacementExId ->
                            val wex2 = plan.exercises.firstOrNull {
                                it.exerciseId == targetExId
                            }
                            if (wex2 != null) {
                                // Show "Swap applied" feedback right away so
                                // the section stays open visually even while
                                // the network swap + reload run in the
                                // background.
                                Toast.makeText(
                                    context,
                                    "Swap applied: " +
                                        replacementExId.replace('_', ' '),
                                    Toast.LENGTH_SHORT,
                                ).show()
                                scope.launch {
                                    try {
                                        val api = BackendClient.create(
                                            settings.backendUrl, settings.bearerToken,
                                        )
                                        withContext(Dispatchers.IO) {
                                            api.swapStrengthExercise(
                                                wex2.id,
                                                app.myvitals.sync.SwapBody(replacementExId),
                                            )
                                        }
                                        reload()
                                    } catch (e: Exception) {
                                        Timber.w(e, "coach swap failed")
                                        error = "Swap failed: ${e.message?.take(80)}"
                                    }
                                }
                            }
                        },
                    )
                }
            }
            // Cardio / notes-only plans (split_focus == "cardio") come back
            // with exercises=[] and the prescription text in `notes`. Without
            // this card the screen looks blank between the Coach card and
            // the Complete button. Web has the equivalent card since v0.7.144.
            if (plan.exercises.isEmpty() && !plan.notes.isNullOrBlank()) {
                item {
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MV.SurfaceContainer,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(Modifier.padding(14.dp)) {
                            Text(
                                when (plan.splitFocus) {
                                    "cardio" -> "Cardio prescription"
                                    "yoga" -> "Mobility flow"
                                    "rest" -> "Rest day"
                                    else -> plan.splitFocus
                                        .replaceFirstChar(Char::titlecase)
                                },
                                color = MV.OnSurface, fontSize = 14.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(bottom = 6.dp),
                            )
                            Text(
                                plan.notes!!,
                                color = MV.OnSurfaceVariant, fontSize = 13.sp,
                            )
                        }
                    }
                }
            }
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
                    backendBaseUrl = settings.backendUrl.trimEnd('/'),
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
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    "✓ Workout complete — see you tomorrow",
                                    color = MV.Green, fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    modifier = Modifier.weight(1f),
                                )
                                // Replay: regenerate with force=true. Wipes
                                // logged sets from today's row so the user
                                // can run the same plan a second time.
                                TextButton(
                                    onClick = {
                                        scope.launch {
                                            try {
                                                workout = repo.regenerate(true); reload()
                                                bumpDeload()
                                            }
                                            catch (e: Exception) {
                                                Timber.w(e, "redo workout failed")
                                            }
                                        }
                                    },
                                ) {
                                    Icon(
                                        Icons.Filled.Refresh, contentDescription = null,
                                        tint = MV.OnSurfaceVariant,
                                        modifier = Modifier.size(14.dp),
                                    )
                                    Spacer(Modifier.width(4.dp))
                                    Text("Redo", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                                }
                            }
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
            // Why + Variety + Deload + Focus are consolidated into CoachCard
            // mounted at the top of the LazyColumn — no separate bottom block.
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

    // ── Custom workout sheet ────────────────────────────────────
    if (customSheetOpen) {
        CustomWorkoutSheet(
            generating = customGenerating,
            onDismiss = { customSheetOpen = false },
            onGenerate = { type, durationMin, difficulty ->
                scope.launch {
                    customGenerating = true
                    try {
                        val api = BackendClient.create(
                            settings.backendUrl, settings.bearerToken,
                        )
                        api.swapStrengthTodayType(
                            app.myvitals.sync.SwapTodayTypeRequest(
                                type = type,
                                durationMinutes = durationMin,
                                difficulty = difficulty,
                                // Custom workout always opts in — user
                                // explicitly chose to stack a second
                                // session on top of whatever's there.
                                replaceCompleted = true,
                            ),
                        )
                        customSheetOpen = false
                        reload()
                    } catch (e: Exception) {
                        Timber.w(e, "custom workout generate failed")
                        error = e.message?.take(160)
                    } finally {
                        customGenerating = false
                    }
                }
            },
        )
    }
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun CustomWorkoutSheet(
    generating: Boolean,
    onDismiss: () -> Unit,
    onGenerate: (type: String, durationMin: Int, difficulty: String) -> Unit,
) {
    var type by remember { mutableStateOf("strength") }
    var difficulty by remember { mutableStateOf("normal") }
    var durationMin by remember { mutableIntStateOf(45) }
    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = MV.SurfaceContainer,
    ) {
        Column(modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp)) {
            Text(
                "Custom workout",
                color = MV.OnSurface, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
            )
            Text(
                "Generate a one-off session — the planner picks exercises sized to "
                + "your duration + difficulty.",
                color = MV.OnSurfaceVariant, fontSize = 12.sp,
                modifier = Modifier.padding(top = 4.dp, bottom = 14.dp),
            )

            // Type picker — three pills
            SectionLabel("Type")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("strength", "yoga", "cardio").forEach { t ->
                    PillChip(
                        label = t.replaceFirstChar { it.uppercase() },
                        selected = type == t,
                        onClick = { type = t },
                    )
                }
            }
            Spacer(Modifier.height(14.dp))

            // Duration picker — preset buttons
            SectionLabel("Duration")
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(15, 30, 45, 60, 90).forEach { mins ->
                    PillChip(
                        label = "${mins}m",
                        selected = durationMin == mins,
                        onClick = { durationMin = mins },
                    )
                }
            }
            Spacer(Modifier.height(14.dp))

            // Difficulty picker
            SectionLabel("Difficulty")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(
                    "easy" to "Easy",
                    "normal" to "Normal",
                    "hard" to "Hard",
                ).forEach { (key, label) ->
                    PillChip(
                        label = label,
                        selected = difficulty == key,
                        onClick = { difficulty = key },
                    )
                }
            }
            Spacer(Modifier.height(20.dp))

            androidx.compose.material3.Button(
                onClick = { onGenerate(type, durationMin, difficulty) },
                enabled = !generating,
                colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                    containerColor = Color(0xFFA78BFA),
                    contentColor = Color.White,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (generating) "Generating…" else "Generate workout")
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun OfflineBanner(
    online: Boolean, pending: Int, flushing: Boolean, onSyncNow: () -> Unit,
) {
    val bg = if (!online) Color(0x33EAB308) else Color(0x33A78BFA)
    val fg = if (!online) Color(0xFFEAB308) else Color(0xFFA78BFA)
    val msg = when {
        !online && pending > 0 -> "Offline · $pending set${if (pending == 1) "" else "s"} buffered"
        !online -> "Offline · using cached workout"
        pending > 0 -> "$pending set${if (pending == 1) "" else "s"} pending sync"
        else -> ""
    }
    if (msg.isEmpty()) return
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp)
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
            .background(bg)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            msg,
            color = fg, fontSize = 12.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(1f),
        )
        if (online && pending > 0) {
            TextButton(
                onClick = onSyncNow,
                enabled = !flushing,
            ) {
                Text(
                    if (flushing) "Syncing…" else "Sync now",
                    color = fg, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        color = MV.OnSurfaceVariant, fontSize = 11.sp,
        fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
        modifier = Modifier.padding(bottom = 6.dp),
    )
}

@Composable
private fun PillChip(label: String, selected: Boolean, onClick: () -> Unit) {
    androidx.compose.foundation.layout.Box(
        modifier = Modifier
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(999.dp))
            .background(
                if (selected) Color(0x33A78BFA) else Color(0x141A2332),
            )
            .border(
                width = 1.dp,
                color = if (selected) Color(0xFFA78BFA) else Color(0x40A78BFA),
                shape = androidx.compose.foundation.shape.RoundedCornerShape(999.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(
            label,
            color = if (selected) Color(0xFFA78BFA) else MV.OnSurfaceVariant,
            fontSize = 13.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
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
internal fun FocusCueCard(
    settings: SettingsRepository, workoutId: Long, refreshKey: Int = 0,
) {
    var cue by remember(workoutId) {
        mutableStateOf<app.myvitals.sync.FocusCueBody?>(null)
    }
    var loading by remember(workoutId) { mutableStateOf(false) }
    var failed by remember(workoutId) { mutableStateOf(false) }
    var expanded by remember(workoutId) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    fun load() {
        if (loading || !settings.isConfigured()) return
        loading = true
        failed = false
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val resp = withContext(Dispatchers.IO) { api.strengthFocusCue(workoutId) }
                cue = resp.cue
                expanded = true
            } catch (e: Exception) {
                Timber.w(e, "focus cue failed")
                failed = true
            } finally { loading = false }
        }
    }

    // refreshKey changes (e.g. after a regenerate) → drop cached cue
    // so the next tap re-fetches against the new plan.
    LaunchedEffect(refreshKey) {
        if (refreshKey != 0) { cue = null; failed = false; expanded = false }
    }

    Card(
        colors = CardDefaults.cardColors(
            containerColor = Color(0xFFA78BFA).copy(alpha = 0.10f)
        ),
        modifier = Modifier.fillMaxWidth().clickable {
            if (cue == null) load() else expanded = !expanded
        },
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("◇", color = Color(0xFFA78BFA), fontSize = 14.sp,
                    modifier = Modifier.padding(end = 6.dp))
                Text(
                    cue?.headline?.takeIf { it.isNotEmpty() } ?: "Focus cue",
                    color = MV.OnSurface, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    when {
                        loading -> "Thinking…"
                        failed -> "Unavailable"
                        cue == null -> "Ask AI"
                        else -> if (expanded) "−" else "+"
                    },
                    color = MV.OnSurfaceVariant, fontSize = 12.sp,
                )
            }
            if (expanded && cue != null && cue!!.cue.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text(cue!!.cue, color = MV.OnSurface, fontSize = 12.sp)
            }
        }
    }
}

@Composable
internal fun DeloadBannerCard(settings: SettingsRepository, refreshKey: Int = 0) {
    var judgment by remember { mutableStateOf<app.myvitals.sync.DeloadJudgment?>(null) }
    var expanded by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    // Load latest cached judgment on first composition AND whenever
    // refreshKey changes — the workout screen bumps it after every
    // regenerate so the banner stays in sync with the active plan.
    LaunchedEffect(refreshKey) {
        if (!settings.isConfigured()) return@LaunchedEffect
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.strengthDeloadLatest() }
            if (resp.isSuccessful) judgment = resp.body()?.judgment
        } catch (e: Exception) {
            Timber.d(e, "deload latest fetch failed")
        }
    }

    fun refresh() {
        if (loading || !settings.isConfigured()) return
        loading = true
        failed = false
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val resp = withContext(Dispatchers.IO) { api.strengthDeloadCheck() }
                judgment = resp.judgment
            } catch (e: Exception) {
                Timber.w(e, "deload check failed")
                failed = true
            } finally { loading = false }
        }
    }

    val j = judgment
    if (j == null) {
        // Compact "ask AI" pill when nothing cached yet
        Card(
            colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainerLow),
            modifier = Modifier.fillMaxWidth().clickable { refresh() },
        ) {
            Row(
                Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("▲ Deload check",
                    color = MV.OnSurface, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text(
                    when {
                        loading -> "Reading…"
                        failed -> "Unavailable"
                        else -> "Ask AI"
                    },
                    color = MV.OnSurfaceVariant, fontSize = 12.sp,
                )
            }
        }
        return
    }

    if (j.severity == "none") return  // no banner when AI says all clear

    val accent = when (j.severity) {
        "light" -> Color(0xFFFACC15)
        "moderate" -> Color(0xFFF97316)
        "rest" -> Color(0xFFEF4444)
        else -> MV.OnSurfaceVariant
    }
    Card(
        colors = CardDefaults.cardColors(
            containerColor = accent.copy(alpha = 0.10f),
        ),
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = 0.dp,
                color = androidx.compose.ui.graphics.Color.Transparent,
                shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp),
            )
            .clickable { expanded = !expanded },
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("▲", color = accent, fontSize = 14.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(end = 6.dp))
                Text(
                    "Deload ${j.severity}",
                    color = MV.OnSurface, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    j.headline,
                    color = MV.OnSurface, fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                Text(if (expanded) "▾" else "▸",
                    color = MV.OnSurfaceVariant, fontSize = 14.sp)
            }
            if (expanded) {
                Spacer(Modifier.height(6.dp))
                for (e in j.evidence) {
                    Text("• $e", color = MV.OnSurfaceVariant, fontSize = 12.sp,
                        modifier = Modifier.padding(vertical = 1.dp))
                }
                if (j.recommendation.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "What to do: ${j.recommendation}",
                        color = MV.OnSurface, fontSize = 12.sp,
                    )
                }
                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = { refresh() },
                    enabled = !loading,
                ) { Text(if (loading) "Thinking…" else "Re-check", fontSize = 11.sp) }
            }
        }
    }
}

/** All mutable state used by CoachCard, hoisted into a holder so the
 *  parent screen owns the lifetime. Earlier the state was internal to
 *  CoachCard, which meant any path that disposed and re-created the
 *  composable (LazyColumn item churn, conditional re-evaluation, etc.)
 *  dropped openVariety + dismissed + swaps, making it look like the
 *  AI was re-querying on every Accept. */
@androidx.compose.runtime.Stable
internal class CoachCardState {
    var deload by mutableStateOf<app.myvitals.sync.DeloadJudgment?>(null)
    var deloadLoading by mutableStateOf(false)
    var focus by mutableStateOf<app.myvitals.sync.FocusCueBody?>(null)
    var focusLoading by mutableStateOf(false)
    var swaps by mutableStateOf<List<app.myvitals.sync.StrengthSwapSuggestion>?>(null)
    var swapsLoading by mutableStateOf(false)
    val dismissed = mutableStateMapOf<String, Boolean>()
    var explain by mutableStateOf<app.myvitals.sync.StrengthExplain?>(null)
    var explainLoading by mutableStateOf(false)
    var openDeload by mutableStateOf(false)
    var openFocus by mutableStateOf(false)
    var openVariety by mutableStateOf(false)
    var openWhy by mutableStateOf(false)
    // Master collapse — Coach body hidden by default. Tap header to expand.
    var cardOpen by mutableStateOf(false)
}

/** Consolidated Coach card — replaces 4 separate cards (Why, Deload,
 *  Variety, Focus) with one collapsible card that has four expandable
 *  sections. Each section lazy-loads its body on first expand; deload
 *  pre-fetches /latest so its severity pill is accurate without a tap.
 *  refreshKey invalidates cached state after a regenerate. State is
 *  hoisted via the `state` param so the parent's lifetime owns it. */
@Composable
internal fun CoachCard(
    settings: SettingsRepository,
    workoutId: Long,
    state: CoachCardState,
    refreshKey: Int = 0,
    onAcceptSwap: (targetExerciseId: String, replacementExerciseId: String) -> Unit,
) {
    val scope = rememberCoroutineScope()

    // Pre-fetch the cached deload judgment so its pill is right without a tap.
    LaunchedEffect(refreshKey, workoutId) {
        if (refreshKey != 0) {
            state.deload = null; state.focus = null; state.swaps = null; state.explain = null
            state.dismissed.clear()
        }
        if (settings.isConfigured()) {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val resp = withContext(Dispatchers.IO) { api.strengthDeloadLatest() }
                if (resp.isSuccessful) state.deload = resp.body()?.judgment
            } catch (e: Exception) { Timber.d(e, "coach deload prefetch") }
        }
    }

    fun reCheckDeload() {
        if (state.deloadLoading) return
        state.deloadLoading = true
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val r = withContext(Dispatchers.IO) { api.strengthDeloadCheck() }
                state.deload = r.judgment
            } catch (e: Exception) { Timber.w(e, "coach deload check") }
            finally { state.deloadLoading = false }
        }
    }
    fun loadFocus() {
        if (state.focus != null || state.focusLoading) return
        state.focusLoading = true
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val r = withContext(Dispatchers.IO) { api.strengthFocusCue(workoutId) }
                state.focus = r.cue
            } catch (e: Exception) { Timber.w(e, "coach focus cue") }
            finally { state.focusLoading = false }
        }
    }
    fun loadSwaps(force: Boolean = false) {
        if (state.swapsLoading) return
        if (state.swaps != null && !force) return
        state.swapsLoading = true
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val r = withContext(Dispatchers.IO) { api.strengthNudge(workoutId) }
                state.swaps = r.nudge.swaps
                if (force) state.dismissed.clear()
            } catch (e: Exception) {
                Timber.w(e, "coach variety nudge"); state.swaps = emptyList()
            } finally { state.swapsLoading = false }
        }
    }
    fun loadExplain() {
        if (state.explain != null || state.explainLoading) return
        state.explainLoading = true
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val r = withContext(Dispatchers.IO) { api.strengthExplain(workoutId) }
                state.explain = r
            } catch (e: Exception) { Timber.w(e, "coach explain") }
            finally { state.explainLoading = false }
        }
    }

    val visibleSwaps = (state.swaps ?: emptyList())
        .filter { state.dismissed[it.targetExerciseId] != true }
    val sevColor = when (state.deload?.severity) {
        "rest" -> Color(0xFFEF4444)
        "moderate" -> Color(0xFFF97316)
        "light" -> Color(0xFFFACC15)
        else -> null
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(10.dp)) {
            // Clickable header. Surfaces the most-actionable signal
            // (deload severity) inline when collapsed so the user sees
            // state without expanding.
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { state.cardOpen = !state.cardOpen }
                    .padding(start = 4.dp, end = 4.dp,
                        top = 2.dp, bottom = if (state.cardOpen) 4.dp else 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "Coach", color = MV.OnSurface, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                val sevPill = state.deload?.severity?.takeIf { it != "none" }
                if (!state.cardOpen && sevPill != null) {
                    val sevColor = when (sevPill) {
                        "rest" -> Color(0xFFEF4444)
                        "moderate" -> Color(0xFFF97316)
                        "light" -> Color(0xFFFACC15)
                        else -> MV.OnSurfaceVariant
                    }
                    Text(
                        "Deload $sevPill",
                        color = sevColor, fontSize = 11.sp,
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(sevColor.copy(alpha = 0.15f))
                            .padding(horizontal = 8.dp, vertical = 2.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                }
                Text(
                    if (state.cardOpen) "−" else "+",
                    color = MV.OnSurfaceVariant, fontSize = 16.sp,
                )
            }
            if (!state.cardOpen) return@Column
            // Deload
            CoachRow(
                icon = "▲",
                title = "Deload",
                pill = state.deload?.severity?.takeIf { it != "none" }
                    ?: if (state.deload != null) "clear" else "tap to check",
                pillColor = sevColor
                    ?: if (state.deload != null) Color(0xFF22C55E) else MV.OnSurfaceVariant,
                expanded = state.openDeload,
                accent = sevColor,
                onToggle = { state.openDeload = !state.openDeload },
            ) {
                val d = state.deload
                if (d != null && d.severity != "none") {
                    Text(d.headline, color = MV.OnSurface, fontSize = 12.sp,
                        fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(4.dp))
                    for (e in d.evidence) {
                        Text("• $e", color = MV.OnSurfaceVariant, fontSize = 11.sp,
                            modifier = Modifier.padding(vertical = 1.dp))
                    }
                    if (d.recommendation.isNotEmpty()) {
                        Spacer(Modifier.height(4.dp))
                        Text("What to do: ${d.recommendation}",
                            color = MV.OnSurface, fontSize = 11.sp)
                    }
                } else if (d != null) {
                    Text("No deload needed.", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else if (state.deloadLoading) {
                    Text("Thinking…", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                }
                Spacer(Modifier.height(6.dp))
                OutlinedButton(onClick = { reCheckDeload() }, enabled = !state.deloadLoading) {
                    Text(if (state.deloadLoading) "Thinking…" else "Re-check", fontSize = 10.sp)
                }
            }

            // Focus
            CoachRow(
                icon = "◇",
                title = "Focus cue",
                pill = if (state.focus != null) "ready" else "tap to load",
                pillColor = if (state.focus != null) Color(0xFF38BDF8) else MV.OnSurfaceVariant,
                expanded = state.openFocus,
                accent = null,
                onToggle = {
                    state.openFocus = !state.openFocus
                    if (state.openFocus) loadFocus()
                },
            ) {
                val f = state.focus
                if (f != null) {
                    Text(f.headline, color = MV.OnSurface, fontSize = 12.sp,
                        fontWeight = FontWeight.Medium)
                    if (f.cue.isNotEmpty()) {
                        Spacer(Modifier.height(3.dp))
                        Text(f.cue, color = MV.OnSurface, fontSize = 11.sp)
                    }
                } else if (state.focusLoading) {
                    Text("Thinking…", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else {
                    Text("Tap to load.", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                }
            }

            // Variety
            CoachRow(
                icon = "✦",
                title = "Variety",
                pill = when {
                    state.swaps == null -> "tap to check"
                    visibleSwaps.isEmpty() && (state.swaps?.isEmpty() == true) -> "balanced"
                    visibleSwaps.isEmpty() -> "all handled"
                    else -> "${visibleSwaps.size} swap${if (visibleSwaps.size == 1) "" else "s"}"
                },
                pillColor = if (state.swaps != null && visibleSwaps.isNotEmpty())
                    Color(0xFFA78BFA)
                else if (state.swaps != null) Color(0xFF22C55E)
                else MV.OnSurfaceVariant,
                expanded = state.openVariety,
                accent = null,
                onToggle = {
                    state.openVariety = !state.openVariety
                    if (state.openVariety) loadSwaps()
                },
            ) {
                if (state.swapsLoading) {
                    Text("Thinking…", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else if (state.swaps == null) {
                    Text("Tap to load.", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else if (visibleSwaps.isEmpty()) {
                    Text("Plan looks balanced — no swaps suggested.",
                        color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else {
                    for (s in visibleSwaps) {
                        Column(
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 4.dp)
                                .clip(RoundedCornerShape(6.dp))
                                .background(MV.SurfaceContainerLow)
                                .padding(8.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(s.targetExerciseId.replace('_', ' ')
                                        .replaceFirstChar(Char::titlecase),
                                    color = MV.OnSurface, fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(" → ", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                                Text(s.replacementExerciseId.replace('_', ' ')
                                        .replaceFirstChar(Char::titlecase),
                                    color = MV.Green, fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold)
                            }
                            Spacer(Modifier.height(2.dp))
                            Text(s.reason, color = MV.OnSurfaceVariant, fontSize = 10.sp)
                            Spacer(Modifier.height(4.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                Button(
                                    onClick = {
                                        onAcceptSwap(s.targetExerciseId, s.replacementExerciseId)
                                        // Implicit dismiss — swap is applied; no point showing it.
                                        state.dismissed[s.targetExerciseId] = true
                                    },
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = MV.BrandRed,
                                        contentColor = MV.OnSurface,
                                    ),
                                ) { Text("Accept", fontSize = 10.sp) }
                                OutlinedButton(
                                    onClick = { state.dismissed[s.targetExerciseId] = true },
                                ) { Text("Dismiss", fontSize = 10.sp) }
                            }
                        }
                    }
                    if (visibleSwaps.isEmpty() && (state.swaps?.isNotEmpty() == true)) {
                        Spacer(Modifier.height(6.dp))
                        OutlinedButton(
                            onClick = { loadSwaps(force = true) },
                            enabled = !state.swapsLoading,
                        ) {
                            Text(
                                if (state.swapsLoading) "Thinking…" else "Get fresh suggestions",
                                fontSize = 10.sp,
                            )
                        }
                    }
                }
            }

            // Why
            CoachRow(
                icon = "?",
                title = "Why this workout",
                pill = if (state.explain != null) "loaded" else "tap to view",
                pillColor = MV.OnSurfaceVariant,
                expanded = state.openWhy,
                accent = null,
                onToggle = {
                    state.openWhy = !state.openWhy
                    if (state.openWhy) loadExplain()
                },
            ) {
                val ex = state.explain
                if (state.explainLoading) {
                    Text("…", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else if (ex == null) {
                    Text("Tap to load.", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                } else {
                    Text("WHY THIS SPLIT", color = MV.OnSurfaceVariant, fontSize = 9.sp)
                    Text(ex.whySplit, color = MV.OnSurface, fontSize = 11.sp)
                    Spacer(Modifier.height(4.dp))
                    Text("WHY THESE EXERCISES", color = MV.OnSurfaceVariant, fontSize = 9.sp)
                    Text(ex.whyExercises, color = MV.OnSurface, fontSize = 11.sp)
                    Spacer(Modifier.height(4.dp))
                    Text("WHY THESE TARGETS", color = MV.OnSurfaceVariant, fontSize = 9.sp)
                    Text(ex.whyTargets, color = MV.OnSurface, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
private fun CoachRow(
    icon: String,
    title: String,
    pill: String,
    pillColor: Color,
    expanded: Boolean,
    accent: Color?,
    onToggle: () -> Unit,
    body: @Composable () -> Unit,
) {
    val borderMod = if (accent != null) {
        Modifier
            .background(accent.copy(alpha = 0.07f))
            .padding(start = 3.dp)
    } else Modifier
    Column(
        Modifier
            .fillMaxWidth()
            .then(borderMod)
            .padding(vertical = 4.dp, horizontal = 4.dp),
    ) {
        // Only the header row is clickable. The body must NOT be clickable
        // because Compose's `clickable` modifier intercepts touches for
        // the whole element; buttons inside the body fire their handlers
        // BUT their click also propagates to the parent. That was making
        // tapping Accept inside Variety close the section.
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth().clickable { onToggle() },
        ) {
            Text(icon, color = accent ?: MV.OnSurfaceVariant, fontSize = 12.sp,
                modifier = Modifier.padding(end = 6.dp).width(14.dp))
            Text(title, color = MV.OnSurface, fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Text(
                pill,
                color = pillColor,
                fontSize = 10.sp,
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(pillColor.copy(alpha = 0.15f))
                    .padding(horizontal = 7.dp, vertical = 2.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(if (expanded) "−" else "+", color = MV.OnSurfaceVariant, fontSize = 13.sp)
        }
        if (expanded) {
            Spacer(Modifier.height(4.dp))
            Column(Modifier.padding(start = 18.dp)) { body() }
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
    backendBaseUrl: String = "",
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
                    val baseUrl = backendBaseUrl
                    if (baseUrl.isNotEmpty()) {
                        // Photo (.jpg from base catalog) → render as-is.
                        // Icon (.png from Noun Project) → tint violet so the
                        // black-on-transparent silhouette becomes legible.
                        // Mirrors web's image() vs thumb-mask split.
                        val isPhoto = info.imageFront!!
                            .lowercase().let { it.endsWith(".jpg") || it.endsWith(".jpeg") }
                        Box(
                            Modifier
                                .size(40.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .background(Color(0x14A78BFA)),
                            contentAlignment = Alignment.Center,
                        ) {
                            AsyncImage(
                                model = baseUrl + info.imageFront,
                                contentDescription = name,
                                modifier = if (isPhoto) Modifier.size(40.dp)
                                           else Modifier.size(32.dp),
                                colorFilter = if (isPhoto) null
                                              else ColorFilter.tint(Color(0xFFA78BFA)),
                            )
                        }
                    }
                } else if (info?.movementPattern == "mobility"
                    && app.myvitals.ui.hasYogaPoseIcon(wex.exerciseId)) {
                    // Yoga poses ship without bundled images — render the
                    // hand-drawn pose silhouette so each row is visually
                    // identifiable rather than a name-only block.
                    Box(
                        Modifier
                            .size(40.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(Color(0x14A78BFA)),
                        contentAlignment = Alignment.Center,
                    ) {
                        app.myvitals.ui.YogaPoseIcon(
                            id = wex.exerciseId, size = 28.dp,
                            tint = Color(0xFFA78BFA),
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
            val timed = isTimedExercise(wex, info)
            for (n in 1..wex.targetSets) {
                val key = "${wex.id}-$n"
                val logged = wex.sets.firstOrNull { it.setNumber == n && it.actualReps != null }
                if (logged != null) {
                    if (timed) {
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("$n", color = MV.OnSurfaceVariant,
                                modifier = Modifier.width(20.dp))
                            Text("Held ${logged.actualReps ?: 0}s",
                                color = MV.OnSurface, fontSize = 14.sp,
                                modifier = Modifier.weight(1f))
                            Text("✓", color = MV.Green, fontWeight = FontWeight.Bold)
                        }
                    } else {
                        LoggedSetRow(
                            n, logged.actualWeightLb, logged.actualReps ?: 0,
                            logged.rating ?: 0,
                            sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                        )
                    }
                } else if (timed && n == nextSet) {
                    TimedSetRow(
                        n = n, holdSeconds = wex.targetRepsLow,
                        sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                        onComplete = { elapsed, rating ->
                            // Logs actual seconds held + the user's
                            // rating (5 / 4 / 1). The next session's
                            // generator reads this history and adjusts
                            // the target via adjust_mobility_target().
                            onLogSet(n, null, elapsed, rating)
                            inputs.remove(key)
                        },
                    )
                } else if (timed) {
                    PendingSetRow(n, bilateralSideLabel(n, wex.targetSets, info))
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
                        sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                    )
                } else {
                    PendingSetRow(n, bilateralSideLabel(n, wex.targetSets, info))
                }
            }
        }
    }
}

/** Time-based exercises use a countdown instead of a weight/reps form.
 *  Mobility entries declare it explicitly via the catalog `is_timed`
 *  flag (rep-based mobility like Thread-the-Needle / Cat-Cow returns
 *  false). Non-mobility falls through to the prior heuristic. */
internal fun isTimedExercise(
    wex: StrengthWorkoutExerciseRow, info: StrengthExerciseInfo?,
): Boolean {
    if (info?.movementPattern == "mobility") return info.isTimed
    if (wex.targetWeightLb == null
        && wex.targetRepsLow == wex.targetRepsHigh
        && wex.targetRepsLow >= 20) return true
    return false
}

/** For bilateral mobility (sets=2: one per side), label the sets
 *  Right / Left instead of 1 / 2. Returns null when the exercise isn't
 *  bilateral or the set count doesn't match the expected R/L pattern. */
internal fun bilateralSideLabel(
    setNumber: Int, totalSets: Int, info: StrengthExerciseInfo?,
): String? {
    if (info?.isBilateral != true) return null
    if (totalSets != 2) return null
    return if (setNumber == 1) "R" else "L"
}

@Composable
private fun TimedSetRow(
    n: Int,
    holdSeconds: Int,
    onComplete: (elapsedSeconds: Int, rating: Int) -> Unit,
    sideLabel: String? = null,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var startedAt by remember { mutableLongStateOf(0L) }
    var endsAt by remember { mutableLongStateOf(0L) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    // Non-null = countdown finished (or user tapped Done early); show
    // the rating prompt for this many seconds before logging.
    var pendingElapsed by remember { mutableStateOf<Int?>(null) }
    val running = endsAt > 0L
    LaunchedEffect(endsAt) {
        if (endsAt == 0L) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(250L)
            nowMs = System.currentTimeMillis()
            if (nowMs >= endsAt) {
                pendingElapsed = holdSeconds
                endsAt = 0L
                app.myvitals.update.Notifier.postHoldDone(context)
                break
            }
        }
    }
    val remaining = if (running) ((endsAt - nowMs).coerceAtLeast(0L) / 1000L).toInt() else null

    // Three-state row: rating prompt, running countdown, or idle Start button.
    if (pendingElapsed != null) {
        // Rate the set: 💪 easy = RPE 5, ✓ smooth = 4, ✗ failed = 1.
        // Logs (elapsed, rating); the SetEntry on next render will be
        // skipped because the parent moves to the next set.
        Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    sideLabel ?: "$n",
                    color = if (sideLabel != null) Color(0xFFA78BFA) else MV.OnSurfaceVariant,
                    fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
                    modifier = Modifier.width(20.dp),
                )
                Text(
                    "${pendingElapsed}s held — how was it?",
                    color = MV.OnSurface, fontSize = 13.sp,
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(6.dp))
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.padding(start = 20.dp),
            ) {
                RateButton("Easy", "💪", Color(0xFF22C55E)) {
                    onComplete(pendingElapsed!!, 5); pendingElapsed = null
                }
                RateButton("Smooth", "✓", Color(0xFFA78BFA)) {
                    onComplete(pendingElapsed!!, 4); pendingElapsed = null
                }
                RateButton("Failed", "✗", Color(0xFFEF4444)) {
                    onComplete(pendingElapsed!!, 1); pendingElapsed = null
                }
            }
        }
        return
    }

    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            sideLabel ?: "$n",
            color = if (sideLabel != null) Color(0xFFA78BFA) else MV.OnSurfaceVariant,
            fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(20.dp),
        )
        if (remaining != null) {
            Box(
                Modifier
                    .padding(horizontal = 8.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color(0x21A78BFA))
                    .padding(horizontal = 12.dp, vertical = 4.dp),
            ) {
                Text(
                    if (remaining >= 60)
                        "${remaining / 60}:${(remaining % 60).toString().padStart(2, '0')}"
                    else "${remaining}s",
                    color = Color(0xFFA78BFA), fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text("of ${holdSeconds}s",
                color = MV.OnSurfaceVariant, fontSize = 11.sp,
                modifier = Modifier.weight(1f))
            TextButton(onClick = {
                // "Done" — end the hold early but still capture it.
                val elapsed = ((nowMs - startedAt) / 1000L).coerceAtLeast(1L).toInt()
                pendingElapsed = elapsed
                endsAt = 0L
            }) {
                Text("Done", color = Color(0xFFA78BFA),
                     fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            }
            TextButton(onClick = { endsAt = 0L }) {
                Text("Cancel", color = MV.OnSurfaceVariant, fontSize = 12.sp)
            }
        } else {
            Text("${holdSeconds}s hold",
                color = MV.OnSurfaceVariant, fontSize = 13.sp,
                modifier = Modifier.weight(1f))
            Button(
                onClick = {
                    startedAt = System.currentTimeMillis()
                    endsAt = startedAt + holdSeconds * 1000L
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color(0xFFA78BFA), contentColor = Color.White,
                ),
            ) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null,
                    modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(4.dp))
                Text("Start", fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun RateButton(label: String, glyph: String, color: Color, onClick: () -> Unit) {
    Box(
        Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.14f))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(glyph, fontSize = 13.sp)
            Spacer(Modifier.width(4.dp))
            Text(label, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun LoggedSetRow(n: Int, weightLb: Double?, reps: Int, rating: Int,
                          sideLabel: String? = null) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            sideLabel ?: "$n",
            color = if (sideLabel != null) Color(0xFFA78BFA) else MV.OnSurfaceVariant,
            fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(20.dp),
        )
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
private fun PendingSetRow(n: Int, sideLabel: String? = null) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            sideLabel ?: "$n",
            color = MV.OnSurfaceDim,
            fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(20.dp),
        )
        Text("waiting", color = MV.OnSurfaceDim, fontSize = 13.sp)
    }
}

@Composable
private fun SetEntryRow(
    n: Int, input: SetInput,
    onWeight: (String) -> Unit, onReps: (String) -> Unit,
    onRating: (Int) -> Unit, canLog: Boolean,
    onLog: () -> Unit, onFailed: () -> Unit,
    sideLabel: String? = null,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (sideLabel != null) "$sideLabel side" else "Set $n",
                color = if (sideLabel != null) Color(0xFFA78BFA) else MV.OnSurface,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.width(72.dp),
            )
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
