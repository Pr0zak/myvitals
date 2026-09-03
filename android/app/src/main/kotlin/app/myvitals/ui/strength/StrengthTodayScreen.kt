package app.myvitals.ui.strength

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
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
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.FitnessCenter
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.QueryStats
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.layout.fillMaxHeight
import app.myvitals.ui.neon.NeonNumberFamily
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
import app.myvitals.ui.neon.NeonMV
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import app.myvitals.update.Notifier
import coil.compose.AsyncImage
import androidx.compose.ui.graphics.ColorFilter
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Vitality Neon palette holder for this screen. Every value branches the
 * classic MV token to its NeonMV analogue so that with `neon == false`
 * the holder returns the *exact* current colors (byte-for-byte) and with
 * `neon == true` the screen adopts the neon shell.
 *
 * Plumbed via a CompositionLocal so the top-level private helper
 * composables (RestTimerBar, ExerciseCard, CoachCard, …) can read it
 * without any signature change. `StrengthTodayScreen` reads
 * `settings.neonShellEnabled` once and provides the resolved palette.
 */
internal class StrengthPalette(val neon: Boolean) {
    // bg / surface / text
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val cardLow = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val dim = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    val outlineV = if (neon) NeonMV.Line else MV.OutlineVariant

    // semantics
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed          // generic accent / log
    val good = if (neon) NeonMV.Lime else MV.Green               // completed / open / CTA
    val caution = if (neon) NeonMV.Amber else MV.Amber           // caution / elevated
    val bad = if (neon) NeonMV.Bad else MV.Red                   // failed / destructive
    val rest = if (neon) NeonMV.Cyan else MV.BrandRed            // rest-timer running ring
    val info = if (neon) NeonMV.Cyan else Color(0xFF38BDF8)      // paused / focus / sky
    val violet = if (neon) NeonMV.Magenta else Color(0xFFA78BFA) // superset / icon tint / variety
    // set-rating button colors live in ratingColor(r, pal):
    // Failed->Bad, Hard->Amber, Good->Lime, Easy->Cyan under neon.
}

internal val LocalStrengthPalette = staticCompositionLocalOf { StrengthPalette(false) }

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun StrengthTodayScreen(
    settings: SettingsRepository,
    onOpenHistory: () -> Unit,
    onOpenCatalog: () -> Unit = {},
    onOpenTrainingPrefs: () -> Unit = {},
    onOpenEquipment: () -> Unit = {},
    onOpenCoach: () -> Unit = {},
    onOpenDay: (dateIso: String) -> Unit = {},
    onOpenCharts: () -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repo = remember(settings) { StrengthRepository(context, settings) }

    // THE SIGNAL — neon shell active? When false every color below is the
    // current classic value, byte-for-byte. The palette is plumbed to the
    // top-level helpers via LocalStrengthPalette.
    val neon = settings.neonShellEnabled
    val pal = remember(neon) { StrengthPalette(neon) }

    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var catalog by remember { mutableStateOf<Map<String, StrengthExerciseInfo>>(emptyMap()) }
    var recoveryReason by remember { mutableStateOf<String?>(null) }

    // OG2-A8: hold the screen on for exactly as long as a workout is
    // RUNNING. The comment above this said "during the active workout" and
    // the code said `DisposableEffect(Unit)` — keyed to the composable, not
    // to the workout — so the flag went up whenever this screen was on top.
    // Reading a rest-day plan, or a session finished an hour ago, pinned the
    // display awake and drained the battery for no session at all.
    //
    // `paused` releases deliberately: WP-14 pause means the user has stepped
    // away, which is the one moment during a session when the screen should
    // be allowed to sleep.
    //
    // Known and not fixed here: navigating to Charts or History mid-session
    // leaves this composable, so the effect disposes and the flag drops until
    // the user comes back. Holding it past dispose is worse — a user who
    // navigates away and never returns would leave the display pinned on with
    // nothing left to clear it. Fixing it properly means owning the flag
    // above the NavHost, keyed off shared in-progress state, which is a
    // larger change than this defect warrants.
    androidx.compose.runtime.DisposableEffect(workout?.status) {
        val activity = context as? android.app.Activity
        val running = workout?.status == "in_progress"
        if (running) {
            activity?.window?.addFlags(
                android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
            )
        }
        onDispose {
            if (running) {
                activity?.window?.clearFlags(
                    android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                )
            }
        }
    }
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
    // OG2-A4: the dates the generator will actually train on, from the
    // server. Replaces a local copy of the weekday table that disagreed
    // with the generator and could not represent a cardio or yoga day.
    var projectedDates by remember { mutableStateOf<Set<String>>(emptySet()) }
    var loading by remember { mutableStateOf(true) }
    var generating by remember { mutableStateOf(false) }
    var deferring by remember { mutableStateOf(false) }
    var swapWexId by remember { mutableStateOf<Long?>(null) }
    var swapping by remember { mutableStateOf(false) }
    // TD-10 — appending an off-plan exercise. Until this there was no route
    // that added an exercise to a session at all, so three extra sets of
    // curls done in the moment had nowhere to go and were invisible to
    // tonnage, the volume audit, PRs and every AI payload.
    var addSheetOpen by remember { mutableStateOf(false) }
    var addQuery by remember { mutableStateOf("") }
    var adding by remember { mutableStateOf(false) }
    var customSheetOpen by remember { mutableStateOf(false) }
    var customGenerating by remember { mutableStateOf(false) }
    // Cardio-day "Log this workout" flow — see the dialog at the bottom
    // of the file. Opens when split_focus is cardio/yoga/active_recovery.
    var showCardioLog by remember { mutableStateOf(false) }
    var cardioLogging by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    // SKIP-1 — per-slot skip plumbing.
    //  - the in-flight id disables that card's Skip / Undo: a double tap races
    //    two whole-workout responses into the same state.
    //  - a skip refusal (the 409 "N set(s) already logged for this exercise")
    //    lands on the offending card, never in the screen-level error slot —
    //    a message about one exercise shouldn't read as "the plan failed".
    var skipBusyWexId by remember { mutableStateOf<Long?>(null) }
    var skipError by remember { mutableStateOf<Pair<Long, String>?>(null) }
    // Completion PATCH in flight — the Complete CTA stays disabled until it
    // settles so a second tap can't double-finish the session.
    var finishing by remember { mutableStateOf(false) }
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
    // OG2-A9: the logged set currently being corrected, "<wexId>-<setNumber>".
    // Hoisted above `items(orderedExercises)` deliberately — every mutation
    // ends in reload(), and state held inside a LazyColumn item is dropped on
    // slot churn. That is the recorded CoachCard failure, one screen over.
    var editingSetKey by remember { mutableStateOf<String?>(null) }
    var restEndsAt by remember { mutableLongStateOf(0L) }
    var restTotal by remember { mutableLongStateOf(0L) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun reload() {
        loading = true
        error = null
        // A skip refusal is about the plan we're replacing — carrying it onto
        // the fresh one would strand a message on a card it no longer describes.
        skipError = null
        try {
            val plan = repo.today()
            val rec = if (plan == null) repo.recovery() else null
            workout = plan
            recoveryReason = rec?.restDayReason
            if (catalog.isEmpty()) catalog = repo.catalog()
            history = repo.listHistory()
            projectedDates = repo.upcoming().map { it.date }.toSet()
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
    // SKIP-1 — server-computed progress. Both surfaces used to count these
    // themselves and disagreed, so these are read verbatim and never re-derived.
    val setsTotal = workout?.setsTotal ?: 0
    val setsDone = workout?.setsDone ?: 0
    val allSetsDone = setsTotal > 0 && setsDone >= setsTotal

    // SKIP-1 — the slots the server would close as skipped if we finished
    // right now: nothing real logged against them and not already declined.
    // Mirrors _close_remaining_exercises so the dialog names exactly what
    // the flag will touch. Catalog names, never raw slugs.
    val unloggedNames: List<String> = workout?.exercises.orEmpty()
        .filter { ex ->
            !ex.skipped && ex.sets.none { it.actualReps != null }
        }
        .map { catalog[it.exerciseId]?.name ?: it.exerciseId.replace('_', ' ') }
    // Non-empty → the finish confirmation is open, listing these names.
    var confirmSkipNames by remember(workout?.id) { mutableStateOf<List<String>>(emptyList()) }

    fun finishWorkout(closeRemaining: Boolean) {
        val id = workout?.id ?: return
        scope.launch {
            finishing = true
            try { workout = repo.completeWorkout(id, closeRemaining); reload() }
            catch (e: Exception) { error = e.message?.take(160) }
            finally { finishing = false }
        }
    }

    /** Single entry point for every interactive "Complete workout" tap.
     *  Asks before letting the server close un-logged slots; completes
     *  straight through when there's nothing to close. */
    fun requestFinish() {
        if (unloggedNames.isEmpty()) finishWorkout(closeRemaining = false)
        else confirmSkipNames = unloggedNames
    }

    if (confirmSkipNames.isNotEmpty()) {
        val n = confirmSkipNames.size
        val names = confirmSkipNames.joinToString(", ")
        // Copy here is canonical and shared verbatim with StrengthToday.vue —
        // the two surfaces wording the same decision differently is its own
        // kind of parity bug.
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { confirmSkipNames = emptyList() },
            title = {
                Text(
                    if (n == 1) "Finish with unlogged exercise?"
                    else "Finish with unlogged exercises?",
                )
            },
            text = {
                Text(
                    if (n == 1) "1 exercise unlogged: $names. Mark it skipped and finish?"
                    else "$n exercises unlogged: $names. Mark them skipped and finish?",
                )
            },
            confirmButton = {
                androidx.compose.material3.TextButton(
                    onClick = {
                        confirmSkipNames = emptyList()
                        finishWorkout(closeRemaining = true)
                    },
                    enabled = !finishing,
                ) { Text(if (finishing) "Finishing…" else "Finish workout", color = pal.good) }
            },
            // "Go back" closes the dialog and does nothing else. In particular
            // it must NOT set completeDialogDismissed — that would suppress the
            // separate auto "Workout complete?" prompt for the rest of the
            // session, which the user never asked to silence.
            dismissButton = {
                androidx.compose.material3.TextButton(
                    onClick = { confirmSkipNames = emptyList() },
                ) { Text("Go back") }
            },
        )
    }

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
                    "All $setsTotal prescribed sets accounted for. Finish and stamp " +
                    "the session, or keep going if you want to add bonus work.",
                )
            },
            confirmButton = {
                androidx.compose.material3.TextButton(
                    onClick = {
                        showCompleteDialog = false
                        requestFinish()
                    },
                ) { Text("Finish workout", color = pal.good) }
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

    // Cardio-day completion dialog: ask the user for a label + duration,
    // then call complete-cardio which mints a manual Activity row.
    if (showCardioLog && workout != null) {
        CardioLogDialog(
            defaultLabel = "Les Mills VR",
            defaultDurationMin = 30,
            submitting = cardioLogging,
            onDismiss = { if (!cardioLogging) showCardioLog = false },
            onSubmit = { label, type, durationMin, endedAt ->
                scope.launch {
                    cardioLogging = true
                    try {
                        // Anchor the HR window to the user's picked end
                        // time: start = end - duration.
                        val startAt = endedAt
                            .minusSeconds(durationMin * 60L)
                        workout = repo.completeCardio(
                            workoutId = workout!!.id,
                            label = label,
                            durationMinutes = durationMin.toDouble(),
                            startAt = startAt,
                            type = type,
                        )
                        showCardioLog = false
                        reload()
                    } catch (e: Exception) {
                        Timber.w(e, "completeCardio failed")
                        error = "Couldn't log cardio: ${e.message?.take(120)}"
                    } finally { cardioLogging = false }
                }
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

    // WP-14 — keep the ongoing "workout paused" notification in sync with
    // status. Posted while paused so it survives leaving the screen (and
    // even the process); cancelled on resume / complete / skip. The
    // notification's Resume / Complete actions route through
    // WorkoutActionReceiver, which works whether or not this screen is alive.
    LaunchedEffect(workout?.status, workout?.id) {
        val w = workout
        if (w != null && w.status == "paused") {
            Notifier.postWorkoutPaused(context, w.id, w.splitFocus)
        } else {
            Notifier.cancelWorkoutPaused(context)
        }
    }

    CompositionLocalProvider(LocalStrengthPalette provides pal) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(pal.bg)
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
                color = pal.muted,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.6.sp,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                workout?.splitFocus?.replace('_', ' ')?.replaceFirstChar(Char::titlecase)
                    ?: "Today",
                color = pal.ink,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            // Quick stats pip when a plan exists
            workout?.let { p ->
                Box(
                    Modifier.clip(RoundedCornerShape(50))
                        .background(pal.cardLow)
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                ) {
                    Text("${p.setsDone}/${p.setsTotal} sets",
                        color = pal.muted, fontSize = 11.sp)
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
                        tint = pal.muted,
                    )
                }
            }
            Box {
                IconButton(onClick = { headerMenuOpen = true }) {
                    Icon(
                        Icons.Outlined.MoreVert,
                        contentDescription = "More",
                        tint = pal.muted,
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
                        text = { Text("Equipment") },
                        leadingIcon = { Icon(Icons.Filled.FitnessCenter, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = { headerMenuOpen = false; onOpenEquipment() },
                    )
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("Coach") },
                        leadingIcon = { Icon(Icons.Filled.Psychology, null,
                            modifier = Modifier.size(16.dp)) },
                        onClick = { headerMenuOpen = false; onOpenCoach() },
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
                    // PDF-1: share / export today's workout as text (Android
                    // share sheet → notes, print apps, messaging, etc.). The
                    // phone analog of web's "Print / Save PDF".
                    workout?.takeIf { it.exercises.isNotEmpty() }?.let { w ->
                        androidx.compose.material3.DropdownMenuItem(
                            text = { Text("Share workout") },
                            leadingIcon = { Icon(Icons.Filled.Share, null,
                                modifier = Modifier.size(16.dp)) },
                            onClick = {
                                headerMenuOpen = false
                                val text = buildWorkoutShareText(w, catalog)
                                val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                                    type = "text/plain"
                                    putExtra(android.content.Intent.EXTRA_SUBJECT,
                                        "${w.splitFocus.replaceFirstChar { it.uppercase() }.replace('_', ' ')} day — ${w.date}")
                                    putExtra(android.content.Intent.EXTRA_TEXT, text)
                                }
                                context.startActivity(
                                    android.content.Intent.createChooser(send, "Share workout"))
                            },
                        )
                    }
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
                                    color = pal.ink) },
                                leadingIcon = { Icon(Icons.Outlined.Close, null,
                                    modifier = Modifier.size(16.dp), tint = pal.ink) },
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
                                color = pal.bad) },
                            leadingIcon = { Icon(Icons.Filled.SkipNext, null,
                                modifier = Modifier.size(16.dp), tint = pal.bad) },
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
            Text("Loading…", color = pal.muted, modifier = Modifier.padding(16.dp))
            return@Column
        }

        error?.let { Text(it, color = pal.bad, modifier = Modifier.padding(8.dp)) }

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
            } else if (!online) {
                // No cached plan + offline. Generating requires the
                // backend (recovery context + RNG), so we can't surface
                // the Generate button — it would just fail. Tell the
                // user why instead.
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = pal.card),
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            "Offline — workout not cached yet",
                            color = pal.ink,
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Today's plan needs the server to generate (recovery + history). " +
                            "Reconnect and the workout will load. Logged sets from offline " +
                            "sessions will sync automatically.",
                            color = pal.muted,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
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
                        containerColor = pal.accent, contentColor = pal.ink,
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

        // Session progress bar — sets done / total for this workout. Lives in
        // the fixed header so it stays pinned while the exercise list scrolls.
        if (setsTotal > 0 && plan.exercises.isNotEmpty()) {
            val frac = (setsDone.toFloat() / setsTotal).coerceIn(0f, 1f)
            val barColor = if (allSetsDone) pal.good else pal.accent
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.weight(1f).height(8.dp)
                        .clip(RoundedCornerShape(50)).background(pal.cardLow),
                ) {
                    Box(
                        Modifier.fillMaxWidth(frac).height(8.dp)
                            .clip(RoundedCornerShape(50)).background(barColor),
                    )
                }
                Spacer(Modifier.width(8.dp))
                Text(
                    "$setsDone/$setsTotal",
                    color = if (allSetsDone) pal.good else pal.muted,
                    fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            Spacer(Modifier.height(8.dp))
        }

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

        // OG2-C2's projected silhouette used to sit HERE, and that was the
        // bug. Everything above the LazyColumn below is a fixed header —
        // this Column has fillMaxSize() and no verticalScroll — so a card
        // roughly 300dp tall could not be scrolled past. On a phone it took
        // the whole first screen of the one page you open in order to log
        // sets, and there was no way to move it out of the way. It now
        // renders inside the list, after the exercises, which is also where
        // StrengthToday.vue has always put it.

        // 7-day strip
        WeekStrip(
            history = history,
            projectedDates = projectedDates,
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
                colors = CardDefaults.cardColors(containerColor = pal.cardLow),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Skipped today's workout day.",
                            color = pal.ink, fontWeight = FontWeight.SemiBold)
                        Text("Tomorrow will generate fresh.",
                            color = pal.muted, fontSize = 12.sp)
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

        // SKIP-1 — a session that's over accepts no more writes. Every slot in
        // it is CLOSED (see isSlotClosed), which is what stops a workout
        // completed before SKIP-1 shipped from still rendering live logging
        // tables: the server's close-remaining sweep only fires on the
        // completed transition and is deliberately not retroactive.
        val sessionOver = plan.status == "completed" || plan.status == "skipped"

        // Float incomplete exercises to the top so the active set card
        // is always visible without scrolling. Within a superset PAIR,
        // alternate by completed-set count (log set 1 of A, then 1 of B,
        // then 2 of A — that's the point of a superset). Non-superset
        // exercises stay in their natural order so the user finishes all
        // sets of A before moving to B — bouncing breaks focus on
        // compound lifts. Done exercises drop to the bottom for reference.
        val orderedExercises = remember(plan.exercises, sessionOver) {
            // Nothing is actionable once the session is over, so nothing
            // floats: render the prescription in its own order.
            if (sessionOver) return@remember plan.exercises.sortedBy { it.orderIndex }

            // Which bucket a slot lands in is decided by its SETS alone — the
            // slot-level skip flag is deliberately not consulted here, so
            // tapping Skip can never move a card. Demoting the one-line strip
            // to the end of the list the moment it's tapped is disorienting
            // mid-session; the user still reads it as "the third thing I was
            // going to do". A declined slot leaves the NOW highlight (below)
            // and the superset alternation (via accountedSets), nothing else.
            fun setsComplete(w: app.myvitals.sync.StrengthWorkoutExerciseRow): Boolean =
                w.sets.count { it.actualReps != null || it.skipped } >= w.targetSets

            val incomplete = plan.exercises.filter { !setsComplete(it) }
            val complete = plan.exercises.filter { setsComplete(it) }
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
                        // Superset partners: alternate by accounted-count
                        // so the next set is always on the partner who's
                        // behind. A declined partner counts as fully
                        // accounted, so it never wins the alternation with
                        // its zero logged sets.
                        exs.sortedWith(
                            compareBy({ accountedSets(it) }, { it.orderIndex }),
                        )
                    }
                }
                .sortedBy { it.first().orderIndex }
                .flatten()

            groupedIncomplete + complete
        }
        // The single set that's genuinely "NOW": the next set of the first
        // not-yet-finished exercise in render order. Every exercise still shows
        // its own entry form (you can log out of order), but only this one gets
        // the NOW chip + strong highlight so the screen has one clear focus.
        // A closed slot — declined, finished, or part of a finished session —
        // is never it.
        val currentExerciseId = orderedExercises.firstOrNull { ex ->
            !isSlotClosed(ex, plan.status)
        }?.id
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
            // FAST-18 — fasted-training banner. Amber. Appears when an
            // active fast crossed the 18h volume-modulation threshold
            // at plan-generation time. Re-read live on every load so
            // it fades once the user breaks the fast.
            val fastCtx = plan.fastingContext
            if (fastCtx != null && fastCtx.active && fastCtx.modulation != "normal") {
                item {
                    val fastAmber = if (neon) NeonMV.Amber else Color(0xFFF59E0B)
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = fastAmber.copy(alpha = 0.08f),
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("⏳", color = fastAmber, fontSize = 16.sp,
                                modifier = Modifier.padding(end = 8.dp))
                            val hrs = fastCtx.currentHours.toInt()
                            val stage = fastCtx.stage.replace('_', ' ')
                            val body = if (fastCtx.modulation == "volume_-20%") {
                                "You're ${hrs}h fasted ($stage) — volume trimmed ~20%, rest +15s."
                            } else {
                                "You're ${hrs}h fasted ($stage) — volume trimmed ~30%, rest +30s. " +
                                    "A Z2 cardio block alongside is a strong option."
                            }
                            Text(
                                body,
                                color = pal.ink, fontSize = 12.sp,
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                }
            }
            // Recovery deload banner — today's weights were auto-eased for
            // low recovery. Cyan. Transparent + one-tap override to full
            // weight, only while still actionable (planned / in_progress).
            if (plan.deloadFactor < 1.0 &&
                (plan.status == "planned" || plan.status == "in_progress")
            ) {
                item {
                    val dlCyan = if (neon) NeonMV.Cyan else Color(0xFF38BDF8)
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = dlCyan.copy(alpha = 0.08f),
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("🪶", fontSize = 16.sp,
                                modifier = Modifier.padding(end = 8.dp))
                            val pct = Math.round((1.0 - plan.deloadFactor) * 100).toInt()
                            Column(Modifier.weight(1f)) {
                                Text("Load eased ~${pct}% for recovery",
                                    color = pal.ink, fontSize = 14.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(
                                    (plan.deloadReason ?: "low recovery")
                                        .replaceFirstChar { it.uppercase() } +
                                        " — feeling strong?",
                                    color = pal.muted, fontSize = 12.sp,
                                )
                            }
                            Button(
                                onClick = {
                                    scope.launch {
                                        try {
                                            workout = repo.regenerate(
                                                force = true, forceFullWeight = true,
                                            )
                                            reload()
                                        } catch (e: Exception) {
                                            error = e.message?.take(160)
                                        }
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = dlCyan),
                                modifier = Modifier.padding(start = 8.dp),
                            ) { Text("Full weight") }
                        }
                    }
                }
            }
            // WP-14 paused banner. Set logging is gated until resume.
            if (plan.status == "paused") {
                item {
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = pal.info.copy(alpha = 0.10f),
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Row(
                            Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text("Workout paused",
                                    color = pal.ink, fontSize = 14.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text("Resume to keep logging — time away won't " +
                                    "count toward your session length.",
                                    color = pal.muted, fontSize = 12.sp)
                            }
                            Button(
                                onClick = {
                                    scope.launch {
                                        try {
                                            workout = repo.resumeWorkout(plan.id); reload()
                                        } catch (e: Exception) {
                                            error = e.message?.take(160)
                                        }
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = pal.info),
                            ) { Text("Resume") }
                        }
                    }
                }
            }
            // OG2-D-2 — the same `notes` on a day that DOES have exercises.
            // The card below renders them only when the plan is empty, so on
            // an ordinary strength day everything the generator said about
            // the plan was web-only: StrengthToday.vue prints them
            // unconditionally right under the header. That gap hid the #WP-8
            // cadence advisory, which is the one note most worth reading,
            // since it explains why untrained days keep appearing as skipped
            // sessions. Muted single paragraph, matching web's "hint subtle"
            // rather than inventing a card the other surface does not have.
            if (plan.exercises.isNotEmpty() && !plan.notes.isNullOrBlank()) {
                item {
                    Text(
                        plan.notes!!,
                        color = pal.muted,
                        fontSize = 12.sp,
                        lineHeight = 17.sp,
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 2.dp),
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
                            containerColor = pal.card,
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
                                color = pal.ink, fontSize = 14.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(bottom = 6.dp),
                            )
                            Text(
                                plan.notes!!,
                                color = pal.muted, fontSize = 13.sp,
                            )
                        }
                    }
                }
            }
            items(orderedExercises, key = { it.id }) { wex ->
                // SKIP-1 — Swap and Skip share one guard: nothing real logged
                // against this slot AND the session still open to edits. Once
                // actuals exist they belong to this exercise, and neither
                // rewriting nor hiding the slot is honest.
                val canEditSlot = !sessionOver &&
                    wex.sets.none { it.actualReps != null && !it.skipped }
                ExerciseCard(
                    wex = wex,
                    info = catalog[wex.exerciseId],
                    inputs = setInputs,
                    canSwap = canEditSlot,
                    canSkip = canEditSlot,
                    closed = isSlotClosed(wex, plan.status),
                    skipBusy = skipBusyWexId == wex.id,
                    // Any skip in flight disables every Skip/Undo button, not
                    // just the tapped one. Each PATCH returns the whole workout
                    // as the server saw it, so two overlapping skips race their
                    // responses and the slower one lands last, wiping the
                    // other's flag until the next refresh.
                    skipLocked = skipBusyWexId != null,
                    skipError = skipError?.takeIf { it.first == wex.id }?.second,
                    isCurrentExercise = wex.id == currentExerciseId,
                    sessionWritable = !sessionOver && plan.status != "paused",
                    editingSetNum = editingSetKey
                        ?.takeIf { it.startsWith("${wex.id}-") }
                        ?.substringAfter("-")?.toIntOrNull(),
                    // -1 is the Cancel signal from the correction row.
                    onEditSet = { n ->
                        editingSetKey = if (n < 0) null else "${wex.id}-$n"
                        if (n < 0) setInputs.clear()
                    },
                    onDeleteSet = { setId ->
                        scope.launch {
                            try {
                                repo.deleteSet(setId)
                                editingSetKey = null
                                setInputs.clear()
                                reload()
                            } catch (e: Exception) {
                                // Online only by design — see the repository
                                // note. Say so rather than queueing a delete
                                // that could replay before the insert it was
                                // meant to remove.
                                Timber.w(e, "deleteSet %d failed", setId)
                                error = "Couldn't delete that set — needs a connection."
                            }
                        }
                    },
                    onLogSet = onLogSet@{ setNum, weight, reps, rating, setType ->
                        // WP-14: resume before logging — a paused session
                        // shouldn't accept new sets.
                        if (workout?.status == "paused") {
                            error = "Workout paused — tap Resume to keep logging."
                            return@onLogSet
                        }
                        scope.launch {
                            val logged = repo.logSet(LogSetRequest(
                                workoutExerciseId = wex.id,
                                setNumber = setNum,
                                targetWeightLb = wex.targetWeightLb,
                                targetReps = wex.targetRepsLow,
                                actualWeightLb = weight,
                                actualReps = reps,
                                rating = rating,
                                setType = setType,
                            ))
                            // PR-1b: transient toast the moment a record falls.
                            // The KIND is the server's call — this used to be
                            // `isWeightPr ? "weight" : "e1RM"`, hard-coded
                            // identically and separately on both clients, and
                            // it could not name a bodyweight or hold record
                            // because neither could ever be detected.
                            if (logged?.prKind != null) {
                                val what = when (logged.prKind) {
                                    "weight" -> "weight"
                                    "e1rm" -> "e1RM"
                                    "added_load" -> "added-weight"
                                    "hold" -> "hold"
                                    "reps" -> "rep"
                                    else -> "personal"
                                }
                                android.widget.Toast.makeText(
                                    context, "🏆 New $what PR!",
                                    android.widget.Toast.LENGTH_SHORT,
                                ).show()
                            }
                            if (logged != null) {
                                // OG2-A9: a correction closes its own editor
                                // and drops its scratch input, so the row
                                // returns to a logged summary instead of
                                // staying an entry form after Save.
                                if (editingSetKey != null) {
                                    editingSetKey = null
                                    setInputs.clear()
                                }
                                // OG2-A7: the server decides, having just
                                // written the set and knowing the whole
                                // session. This block used to hard-code the
                                // 35-second within-round superset rest — and
                                // so did Vue, separately — and neither knew
                                // the session could be over, so finishing a
                                // workout started a countdown while the user
                                // racked the weights. 0 means do not rest.
                                val restMs = logged.restAfterS * 1000L
                                if (restMs > 0L) {
                                    restTotal = restMs
                                    restEndsAt = System.currentTimeMillis() + restTotal
                                }
                            }
                            reload()
                        }
                    },
                    onYouTube = { slug, name ->
                        openYouTube(context, slug, name)
                    },
                    onSwap = { swapWexId = wex.id },
                    // The PATCH answers with the whole workout, counters
                    // included, so there's nothing left to refetch.
                    onSkipChange = { skipped ->
                        scope.launch {
                            skipBusyWexId = wex.id
                            skipError = null
                            try {
                                workout = repo.skipExercise(wex.id, skipped)
                            } catch (e: Exception) {
                                Timber.w(e, "skipExercise %s failed", wex.id)
                                // Verbatim server detail ("N set(s) already
                                // logged for this exercise") on the card it's
                                // about — the screen-level slot would read as
                                // a plan-wide failure.
                                skipError = wex.id to (e.message ?: "Skip failed")
                            } finally { skipBusyWexId = null }
                        }
                    },
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
            // TD-10 — add an off-plan exercise. Offered only while the
            // session is still open: appending to a finished workout would
            // rewrite what was performed rather than record it.
            if (plan.status != "completed" && plan.status != "skipped") {
                item {
                    androidx.compose.material3.TextButton(
                        onClick = { addSheetOpen = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            "+ Add exercise",
                            color = pal.muted, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }
            // OG2-C2: the same silhouette the charts screen shows, projected
            // forward through today's plan. The audit alone counts logged
            // sets, so it can only describe a gap already trained around;
            // here it is still actionable — a slot can be swapped.
            //
            // Below the session rather than above it, matching the web page:
            // the question it answers is "what will this leave me at", which
            // is worth reading once the work in front of you is in view.
            workout?.projectedMuscleVolume?.takeIf { it.isNotEmpty() }?.let { pv ->
                item {
                    Text(
                        "THIS WEEK, AFTER TODAY",
                        color = pal.muted, fontSize = 10.sp,
                        fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp,
                        modifier = Modifier.padding(top = 6.dp, bottom = 2.dp),
                    )
                    // Capped and centred, the way BodyMap.vue caps its svg at
                    // 360px. Without it the canvas is width-driven at a 1.2
                    // aspect, so a wider screen makes the figure taller rather
                    // than bigger — the reason it grew to fill a phone.
                    Box(
                        Modifier.fillMaxWidth(),
                        contentAlignment = Alignment.Center,
                    ) {
                        Box(Modifier.widthIn(max = 360.dp)) {
                            BodyMapCard(
                                muscles = pv.mapValues { (_, r) ->
                                    r.copy(
                                        sets = (r.setsProjected
                                            ?: r.sets.toDouble()).toInt(),
                                        status = r.statusProjected ?: r.status,
                                    )
                                },
                                neon = neon,
                            )
                        }
                    }
                }
            }
            item {
                if (plan.status != "completed" && plan.status != "skipped") {
                    // Cardio-day (no exercises) gets a dialog flow so the
                    // user can name the session + log duration; that mints
                    // an Activity row which feeds the activity feed, HR
                    // chart markers, and the cardio coach dose.
                    val isCardioDay = plan.exercises.isEmpty() &&
                        plan.splitFocus in listOf("cardio", "active_recovery", "yoga")
                    if (plan.status == "paused") {
                        // WP-14 — resume is the primary action while paused.
                        Button(
                            onClick = {
                                scope.launch {
                                    try { workout = repo.resumeWorkout(plan.id); reload() }
                                    catch (e: Exception) { error = e.message?.take(160) }
                                }
                            },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = pal.info),
                        ) { Text("Resume workout") }
                    } else {
                        // SKIP-1 — the CTA is live whenever the session is
                        // (this whole block is already gated on that) and no
                        // completion is in flight. There is deliberately no
                        // "you haven't logged anything yet" gate: finishing a
                        // session you walked away from is the flagship SKIP-1
                        // flow, and the confirmation names what it will close.
                        Button(
                            onClick = {
                                if (isCardioDay) {
                                    showCardioLog = true
                                } else {
                                    requestFinish()
                                }
                            },
                            enabled = !finishing,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 12.dp),
                            colors = if (neon) ButtonDefaults.buttonColors(
                                containerColor = pal.good, contentColor = NeonMV.OnAccent,
                            ) else ButtonDefaults.buttonColors(containerColor = MV.Green),
                        ) {
                            Text(
                                when {
                                    isCardioDay -> "Log this workout"
                                    finishing -> "Finishing…"
                                    else -> "Complete workout"
                                },
                            )
                        }
                        // WP-14 — Pause, for strength sessions already underway.
                        val started = setsDone > 0 || plan.status == "in_progress"
                        if (!isCardioDay && started) {
                            OutlinedButton(
                                onClick = {
                                    scope.launch {
                                        try { workout = repo.pauseWorkout(plan.id); reload() }
                                        catch (e: Exception) { error = e.message?.take(160) }
                                    }
                                },
                                modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp),
                            ) { Text("Pause workout") }
                        }
                    }
                }
                if (plan.status == "completed") {
                    Card(
                        colors = CardDefaults.cardColors(containerColor = pal.card),
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    "✓ Workout complete — see you tomorrow",
                                    color = pal.good, fontSize = 15.sp,
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
                                        tint = pal.muted,
                                        modifier = Modifier.size(14.dp),
                                    )
                                    Spacer(Modifier.width(4.dp))
                                    Text("Redo", color = pal.muted, fontSize = 12.sp)
                                }
                            }
                            // SKIP-1 — what the session actually amounted to,
                            // straight from the server counters. Same subtitle
                            // as the web's "Workout complete" card.
                            Text(
                                "${plan.setsDone}/${plan.setsTotal} sets · " +
                                    "${plan.exercisesDone}/${plan.exercisesTotal} exercises",
                                color = pal.muted, fontSize = 12.sp,
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
                containerColor = pal.card,
            ) {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Text(
                        "Swap exercise",
                        color = pal.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "Currently: ${current.name}",
                        color = pal.muted, fontSize = 12.sp,
                        modifier = Modifier.padding(top = 2.dp, bottom = 8.dp),
                    )
                    if (alternatives.isEmpty()) {
                        Text("No alternatives in your equipment for this slot.",
                            color = pal.muted, fontSize = 13.sp)
                    } else {
                        alternatives.forEach { alt ->
                            Card(
                                colors = CardDefaults.cardColors(containerColor = pal.cardLow),
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
                                    Text(alt.name, color = pal.ink, fontSize = 14.sp,
                                        fontWeight = FontWeight.SemiBold)
                                    Text(
                                        "${alt.movementPattern.replace('_', ' ')} · ${alt.primaryMuscle}",
                                        color = pal.muted, fontSize = 11.sp,
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

    // ── Add-exercise sheet (TD-10) ──────────────────────────────
    if (addSheetOpen && workout != null) {
        val inWorkout = workout!!.exercises.map { it.exerciseId }.toSet()
        val q = addQuery.trim().lowercase()
        val candidates = catalog.values
            .filter { it.id !in inWorkout }
            .filter {
                q.isEmpty() ||
                    it.name.lowercase().contains(q) ||
                    it.primaryMuscle.lowercase().contains(q)
            }
            .sortedBy { it.name }
            .take(20)
        androidx.compose.material3.ModalBottomSheet(
            onDismissRequest = { addSheetOpen = false },
            containerColor = pal.card,
        ) {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text(
                    "Add exercise",
                    color = pal.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "The weight comes from your history, the same way the planner " +
                        "does it — you pick the movement.",
                    color = pal.muted, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 2.dp, bottom = 8.dp),
                )
                androidx.compose.material3.OutlinedTextField(
                    value = addQuery,
                    onValueChange = { addQuery = it },
                    singleLine = true,
                    label = { Text("Search by name or muscle") },
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                )
                if (candidates.isEmpty()) {
                    Text(
                        "Nothing matches — every exercise in your equipment is " +
                            "either already in today's session or filtered out.",
                        color = pal.muted, fontSize = 13.sp,
                    )
                } else {
                    candidates.forEach { alt ->
                        Card(
                            colors = CardDefaults.cardColors(containerColor = pal.cardLow),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp)
                                .clickable(enabled = !adding) {
                                    scope.launch {
                                        adding = true
                                        try {
                                            repo.addExercise(workout!!.id, alt.id)
                                            reload()
                                            addSheetOpen = false
                                            addQuery = ""
                                        } catch (e: Exception) {
                                            // This one genuinely needs the
                                            // network: the prescription is
                                            // server compute, so there is
                                            // nothing honest to buffer.
                                            error = e.message?.take(160)
                                        } finally { adding = false }
                                    }
                                },
                        ) {
                            Column(modifier = Modifier.padding(12.dp)) {
                                Text(alt.name, color = pal.ink, fontSize = 14.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(
                                    "${alt.movementPattern.replace('_', ' ')} · ${alt.primaryMuscle}",
                                    color = pal.muted, fontSize = 11.sp,
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.height(16.dp))
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
    }  // end CompositionLocalProvider(LocalStrengthPalette)
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun CustomWorkoutSheet(
    generating: Boolean,
    onDismiss: () -> Unit,
    onGenerate: (type: String, durationMin: Int, difficulty: String) -> Unit,
) {
    val pal = LocalStrengthPalette.current
    var type by remember { mutableStateOf("strength") }
    var difficulty by remember { mutableStateOf("normal") }
    var durationMin by remember { mutableIntStateOf(45) }
    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = pal.card,
    ) {
        Column(modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp)) {
            Text(
                "Custom workout",
                color = pal.ink, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
            )
            Text(
                "Generate a one-off session — the planner picks exercises sized to "
                + "your duration + difficulty.",
                color = pal.muted, fontSize = 12.sp,
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
                    containerColor = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA),
                    contentColor = if (pal.neon) NeonMV.OnAccent else Color.White,
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
    val pal = LocalStrengthPalette.current
    val bg = if (!online)
        (if (pal.neon) NeonMV.Amber.copy(alpha = 0.20f) else Color(0x33EAB308))
        else (if (pal.neon) NeonMV.Magenta.copy(alpha = 0.20f) else Color(0x33A78BFA))
    val fg = if (!online)
        (if (pal.neon) NeonMV.Amber else Color(0xFFEAB308))
        else (if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA))
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
    val pal = LocalStrengthPalette.current
    Text(
        text,
        color = pal.muted, fontSize = 11.sp,
        fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
        modifier = Modifier.padding(bottom = 6.dp),
    )
}

@Composable
private fun PillChip(label: String, selected: Boolean, onClick: () -> Unit) {
    val pal = LocalStrengthPalette.current
    val pillAccent = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA)
    androidx.compose.foundation.layout.Box(
        modifier = Modifier
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(999.dp))
            .background(
                if (selected)
                    (if (pal.neon) NeonMV.Magenta.copy(alpha = 0.20f) else Color(0x33A78BFA))
                else (if (pal.neon) NeonMV.Card else Color(0x141A2332)),
            )
            .border(
                width = 1.dp,
                color = if (selected) pillAccent
                        else (if (pal.neon) NeonMV.Magenta.copy(alpha = 0.25f) else Color(0x40A78BFA)),
                shape = androidx.compose.foundation.shape.RoundedCornerShape(999.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(
            label,
            color = if (selected) pillAccent else pal.muted,
            fontSize = 13.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}

// ── Pieces ──────────────────────────────────────────────────────

@Composable
private fun RestDayCard(reason: String, generating: Boolean, onForceGenerate: () -> Unit) {
    val pal = LocalStrengthPalette.current
    Card(
        colors = CardDefaults.cardColors(containerColor = pal.card),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Rest day recommended",
                color = pal.caution, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Text(reason, color = pal.muted, fontSize = 14.sp)
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
private fun ContextRow(plan: StrengthWorkoutDetail) {
    val pal = LocalStrengthPalette.current
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "${plan.splitFocus.replaceFirstChar { it.titlecase() }} day · "
                + muscleGroupsFor(plan.splitFocus),
            color = pal.ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ContextChip("${plan.setsDone}/${plan.setsTotal} sets")
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
    val pal = LocalStrengthPalette.current
    var expanded by remember(workoutId) { mutableStateOf(false) }
    var explain by remember(workoutId) { mutableStateOf<app.myvitals.sync.StrengthExplain?>(null) }
    var loading by remember(workoutId) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Card(
        colors = CardDefaults.cardColors(containerColor = pal.cardLow),
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
                    color = pal.ink, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f))
                Text(if (expanded) "▾" else "▸",
                    color = pal.muted, fontSize = 14.sp)
            }
            if (expanded) {
                Spacer(Modifier.height(6.dp))
                if (loading && explain == null) {
                    Text("…", color = pal.dim, fontSize = 12.sp)
                } else if (explain != null) {
                    Spacer(Modifier.height(2.dp))
                    val lines = listOf(
                        explain!!.whySplit, explain!!.whyExercises, explain!!.whyTargets,
                    )
                    for ((i, line) in lines.withIndex()) {
                        Text(
                            // strip <strong> for plain phone display
                            line.replace("<strong>", "").replace("</strong>", ""),
                            color = pal.muted, fontSize = 12.sp,
                        )
                        if (i < lines.lastIndex) Spacer(Modifier.height(4.dp))
                    }
                } else {
                    Text("No rationale available.",
                        color = pal.dim, fontSize = 12.sp)
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
    val pal = LocalStrengthPalette.current

    Card(
        colors = CardDefaults.cardColors(containerColor = pal.cardLow),
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
                    color = pal.ink, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f))
                val visibleCount = swaps?.count { dismissed[it.targetExerciseId] != true } ?: 0
                if (!expanded && visibleCount > 0) {
                    Text("$visibleCount", color = pal.muted, fontSize = 12.sp,
                        modifier = Modifier.padding(end = 6.dp))
                }
                Text(if (expanded) "▾" else "▸",
                    color = pal.muted, fontSize = 14.sp)
            }
            if (expanded) {
                Spacer(Modifier.height(6.dp))
                when {
                    loading -> Text("Thinking…", color = pal.dim, fontSize = 12.sp)
                    failed -> Text("AI nudge unavailable. Check Settings → AI.",
                        color = pal.dim, fontSize = 12.sp)
                    swaps == null -> {}
                    swaps!!.isEmpty() -> Text("Plan looks balanced — no swaps suggested.",
                        color = pal.dim, fontSize = 12.sp)
                    else -> {
                        for (s in swaps!!) {
                            if (dismissed[s.targetExerciseId] == true) continue
                            Spacer(Modifier.height(4.dp))
                            Column(
                                Modifier.fillMaxWidth()
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(pal.card)
                                    .padding(10.dp),
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(s.targetExerciseId.replace('_', ' ')
                                            .replaceFirstChar(Char::titlecase),
                                        color = pal.ink, fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold)
                                    Text(" → ", color = pal.muted, fontSize = 12.sp)
                                    Text(s.replacementExerciseId.replace('_', ' ')
                                            .replaceFirstChar(Char::titlecase),
                                        color = pal.good, fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold)
                                }
                                Spacer(Modifier.height(2.dp))
                                Text(s.reason, color = pal.muted, fontSize = 11.sp)
                                Spacer(Modifier.height(6.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Button(
                                        onClick = {
                                            onAccept(s.targetExerciseId, s.replacementExerciseId)
                                            dismissed[s.targetExerciseId] = true
                                        },
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = pal.accent,
                                            contentColor = if (pal.neon) NeonMV.OnAccent else MV.OnSurface,
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
    val pal = LocalStrengthPalette.current
    val focusAccent = if (pal.neon) NeonMV.Cyan else Color(0xFFA78BFA)

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
            containerColor = focusAccent.copy(alpha = 0.10f)
        ),
        modifier = Modifier.fillMaxWidth().clickable {
            if (cue == null) load() else expanded = !expanded
        },
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("◇", color = focusAccent, fontSize = 14.sp,
                    modifier = Modifier.padding(end = 6.dp))
                Text(
                    cue?.headline?.takeIf { it.isNotEmpty() } ?: "Focus cue",
                    color = pal.ink, fontSize = 13.sp,
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
                    color = pal.muted, fontSize = 12.sp,
                )
            }
            if (expanded && cue != null && cue!!.cue.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text(cue!!.cue, color = pal.ink, fontSize = 12.sp)
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
    val pal = LocalStrengthPalette.current

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
            colors = CardDefaults.cardColors(containerColor = pal.cardLow),
            modifier = Modifier.fillMaxWidth().clickable { refresh() },
        ) {
            Row(
                Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("▲ Deload check",
                    color = pal.ink, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text(
                    when {
                        loading -> "Reading…"
                        failed -> "Unavailable"
                        else -> "Ask AI"
                    },
                    color = pal.muted, fontSize = 12.sp,
                )
            }
        }
        return
    }

    if (j.severity == "none") return  // no banner when AI says all clear

    val accent = when (j.severity) {
        "light" -> if (pal.neon) NeonMV.Amber else Color(0xFFFACC15)
        "moderate" -> if (pal.neon) NeonMV.Amber else Color(0xFFF97316)
        "rest" -> if (pal.neon) NeonMV.Bad else Color(0xFFEF4444)
        else -> pal.muted
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
                    color = pal.ink, fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    j.headline,
                    color = pal.ink, fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                Text(if (expanded) "▾" else "▸",
                    color = pal.muted, fontSize = 14.sp)
            }
            if (expanded) {
                Spacer(Modifier.height(6.dp))
                for (e in j.evidence) {
                    Text("• $e", color = pal.muted, fontSize = 12.sp,
                        modifier = Modifier.padding(vertical = 1.dp))
                }
                if (j.recommendation.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "What to do: ${j.recommendation}",
                        color = pal.ink, fontSize = 12.sp,
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
    val pal = LocalStrengthPalette.current

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
        "rest" -> if (pal.neon) NeonMV.Bad else Color(0xFFEF4444)
        "moderate" -> if (pal.neon) NeonMV.Amber else Color(0xFFF97316)
        "light" -> if (pal.neon) NeonMV.Amber else Color(0xFFFACC15)
        else -> null
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = pal.card),
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
                    "Coach", color = pal.ink, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                val sevPill = state.deload?.severity?.takeIf { it != "none" }
                if (!state.cardOpen && sevPill != null) {
                    val sevColorPill = when (sevPill) {
                        "rest" -> if (pal.neon) NeonMV.Bad else Color(0xFFEF4444)
                        "moderate" -> if (pal.neon) NeonMV.Amber else Color(0xFFF97316)
                        "light" -> if (pal.neon) NeonMV.Amber else Color(0xFFFACC15)
                        else -> pal.muted
                    }
                    Text(
                        "Deload $sevPill",
                        color = sevColorPill, fontSize = 11.sp,
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(sevColorPill.copy(alpha = 0.15f))
                            .padding(horizontal = 8.dp, vertical = 2.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                }
                Text(
                    if (state.cardOpen) "−" else "+",
                    color = pal.muted, fontSize = 16.sp,
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
                    ?: if (state.deload != null) pal.good else pal.muted,
                expanded = state.openDeload,
                accent = sevColor,
                onToggle = { state.openDeload = !state.openDeload },
            ) {
                val d = state.deload
                if (d != null && d.severity != "none") {
                    Text(d.headline, color = pal.ink, fontSize = 12.sp,
                        fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(4.dp))
                    for (e in d.evidence) {
                        Text("• $e", color = pal.muted, fontSize = 11.sp,
                            modifier = Modifier.padding(vertical = 1.dp))
                    }
                    if (d.recommendation.isNotEmpty()) {
                        Spacer(Modifier.height(4.dp))
                        Text("What to do: ${d.recommendation}",
                            color = pal.ink, fontSize = 11.sp)
                    }
                } else if (d != null) {
                    Text("No deload needed.", color = pal.muted, fontSize = 11.sp)
                } else if (state.deloadLoading) {
                    Text("Thinking…", color = pal.muted, fontSize = 11.sp)
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
                pillColor = if (state.focus != null) pal.info else pal.muted,
                expanded = state.openFocus,
                accent = null,
                onToggle = {
                    state.openFocus = !state.openFocus
                    if (state.openFocus) loadFocus()
                },
            ) {
                val f = state.focus
                if (f != null) {
                    Text(f.headline, color = pal.ink, fontSize = 12.sp,
                        fontWeight = FontWeight.Medium)
                    if (f.cue.isNotEmpty()) {
                        Spacer(Modifier.height(3.dp))
                        Text(f.cue, color = pal.ink, fontSize = 11.sp)
                    }
                } else if (state.focusLoading) {
                    Text("Thinking…", color = pal.muted, fontSize = 11.sp)
                } else {
                    Text("Tap to load.", color = pal.muted, fontSize = 11.sp)
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
                    pal.violet
                else if (state.swaps != null) pal.good
                else pal.muted,
                expanded = state.openVariety,
                accent = null,
                onToggle = {
                    state.openVariety = !state.openVariety
                    if (state.openVariety) loadSwaps()
                },
            ) {
                if (state.swapsLoading) {
                    Text("Thinking…", color = pal.muted, fontSize = 11.sp)
                } else if (state.swaps == null) {
                    Text("Tap to load.", color = pal.muted, fontSize = 11.sp)
                } else if (visibleSwaps.isEmpty()) {
                    Text("Plan looks balanced — no swaps suggested.",
                        color = pal.muted, fontSize = 11.sp)
                } else {
                    for (s in visibleSwaps) {
                        Column(
                            Modifier
                                .fillMaxWidth()
                                .padding(top = 4.dp)
                                .clip(RoundedCornerShape(6.dp))
                                .background(pal.cardLow)
                                .padding(8.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(s.targetExerciseId.replace('_', ' ')
                                        .replaceFirstChar(Char::titlecase),
                                    color = pal.ink, fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(" → ", color = pal.muted, fontSize = 11.sp)
                                Text(s.replacementExerciseId.replace('_', ' ')
                                        .replaceFirstChar(Char::titlecase),
                                    color = pal.good, fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold)
                            }
                            Spacer(Modifier.height(2.dp))
                            Text(s.reason, color = pal.muted, fontSize = 10.sp)
                            Spacer(Modifier.height(4.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                Button(
                                    onClick = {
                                        onAcceptSwap(s.targetExerciseId, s.replacementExerciseId)
                                        // Implicit dismiss — swap is applied; no point showing it.
                                        state.dismissed[s.targetExerciseId] = true
                                    },
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = pal.accent,
                                        contentColor = if (pal.neon) NeonMV.OnAccent else MV.OnSurface,
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
                pillColor = pal.muted,
                expanded = state.openWhy,
                accent = null,
                onToggle = {
                    state.openWhy = !state.openWhy
                    if (state.openWhy) loadExplain()
                },
            ) {
                val ex = state.explain
                if (state.explainLoading) {
                    Text("…", color = pal.muted, fontSize = 11.sp)
                } else if (ex == null) {
                    Text("Tap to load.", color = pal.muted, fontSize = 11.sp)
                } else {
                    Text("WHY THIS SPLIT", color = pal.muted, fontSize = 9.sp)
                    Text(ex.whySplit, color = pal.ink, fontSize = 11.sp)
                    Spacer(Modifier.height(4.dp))
                    Text("WHY THESE EXERCISES", color = pal.muted, fontSize = 9.sp)
                    Text(ex.whyExercises, color = pal.ink, fontSize = 11.sp)
                    Spacer(Modifier.height(4.dp))
                    Text("WHY THESE TARGETS", color = pal.muted, fontSize = 9.sp)
                    Text(ex.whyTargets, color = pal.ink, fontSize = 11.sp)
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
    val pal = LocalStrengthPalette.current
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
            Text(icon, color = accent ?: pal.muted, fontSize = 12.sp,
                modifier = Modifier.padding(end = 6.dp).width(14.dp))
            Text(title, color = pal.ink, fontSize = 12.sp,
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
            Text(if (expanded) "−" else "+", color = pal.muted, fontSize = 13.sp)
        }
        if (expanded) {
            Spacer(Modifier.height(4.dp))
            Column(Modifier.padding(start = 18.dp)) { body() }
        }
    }
}

@Composable
private fun ContextChip(text: String) {
    val pal = LocalStrengthPalette.current
    Box(
        Modifier
            .clip(RoundedCornerShape(50))
            .background(pal.cardLow)
            .border(1.dp, pal.outlineV, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) { Text(text, color = pal.muted, fontSize = 12.sp) }
}

@Composable
private fun RestTimerBar(
    remainingS: Long, totalS: Long,
    onAdd30: () -> Unit, onSkip: () -> Unit,
) {
    val pal = LocalStrengthPalette.current
    val done = remainingS <= 0
    // Rest-timer ring/readout: Cyan while running (rest semantics), good
    // (lime/green) when done. Classic keeps brand-red running / green done.
    val runningColor = pal.rest
    val doneColor = pal.good
    val ringColor = if (done) doneColor else runningColor
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (done) doneColor.copy(alpha = 0.18f) else runningColor.copy(alpha = 0.18f)
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            val mm = remainingS / 60
            val ss = (remainingS % 60).toString().padStart(2, '0')
            // Depleting countdown ring with the mm:ss readout in the centre.
            val frac = if (totalS > 0) (remainingS.toFloat() / totalS).coerceIn(0f, 1f) else 0f
            Box(Modifier.size(56.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.size(56.dp)) {
                    val sw = 5.dp.toPx()
                    val inset = sw / 2
                    val arcSize = androidx.compose.ui.geometry.Size(size.width - sw, size.height - sw)
                    val topLeft = androidx.compose.ui.geometry.Offset(inset, inset)
                    drawArc(
                        color = ringColor.copy(alpha = 0.18f),
                        startAngle = 0f, sweepAngle = 360f, useCenter = false,
                        topLeft = topLeft, size = arcSize,
                        style = Stroke(width = sw, cap = StrokeCap.Round),
                    )
                    drawArc(
                        color = ringColor,
                        startAngle = -90f, sweepAngle = -360f * frac, useCenter = false,
                        topLeft = topLeft, size = arcSize,
                        style = Stroke(width = sw, cap = StrokeCap.Round),
                    )
                }
                Text(
                    if (done) "rest\nover" else "$mm:$ss",
                    color = ringColor, fontSize = if (done) 12.sp else 16.sp,
                    fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                    lineHeight = 14.sp,
                )
            }
            Column(Modifier.weight(1f)) {
                Text(
                    if (done) "Rest complete" else "Resting",
                    color = if (done) doneColor else runningColor,
                    fontWeight = FontWeight.Bold, fontSize = 15.sp,
                )
                Text(
                    "of ${totalS / 60}:${(totalS % 60).toString().padStart(2, '0')}",
                    color = pal.muted, fontSize = 12.sp,
                )
            }
            TextButton(onClick = onAdd30) {
                Icon(Icons.Filled.Add, contentDescription = null, tint = pal.ink)
                Text(" 30s", color = pal.ink)
            }
            TextButton(onClick = onSkip) {
                Icon(Icons.Filled.SkipNext, contentDescription = null, tint = pal.ink)
                Text(" Skip", color = pal.ink)
            }
        }
    }
}

private data class SetInput(
    var weight: String = "",
    var reps: String = "",
    var rating: Int? = null,
    var setType: String = "working",  // working | warmup | drop | failure (SETTYPE-1)
)

/**
 * SKIP-1 — sets on this slot the user has dealt with, logged or individually
 * skipped, capped at the prescription so a bonus set can't push the slot past
 * its target. Mirrors the backend's `_accounted_sets`; the workout-level
 * counters still come from the server and are rendered verbatim.
 */
internal fun accountedSets(wex: StrengthWorkoutExerciseRow): Int =
    if (wex.skipped) wex.targetSets
    else minOf(
        wex.sets.count { it.actualReps != null || it.skipped },
        wex.targetSets,
    )

/** Nothing left to do on this slot — declined outright, or every prescribed
 *  set accounted for. Mirrors the backend's `_exercise_done`. */
internal fun isSlotSettled(wex: StrengthWorkoutExerciseRow): Boolean =
    wex.skipped || accountedSets(wex) >= wex.targetSets

/**
 * SKIP-1 — the single notion of a CLOSED slot: one nothing can be logged
 * against any more. Either the slot is settled, or the session it belongs to
 * is over. A closed slot never takes the NOW highlight, never floats to the
 * top of the list, and never renders a live set-entry form — which is what
 * stops a workout finished before SKIP-1 shipped (the server's close-remaining
 * sweep is deliberately not retroactive) from still offering to log work the
 * user walked away from. It is display truth only: it writes nothing.
 */
internal fun isSlotClosed(wex: StrengthWorkoutExerciseRow, workoutStatus: String): Boolean =
    isSlotSettled(wex) || workoutStatus == "completed" || workoutStatus == "skipped"

/**
 * The muted one-line form a closed slot takes when there's nothing to show:
 * "Skipped" (declined, with an Undo while the session is still live) or
 * "Not logged" (never touched, on a session that's already over). Neither
 * renders a set-entry form — that's the whole point.
 */
@Composable
private fun SlotStrip(
    label: String,
    state: String,
    error: String? = null,
    trailing: @Composable () -> Unit = {},
) {
    val pal = LocalStrengthPalette.current
    Card(
        colors = CardDefaults.cardColors(containerColor = pal.cardLow),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column {
            Row(
                modifier = Modifier.padding(
                    start = 14.dp, end = 4.dp, top = 4.dp, bottom = 4.dp,
                ),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    label,
                    color = pal.dim, fontSize = 14.sp,
                    modifier = Modifier.weight(1f),
                )
                Text(state, color = pal.muted, fontSize = 12.sp)
                trailing()
            }
            error?.let {
                Text(
                    it, color = pal.bad, fontSize = 11.sp,
                    modifier = Modifier.padding(
                        start = 14.dp, end = 14.dp, bottom = 6.dp,
                    ),
                )
            }
        }
    }
}

@Composable
private fun ExerciseCard(
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    inputs: androidx.compose.runtime.snapshots.SnapshotStateMap<String, SetInput>,
    canSwap: Boolean,
    canSkip: Boolean = false,
    // SKIP-1 — see isSlotClosed. Suppresses every writable affordance.
    closed: Boolean = false,
    // The slot's own Skip / Undo PATCH is in flight, and its last failure.
    skipBusy: Boolean = false,
    skipLocked: Boolean = false,
    skipError: String? = null,
    isCurrentExercise: Boolean = true,
    onLogSet: (setNum: Int, weight: Double?, reps: Int?, rating: Int?, setType: String) -> Unit,
    onYouTube: (slug: String, name: String) -> Unit,
    onSwap: () -> Unit,
    onSkipChange: (Boolean) -> Unit = {},
    onSetPref: (String) -> Unit = {},
    // OG2-A9: which of this slot's logged sets is being corrected, and the
    // two ways out. State lives on the screen, not in the card, because the
    // card is rebuilt by every reload().
    // OG2-A9: whether the SESSION accepts writes. Deliberately not `closed`,
    // which is also true for a slot whose sets are all logged — gating the
    // correction affordance on that hides it exactly when every set is done,
    // which is when a typo is actually noticed.
    sessionWritable: Boolean = true,
    editingSetNum: Int? = null,
    onEditSet: (Int) -> Unit = {},
    onDeleteSet: (setId: Long) -> Unit = {},
    partnerName: String? = null,
    backendBaseUrl: String = "",
) {
    val pal = LocalStrengthPalette.current
    // Violet icon-tint accent → Magenta under neon (exercise/silhouette tint).
    val iconViolet = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA)
    val iconVioletBg = if (pal.neon) NeonMV.Magenta.copy(alpha = 0.12f) else Color(0x14A78BFA)
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    // SKIP-1 — a declined slot collapses to a muted one-line strip. No NOW
    // highlight, no writable set table: the whole point is that a finished
    // session stops offering to log work the user walked away from.
    if (wex.skipped) {
        SlotStrip(
            label = "${wex.orderIndex + 1}. $name",
            state = "Skipped",
            error = skipError,
        ) {
            // Undo rides the same guard as Skip: on a session that's over,
            // un-skipping would be a one-way trip into the "Not logged" strip
            // below with no way back.
            if (canSkip) {
                TextButton(
                    onClick = { onSkipChange(false) },
                    enabled = !skipLocked,
                ) {
                    Text(
                        if (skipBusy) "Restoring…" else "Undo",
                        color = pal.accent, fontSize = 12.sp,
                    )
                }
            }
        }
        return
    }
    // The session is over and this slot was never touched. It is NOT a skip —
    // the user didn't decline it, the sweep just never ran over this workout —
    // so it says so plainly: no Undo, no logging controls, no set-entry form.
    if (closed && wex.sets.none { it.actualReps != null || it.skipped }) {
        SlotStrip(label = "${wex.orderIndex + 1}. $name", state = "Not logged")
        return
    }
    val nextSet = (1..wex.targetSets).firstOrNull { n ->
        wex.sets.none { it.setNumber == n && (it.actualReps != null || it.skipped) }
    }
    val done = nextSet == null
    val supersetColor = wex.supersetId?.let {
        // Stable hash → hue (HSL)
        val h = it.fold(0) { acc, c -> (acc * 31 + c.code) % 360 }
        Color(android.graphics.Color.HSVToColor(floatArrayOf(h.toFloat(), 0.55f, 0.85f)))
    }
    // Tap-icon-for-bigger-view + instructions. The 40dp icon in the
    // card header is too small to actually read the silhouette; the
    // dialog renders a larger image and the catalog's how-to steps.
    var showInfo by remember { mutableStateOf(false) }
    if (showInfo && info != null) {
        ExerciseInfoDialog(
            info = info,
            name = name,
            backendBaseUrl = backendBaseUrl,
            onYouTube = { onYouTube(wex.exerciseId, name) },
            onDismiss = { showInfo = false },
        )
    }
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (done) pal.cardLow else pal.card
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
                    color = supersetColor ?: pal.muted,
                    fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(bottom = 4.dp),
                )
            }
            Row(verticalAlignment = Alignment.Top) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        "${wex.orderIndex + 1}. $name",
                        color = pal.ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                    )
                    // TD-10: keep the plan and its improvisations
                    // distinguishable after the fact. explain_workout and the
                    // AI reviewer make the same distinction, so the UI
                    // should not be the one place that blurs it.
                    if (wex.addedAdHoc) {
                        Text(
                            "ADDED BY YOU",
                            color = pal.accent, fontSize = 9.sp,
                            fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp,
                        )
                    }
                    // OG2-A6: the equipment changed after this plan was made
                    // and it was too late to regenerate. Flagged, never
                    // removed — deleting work from a session already in front
                    // of the user is worse than saying it cannot be done.
                    if (wex.equipmentMissing) {
                        Text(
                            "NEEDS KIT YOU NO LONGER HAVE",
                            color = pal.caution, fontSize = 9.sp,
                            fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp,
                        )
                    }
                    val rep = if (wex.targetRepsLow == wex.targetRepsHigh)
                        "${wex.targetRepsLow}" else "${wex.targetRepsLow}-${wex.targetRepsHigh}"
                    val w = wex.targetWeightLb?.let { " @ ${it}lb" } ?: ""
                    Text(
                        "${wex.targetSets}×$rep$w  ·  ${wex.targetRestS}s rest",
                        color = pal.muted, fontSize = 12.sp,
                    )
                    // PROG-1: program-mode scheme badge on program lifts
                    wex.programScheme?.let {
                        Text(
                            "📈 $it",
                            color = pal.accent, fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                    // OG2-B3: why this weight, in the server's words. It was
                    // a single generic sentence two taps deep in the Coach
                    // card — which is collapsed by default and gone once the
                    // workout is complete — describing an RPE scale this app
                    // does not use, and derived from a different query than
                    // the one that chose the number.
                    wex.notes?.takeIf { it.isNotBlank() }?.let {
                        Text(
                            it,
                            color = pal.muted, fontSize = 11.sp,
                            fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                        )
                    }
                    // LOAD-1: how to load it (only when micro-loaders needed)
                    wex.loadHint?.let {
                        Text(
                            "🏋 $it",
                            color = pal.muted, fontSize = 11.sp,
                        )
                    }
                    // LOG-1: what you did last time (rep-based exercises only)
                    if (!isTimedExercise(wex, info) && wex.lastSets.isNotEmpty()) {
                        val summary = wex.lastSets.joinToString(" · ") { ls ->
                            val wv = ls.weightLb?.let {
                                if (it == it.toLong().toDouble()) "${it.toLong()}"
                                else "%.1f".format(it)
                            }
                            if (wv != null) "$wv×${ls.reps}" else "${ls.reps}"
                        }
                        Text(
                            "↩ last: $summary",
                            color = pal.dim, fontSize = 11.sp,
                        )
                    }
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
                                .background(iconVioletBg)
                                .clickable { showInfo = true },
                            contentAlignment = Alignment.Center,
                        ) {
                            AsyncImage(
                                model = baseUrl + info.imageFront,
                                contentDescription = name,
                                modifier = if (isPhoto) Modifier.size(40.dp)
                                           else Modifier.size(32.dp),
                                colorFilter = if (isPhoto) null
                                              else ColorFilter.tint(iconViolet),
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
                            .background(iconVioletBg)
                            .clickable { showInfo = true },
                        contentAlignment = Alignment.Center,
                    ) {
                        app.myvitals.ui.YogaPoseIcon(
                            id = wex.exerciseId, size = 28.dp,
                            tint = iconViolet,
                        )
                    }
                }
            }

            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { onYouTube(wex.exerciseId, name) }) {
                    Text("YouTube ↗", color = pal.muted, fontSize = 12.sp)
                }
                if (canSwap) {
                    TextButton(onClick = onSwap) {
                        Icon(Icons.Filled.SwapHoriz, contentDescription = null,
                            tint = pal.muted, modifier = Modifier.size(14.dp))
                        Text(" Swap", color = pal.muted, fontSize = 12.sp)
                    }
                }
                if (canSkip) {
                    TextButton(
                        onClick = { onSkipChange(true) },
                        // Disabled while the PATCH is in flight — a double tap
                        // races two whole-workout responses into the same state.
                        enabled = !skipLocked,
                    ) {
                        Icon(Icons.Filled.SkipNext, contentDescription = null,
                            tint = pal.muted, modifier = Modifier.size(14.dp))
                        Text(
                            if (skipBusy) " Skipping…" else " Skip",
                            color = pal.muted, fontSize = 12.sp,
                        )
                    }
                }
                Spacer(Modifier.weight(1f))
                ExercisePrefMenu(onSetPref)
            }
            // A skip refusal — the 409 "N set(s) already logged for this
            // exercise" — belongs on the card it names, verbatim.
            skipError?.let {
                Text(it, color = pal.bad, fontSize = 11.sp)
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
                            Text("$n", color = pal.muted,
                                modifier = Modifier.width(20.dp))
                            Text("Held ${logged.actualReps ?: 0}s",
                                color = pal.ink, fontSize = 14.sp,
                                modifier = Modifier.weight(1f))
                            Text("✓", color = pal.good, fontWeight = FontWeight.Bold)
                        }
                    } else if (editingSetNum == n && sessionWritable) {
                        // OG2-A9: the same entry form, seeded from the truth
                        // by the server's planned_sets prefill. `isCurrent`
                        // is false so the corrected row does not steal the
                        // NOW accent from the set actually next up.
                        SetEntryRow(
                            n = n, input = inputs.getOrPut(key) {
                                SetInput(
                                    weight = logged.actualWeightLb?.toString() ?: "",
                                    reps = (logged.actualReps ?: 0).toString(),
                                    rating = logged.rating,
                                    // The set's real classification, from
                                    // the server's planned_sets rather than
                                    // assumed "working" — correcting a
                                    // warm-up's weight must not silently
                                    // reclassify it and move it into the
                                    // volume audit and next session's load.
                                    setType = wex.plannedSets
                                        .firstOrNull { it.setNumber == n }
                                        ?.setType ?: "working",
                                )
                            },
                            onWeight = { inputs[key] = (inputs[key] ?: SetInput()).copy(weight = it) },
                            onReps = { inputs[key] = (inputs[key] ?: SetInput()).copy(reps = it) },
                            onRating = { inputs[key] = (inputs[key] ?: SetInput()).copy(rating = it) },
                            onSetType = { inputs[key] = (inputs[key] ?: SetInput()).copy(setType = it) },
                            canLog = inputs[key]?.rating != null,
                            onLog = {
                                val inp = inputs[key]
                                onLogSet(n, inp?.weight?.toDoubleOrNull(),
                                    inp?.reps?.toIntOrNull(), inp?.rating,
                                    inp?.setType ?: "working")
                            },
                            // Log it as failed — NOT delete. SetEntryRow's
                            // single button routes to onFailed whenever the
                            // rating is 1, so wiring delete here made
                            // correcting a set to Failed silently destroy it,
                            // unconfirmed, from a button reading "Log set".
                            onFailed = {
                                val inp = inputs[key]
                                onLogSet(n, inp?.weight?.toDoubleOrNull(),
                                    inp?.reps?.toIntOrNull(), 1,
                                    inp?.setType ?: "working")
                            },
                            sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                            isCurrent = false,
                        )
                        // Delete is its own control, said in words, because
                        // it destroys logged work and there is no undo.
                        Row(
                            Modifier.fillMaxWidth().padding(bottom = 4.dp),
                            horizontalArrangement = Arrangement.End,
                        ) {
                            androidx.compose.material3.TextButton(
                                onClick = { onEditSet(-1) },
                            ) { Text("Cancel", color = pal.muted, fontSize = 12.sp) }
                            androidx.compose.material3.TextButton(
                                onClick = { onDeleteSet(logged.id) },
                            ) {
                                Text("Delete set", color = pal.caution, fontSize = 12.sp)
                            }
                        }
                    } else {
                        LoggedSetRow(
                            n, logged.actualWeightLb, logged.actualReps ?: 0,
                            logged.rating ?: 0,
                            sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                            onEdit = if (sessionWritable) ({ onEditSet(n) }) else null,
                        )
                    }
                } else if (timed && n == nextSet && !closed) {
                    TimedSetRow(
                        n = n, holdSeconds = wex.targetRepsLow,
                        exerciseName = name,
                        sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                        onComplete = { elapsed, rating ->
                            // Logs actual seconds held + the user's
                            // rating (5 / 4 / 1). The next session's
                            // generator reads this history and adjusts
                            // the target via adjust_mobility_target().
                            onLogSet(n, null, elapsed, rating, "working")
                            inputs.remove(key)
                        },
                    )
                } else if (timed) {
                    PendingSetRow(n, bilateralSideLabel(n, wex.targetSets, info))
                    // A closed slot falls through to the read-only pending row:
                    // partial work stays visible, but the session is over (or
                    // this slot is settled) so there's nothing to log into.
                } else if (n == nextSet && !closed) {
                    // TD-6 — the prefill comes from the server.
                    //
                    // This screen used to inherit weight and reps from the
                    // most recently logged set of this exercise and
                    // pre-select a rating of 4, while StrengthToday.vue
                    // seeded every set from the flat slot target with no
                    // rating. Same workout, two different starting values,
                    // on the app's most-used surface — and invisible to
                    // parity_check.py, because both files exist and both
                    // kept changing. The cascade now lives in _planned_sets
                    // and both surfaces render its answer.
                    //
                    // The rating is deliberately no longer pre-selected. It
                    // is the input to next session's weight choice, so
                    // defaulting it manufactured progression data from a
                    // user tapping through without thinking. That costs a
                    // tap; it buys honest history.
                    val planned = wex.plannedSets.firstOrNull { it.setNumber == n }
                    val input = inputs.getOrPut(key) { SetInput(
                        weight = (planned?.prefillWeightLb ?: wex.targetWeightLb)
                            ?.toString().orEmpty(),
                        reps = (planned?.prefillReps?.takeIf { it > 0 }
                            ?: wex.targetRepsLow).toString(),
                        rating = planned?.prefillRating,
                        setType = planned?.setType ?: "working",
                    ) }
                    SetEntryRow(
                        n = n, input = input,
                        onWeight = { inputs[key] = input.copy(weight = it) },
                        onReps = { inputs[key] = input.copy(reps = it) },
                        onRating = { inputs[key] = input.copy(rating = it) },
                        onSetType = { inputs[key] = input.copy(setType = it) },
                        canLog = input.rating != null && input.reps.isNotBlank(),
                        onLog = {
                            onLogSet(
                                n,
                                input.weight.toDoubleOrNull(),
                                input.reps.toIntOrNull(),
                                input.rating,
                                input.setType,
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
                                input.setType,
                            )
                            inputs.remove(key)
                        },
                        sideLabel = bilateralSideLabel(n, wex.targetSets, info),
                        targetWeightLb = wex.targetWeightLb,
                        // TD-6 — an AMRAP set says so on the row itself.
                        // PROG-1 carried it only inside the program badge
                        // string, which meant reading a badge and then
                        // remembering which set it referred to.
                        targetReps = if (planned?.isAmrap == true) {
                            "${wex.targetRepsLow}+ (AMRAP)"
                        } else {
                            repsRange(wex.targetRepsLow, wex.targetRepsHigh)
                        },
                        isCurrent = isCurrentExercise,
                    )
                } else {
                    PendingSetRow(
                        n, bilateralSideLabel(n, wex.targetSets, info),
                        targetWeightLb = wex.targetWeightLb,
                        targetReps = repsRange(wex.targetRepsLow, wex.targetRepsHigh),
                    )
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
    // Backend-supplied wex.isTimed is authoritative — derived at
    // serialization time from the catalog row's is_timed flag.
    if (wex.isTimed) return true
    // Catalog info.isTimed is only consulted for mobility (where it
    // distinguishes yoga holds from rep-based mobility like Cat-Cow).
    // Other movement patterns rely on the workout payload's flag.
    if (info?.movementPattern == "mobility" && info.isTimed) return true
    // Legacy heuristic — for pre-flag cached plans that survive an
    // upgrade. Rep-low == rep-high AND ≥ 20 reads as "30s hold".
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
    exerciseName: String = "",
    sideLabel: String? = null,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val pal = LocalStrengthPalette.current
    // Timed-hold accent (violet → Magenta under neon) + side-label color.
    val holdViolet = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA)
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

    // ── Full-screen hold overlay ─────────────────────────────────────
    // While a hold is running, float a room-readable countdown above the
    // whole screen. The endsAt/nowMs tick above still drives it (and still
    // fires Notifier.postHoldDone at zero — dismissal happens because the
    // tick sets endsAt=0L, flipping `running` false and closing the Dialog).
    if (running && remaining != null) {
        // Fraction remaining, 1f → 0f, for the ring behind the number.
        val total = (holdSeconds.coerceAtLeast(1)) * 1000L
        val fraction = ((endsAt - nowMs).coerceAtLeast(0L).toFloat() / total.toFloat())
            .coerceIn(0f, 1f)
        Dialog(
            onDismissRequest = {},
            properties = DialogProperties(
                usePlatformDefaultWidth = false,
                dismissOnBackPress = false,
                dismissOnClickOutside = false,
            ),
        ) {
            Box(
                Modifier.fillMaxSize().background(pal.bg),
                contentAlignment = Alignment.Center,
            ) {
                Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    // Exercise name — modest, top.
                    Spacer(Modifier.height(24.dp))
                    val heading = buildString {
                        if (!exerciseName.isBlank()) append(exerciseName)
                        if (sideLabel != null) {
                            if (isNotEmpty()) append(" · ")
                            append(if (sideLabel == "R") "Right" else if (sideLabel == "L") "Left" else sideLabel)
                        }
                    }.ifBlank { "Hold" }
                    Text(
                        heading,
                        color = pal.muted, fontSize = 20.sp,
                        fontWeight = FontWeight.SemiBold,
                        textAlign = TextAlign.Center,
                        maxLines = 2,
                    )

                    // Giant countdown + progress ring, vertically centered.
                    Box(
                        Modifier.weight(1f).fillMaxWidth(),
                        contentAlignment = Alignment.Center,
                    ) {
                        Canvas(Modifier.size(320.dp)) {
                            val stroke = 14.dp.toPx()
                            val inset = stroke / 2f
                            // Track.
                            drawArc(
                                color = holdViolet.copy(alpha = 0.16f),
                                startAngle = -90f, sweepAngle = 360f, useCenter = false,
                                topLeft = androidx.compose.ui.geometry.Offset(inset, inset),
                                size = androidx.compose.ui.geometry.Size(
                                    size.width - stroke, size.height - stroke),
                                style = Stroke(width = stroke, cap = StrokeCap.Round),
                            )
                            // Remaining progress.
                            drawArc(
                                color = holdViolet,
                                startAngle = -90f, sweepAngle = 360f * fraction,
                                useCenter = false,
                                topLeft = androidx.compose.ui.geometry.Offset(inset, inset),
                                size = androidx.compose.ui.geometry.Size(
                                    size.width - stroke, size.height - stroke),
                                style = Stroke(width = stroke, cap = StrokeCap.Round),
                            )
                        }
                        Text(
                            if (remaining >= 60)
                                "${remaining / 60}:${(remaining % 60).toString().padStart(2, '0')}"
                            else "$remaining",
                            color = pal.ink,
                            fontSize = 140.sp,
                            fontWeight = FontWeight.Bold,
                            fontFamily = NeonNumberFamily,
                            textAlign = TextAlign.Center,
                        )
                    }

                    Text(
                        "of ${holdSeconds}s hold",
                        color = pal.muted, fontSize = 16.sp,
                        textAlign = TextAlign.Center,
                    )
                    Spacer(Modifier.height(28.dp))

                    // Bottom controls: big Fail (rating=1) + Done (capture elapsed).
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                    ) {
                        OutlinedButton(
                            onClick = {
                                val elapsed = ((System.currentTimeMillis() - startedAt) / 1000L)
                                    .coerceAtLeast(1L).toInt()
                                endsAt = 0L
                                onComplete(elapsed, 1)
                            },
                            modifier = Modifier.weight(1f).height(64.dp),
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = pal.bad,
                            ),
                        ) {
                            Text("Fail", fontSize = 20.sp, fontWeight = FontWeight.Bold)
                        }
                        Button(
                            onClick = {
                                // "Done" — end the hold early, capture elapsed,
                                // then fall through to the rating prompt.
                                val elapsed = ((System.currentTimeMillis() - startedAt) / 1000L)
                                    .coerceAtLeast(1L).toInt()
                                pendingElapsed = elapsed
                                endsAt = 0L
                            },
                            modifier = Modifier.weight(1f).height(64.dp),
                            colors = ButtonDefaults.buttonColors(
                                containerColor = holdViolet,
                                contentColor = if (pal.neon) NeonMV.OnAccent else Color.White,
                            ),
                        ) {
                            Text("Done", fontSize = 20.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    TextButton(
                        onClick = { endsAt = 0L },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Cancel", color = pal.muted, fontSize = 14.sp)
                    }
                }
            }
        }
    }

    // Three-state row: rating prompt, running countdown, or idle Start button.
    if (pendingElapsed != null) {
        // Rate the hold (WP-16 labels): 💪 Easy = 5, ✓ Good = 4, ✗ Failed = 1.
        // Logs (elapsed, rating); the SetEntry on next render will be
        // skipped because the parent moves to the next set.
        Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    sideLabel ?: "$n",
                    color = if (sideLabel != null) holdViolet else pal.muted,
                    fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
                    modifier = Modifier.width(20.dp),
                )
                Text(
                    "${pendingElapsed}s held — how was it?",
                    color = pal.ink, fontSize = 13.sp,
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(6.dp))
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.padding(start = 20.dp),
            ) {
                RateButton("Easy", "💪", if (pal.neon) NeonMV.Cyan else Color(0xFF22C55E)) {
                    onComplete(pendingElapsed!!, 5); pendingElapsed = null
                }
                RateButton("Good", "✓", if (pal.neon) NeonMV.Lime else Color(0xFFA78BFA)) {
                    onComplete(pendingElapsed!!, 4); pendingElapsed = null
                }
                RateButton("Failed", "✗", if (pal.neon) NeonMV.Bad else Color(0xFFEF4444)) {
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
            color = if (sideLabel != null) holdViolet else pal.muted,
            fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(20.dp),
        )
        if (remaining != null) {
            Box(
                Modifier
                    .padding(horizontal = 8.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (pal.neon) NeonMV.Magenta.copy(alpha = 0.13f) else Color(0x21A78BFA))
                    .padding(horizontal = 12.dp, vertical = 4.dp),
            ) {
                Text(
                    if (remaining >= 60)
                        "${remaining / 60}:${(remaining % 60).toString().padStart(2, '0')}"
                    else "${remaining}s",
                    color = holdViolet, fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text("of ${holdSeconds}s",
                color = pal.muted, fontSize = 11.sp,
                modifier = Modifier.weight(1f))
            TextButton(onClick = {
                // "Done" — end the hold early but still capture it.
                val elapsed = ((nowMs - startedAt) / 1000L).coerceAtLeast(1L).toInt()
                pendingElapsed = elapsed
                endsAt = 0L
            }) {
                Text("Done", color = holdViolet,
                     fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            }
            TextButton(onClick = { endsAt = 0L }) {
                Text("Cancel", color = pal.muted, fontSize = 12.sp)
            }
        } else {
            Text("${holdSeconds}s hold",
                color = pal.muted, fontSize = 13.sp,
                modifier = Modifier.weight(1f))
            Button(
                onClick = {
                    startedAt = System.currentTimeMillis()
                    endsAt = startedAt + holdSeconds * 1000L
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = holdViolet,
                    contentColor = if (pal.neon) NeonMV.OnAccent else Color.White,
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
                          sideLabel: String? = null,
                          onEdit: (() -> Unit)? = null) {
    val pal = LocalStrengthPalette.current
    val sideColor = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA)
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            sideLabel ?: "$n",
            color = if (sideLabel != null) sideColor else pal.muted,
            fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(20.dp),
        )
        Text(
            "${weightLb ?: "—"}lb × $reps",
            color = pal.ink, fontSize = 14.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(1f),
        )
        Text(ratingLabel(rating), color = ratingColor(rating, pal), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.width(8.dp))
        // OG2-A9: a logged set was permanent from the UI, so a fat-fingered
        // 225 instead of 25 stayed in the log, in the records card, and in
        // the average that picks next session's weight.
        if (onEdit != null) {
            androidx.compose.material3.TextButton(
                onClick = onEdit,
                contentPadding = androidx.compose.foundation.layout.PaddingValues(
                    horizontal = 6.dp, vertical = 0.dp,
                ),
            ) {
                Text("edit", color = pal.muted, fontSize = 11.sp)
            }
        }
        Text("✓", color = pal.good, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun PendingSetRow(
    n: Int, sideLabel: String? = null,
    targetWeightLb: Double? = null, targetReps: String? = null,
) {
    val pal = LocalStrengthPalette.current
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            sideLabel ?: "$n",
            color = pal.dim,
            fontWeight = if (sideLabel != null) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(20.dp),
        )
        // Pending rows show what the planner prescribes (carried from last
        // session's performance) instead of a bare "waiting".
        val tgt = buildString {
            targetWeightLb?.let { append(fmtTargetLb(it)) }
            targetReps?.let { if (isNotEmpty()) append(" × "); append(it) }
        }
        Text(
            if (tgt.isNotBlank()) tgt else "—",
            color = pal.muted, fontSize = 14.sp,
            modifier = Modifier.weight(1f),
        )
        Text("waiting", color = pal.dim, fontSize = 12.sp)
    }
}

/** "6" when low==high, else "6–8" — the prescribed rep window. */
private fun repsRange(low: Int, high: Int): String =
    if (low == high) "$low" else "$low–$high"

@Composable
private fun SetEntryRow(
    n: Int, input: SetInput,
    onWeight: (String) -> Unit, onReps: (String) -> Unit,
    onRating: (Int) -> Unit, canLog: Boolean,
    onSetType: (String) -> Unit = {},
    onLog: () -> Unit, onFailed: () -> Unit,
    sideLabel: String? = null,
    targetWeightLb: Double? = null, targetReps: String? = null,
    isCurrent: Boolean = true,
) {
    val pal = LocalStrengthPalette.current
    val sideColor = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA)
    val onAccent = if (pal.neon) NeonMV.OnAccent else MV.OnSurface
    // Only the genuinely-current set (first unfinished exercise) gets the
    // accent border + faint wash + "NOW" chip. Other exercises still show
    // their entry form — they're loggable out of order — but with a muted
    // border and no chip, so the screen has exactly one "NOW".
    val borderColor = if (isCurrent) pal.accent.copy(alpha = 0.45f)
        else pal.muted.copy(alpha = 0.22f)
    val washColor = if (isCurrent) pal.accent.copy(alpha = 0.06f)
        else androidx.compose.ui.graphics.Color.Transparent
    Column(
        Modifier.fillMaxWidth()
            .padding(vertical = 6.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(washColor)
            .border(1.dp, borderColor, RoundedCornerShape(12.dp))
            .padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (sideLabel != null) "$sideLabel side" else "Set $n",
                color = if (sideLabel != null) sideColor else pal.ink,
                fontWeight = FontWeight.Bold, fontSize = 14.sp,
            )
            Spacer(Modifier.width(8.dp))
            if (isCurrent) {
                Box(
                    Modifier.clip(RoundedCornerShape(6.dp)).background(pal.accent)
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                ) { Text("NOW", color = onAccent, fontSize = 9.sp, fontWeight = FontWeight.Bold) }
            }
            Spacer(Modifier.weight(1f))
            val tgt = buildString {
                targetWeightLb?.let { append(fmtTargetLb(it)) }
                targetReps?.let { if (isNotEmpty()) append(" × "); append(it) }
            }
            if (tgt.isNotBlank()) {
                Text("target $tgt", color = pal.dim, fontSize = 11.sp)
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
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
            Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Good is pre-selected (see SetInput default) so the common case is
            // a single ✓ tap; Hard/Easy/Failed adjust. Failed = rating 1.
            for ((value, label) in listOf(1 to "Fail", 2 to "Hard", 4 to "Good", 5 to "Easy")) {
                val on = input.rating == value
                val color = ratingColor(value, pal)
                Box(
                    Modifier
                        .weight(1f)
                        .height(42.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (on) color else pal.cardLow)
                        .border(1.dp,
                            if (on) color else color.copy(alpha = 0.45f),
                            RoundedCornerShape(8.dp))
                        .clickable { onRating(value) },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(label,
                        color = if (on) onAccent else color,
                        fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        Button(
            onClick = { if (input.rating == 1) onFailed() else onLog() },
            enabled = canLog,
            modifier = Modifier.fillMaxWidth().height(46.dp),
            colors = if (pal.neon) ButtonDefaults.buttonColors(
                containerColor = pal.accent, contentColor = onAccent,
            ) else ButtonDefaults.buttonColors(
                containerColor = MV.BrandRed, contentColor = MV.OnSurface,
            ),
        ) { Text("✓  Log set $n", fontWeight = FontWeight.Bold) }
    }
}

/** Target weight for the per-set ghost — whole numbers drop the decimal. */
private fun fmtTargetLb(w: Double): String =
    (if (w == w.toLong().toDouble()) "${w.toLong()}" else "%.1f".format(w)) + "lb"

@Composable
private fun ReviewBlock(
    review: StrengthReviewBody?,
    loading: Boolean,
    error: String?,
    onLoad: () -> Unit,
) {
    val pal = LocalStrengthPalette.current
    when {
        loading -> Text("Generating review…", color = pal.muted)
        error != null -> Text(error, color = pal.bad, fontSize = 12.sp)
        review == null -> OutlinedButton(
            onClick = onLoad, modifier = Modifier.fillMaxWidth(),
        ) { Text("Get AI workout review") }
        else -> Column {
            Text(
                review.headline,
                color = pal.ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            )
            for (h in review.highlights) {
                Text("• $h", color = pal.muted, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp))
            }
            for (c in review.concerns) {
                Text("⚠ $c", color = pal.caution, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp))
            }
            Spacer(Modifier.height(6.dp))
            Text(
                "Next session: ${review.nextSessionSuggestion}",
                color = pal.ink, fontSize = 12.sp, fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun WeekStrip(
    history: List<app.myvitals.sync.StrengthWorkoutSummary>,
    projectedDates: Set<String>,
    todayStatus: String,
    onDayClick: (dateIso: String) -> Unit = {},
) {
    val pal = LocalStrengthPalette.current
    val today = java.time.LocalDate.now()
    val statusByDate = history.associate { it.date to it.status }

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
                && projectedDates.contains(iso)

            val dotColor = when {
                effectiveStatus == "completed" -> pal.good
                effectiveStatus == "in_progress" -> pal.caution
                effectiveStatus == "paused" -> pal.info
                effectiveStatus == "skipped" -> pal.muted
                effectiveStatus == "planned" -> pal.accent
                projected -> Color.Transparent
                else -> pal.dim
            }

            Column(
                modifier = Modifier
                    .weight(1f)
                    .clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
                    .border(
                        1.dp,
                        if (isToday) pal.accent else pal.outlineV,
                        androidx.compose.foundation.shape.RoundedCornerShape(8.dp),
                    )
                    .background(pal.cardLow)
                    .clickable(enabled = !isToday) { onDayClick(iso) }
                    .padding(vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    if (isToday) "Today" else d.dayOfWeek.name.take(3),
                    color = if (isToday) pal.ink else pal.muted,
                    fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
                )
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .clip(CircleShape)
                        .background(dotColor)
                        .then(
                            if (projected) Modifier.border(
                                1.5.dp, pal.accent, CircleShape,
                            ) else Modifier
                        ),
                )
            }
        }
    }
}

// Set-rating colors. Classic path returns the exact prior values; under
// neon: Failed(1)->Bad, Hard(2)->Amber, Good(3/4)->Lime, Easy(5)->Cyan.
private fun ratingColor(r: Int, pal: StrengthPalette) = when (r) {
    1 -> if (pal.neon) NeonMV.Bad else MV.Red
    2 -> if (pal.neon) NeonMV.Amber else androidx.compose.ui.graphics.Color(0xFFF97316)
    3 -> if (pal.neon) NeonMV.Lime else MV.Amber
    4 -> if (pal.neon) NeonMV.Lime else androidx.compose.ui.graphics.Color(0xFF84CC16)
    5 -> if (pal.neon) NeonMV.Cyan else MV.Green
    else -> if (pal.neon) NeonMV.Muted else MV.OnSurfaceDim
}

// WP-16 — four-button labels; historical 1–5 RPE data still maps cleanly.
private fun ratingLabel(r: Int) = when (r) {
    1 -> "Failed"; 2 -> "Hard"; 3, 4 -> "Good"; 5 -> "Easy"; else -> "RPE $r"
}

@Composable
private fun ExercisePrefMenu(onSetPref: (String) -> Unit) {
    val pal = LocalStrengthPalette.current
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) {
            Icon(
                Icons.Outlined.MoreVert,
                contentDescription = "Exercise preference",
                tint = pal.muted,
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
                        tint = pal.ink,
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
                        tint = pal.ink,
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
                        tint = pal.ink,
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
                        tint = pal.ink,
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

/** Dialog shown when the user taps "Log this workout" on a cardio /
 *  yoga / active-recovery day. Captures a label (e.g. "Les Mills VR",
 *  "Treadmill Z2", "Evening walk") and a duration in minutes. Submits
 *  via /workout/strength/workouts/{id}/complete-cardio which mints a
 *  manual Activity row + marks the strength workout complete. */
@Composable
private fun CardioLogDialog(
    defaultLabel: String,
    defaultDurationMin: Int,
    submitting: Boolean,
    onDismiss: () -> Unit,
    onSubmit: (label: String, type: String, durationMin: Int, endedAt: java.time.Instant) -> Unit,
) {
    val pal = LocalStrengthPalette.current
    // Common cardio presets — (display label, canonical type). The type
    // is stored on the Activity and drives the feed icon + analytics;
    // "Other" keeps it generic and lets the user type a custom name.
    val presets = remember {
        listOf(
            "Les Mills VR" to "les_mills_vr",
            "Other VR" to "vr",
            "Rowing" to "rowing",
            "Cycling" to "cycling",
            "Elliptical" to "elliptical",
            "Walk" to "walk",
            "Other" to "manual_cardio",
        )
    }
    var selected by remember {
        mutableStateOf(presets.firstOrNull { it.first == defaultLabel } ?: presets[0])
    }
    var typeMenuOpen by remember { mutableStateOf(false) }
    var label by remember {
        mutableStateOf(defaultLabel.ifBlank { presets[0].first })
    }
    var durationStr by remember { mutableStateOf(defaultDurationMin.toString()) }
    // Default end-time = right now in local zone. User can tap to pick a
    // different time so the HR sample scan window matches the real
    // workout instead of the moment they happened to log it.
    val initialNow = remember { java.time.LocalDateTime.now() }
    var endedHour by remember { mutableStateOf(initialNow.hour) }
    var endedMinute by remember { mutableStateOf(initialNow.minute) }
    var showTimePicker by remember { mutableStateOf(false) }
    val duration = durationStr.toIntOrNull()
    val canSubmit = label.isNotBlank() && duration != null && duration in 1..1440 && !submitting

    if (showTimePicker) {
        app.myvitals.ui.common.EndedTimePickerDialog(
            initialHour = endedHour,
            initialMinute = endedMinute,
            onConfirm = { h, m ->
                endedHour = h; endedMinute = m; showTimePicker = false
            },
            onDismiss = { showTimePicker = false },
        )
    }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Log this workout") },
        text = {
            Column {
                Text(
                    "What did you do? The session will appear in your " +
                    "activity feed, as a marker on HR charts, and count " +
                    "toward your weekly cardio dose.",
                    color = pal.muted, fontSize = 12.sp,
                    modifier = Modifier.padding(bottom = 12.dp),
                )
                // Type dropdown — autofills the name; "Other" lets the
                // user type a custom one.
                Box {
                    OutlinedButton(
                        onClick = { if (!submitting) typeMenuOpen = true },
                        enabled = !submitting,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Type: ${selected.first}", color = pal.ink)
                    }
                    DropdownMenu(
                        expanded = typeMenuOpen,
                        onDismissRequest = { typeMenuOpen = false },
                    ) {
                        presets.forEach { p ->
                            DropdownMenuItem(
                                text = { Text(p.first) },
                                onClick = {
                                    selected = p
                                    label = if (p.second == "manual_cardio") "" else p.first
                                    typeMenuOpen = false
                                },
                            )
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = label,
                    onValueChange = { label = it.take(120) },
                    label = { Text("Workout name") },
                    placeholder = { Text("e.g. Les Mills VR") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !submitting,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = durationStr,
                    onValueChange = { durationStr = it.take(4).filter(Char::isDigit) },
                    label = { Text("Duration (minutes)") },
                    singleLine = true,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !submitting,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Ended at",
                    color = pal.muted, fontSize = 12.sp,
                )
                Spacer(Modifier.height(2.dp))
                androidx.compose.material3.OutlinedButton(
                    onClick = { if (!submitting) showTimePicker = true },
                    enabled = !submitting,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("%02d:%02d".format(endedHour, endedMinute),
                         color = pal.ink, fontSize = 16.sp)
                }
                Text(
                    "Tap to change if you're logging this later. " +
                    "HR is scanned from this time minus the duration.",
                    color = pal.muted, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(
                enabled = canSubmit,
                onClick = {
                    onSubmit(
                        label.trim(),
                        selected.second,
                        duration ?: defaultDurationMin,
                        app.myvitals.ui.common.composeEndedInstant(
                            endedHour, endedMinute, anchorDate = null,
                        ),
                    )
                },
            ) { Text(if (submitting) "Logging…" else "Log workout", color = pal.good) }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(
                onClick = onDismiss, enabled = !submitting,
            ) { Text("Cancel") }
        },
    )
}

/** Bigger view of an exercise — full-width image + name + muscle
 *  targets + the catalog's how-to instructions. Opens when the user
 *  taps the small 40dp icon in an ExerciseCard. */
@Composable
private fun ExerciseInfoDialog(
    info: StrengthExerciseInfo,
    name: String,
    backendBaseUrl: String,
    onYouTube: () -> Unit,
    onDismiss: () -> Unit,
) {
    val pal = LocalStrengthPalette.current
    val iconViolet = if (pal.neon) NeonMV.Magenta else Color(0xFFA78BFA)
    val iconVioletBg = if (pal.neon) NeonMV.Magenta.copy(alpha = 0.12f) else Color(0x14A78BFA)
    val isPhoto = info.imageFront?.lowercase()?.let {
        it.endsWith(".jpg") || it.endsWith(".jpeg")
    } ?: false
    val isMobilityYoga = info.movementPattern == "mobility" &&
        app.myvitals.ui.hasYogaPoseIcon(info.id)
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(name) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(
                    androidx.compose.foundation.rememberScrollState(),
                ),
            ) {
                // Big-image area — 200dp tall, fills the dialog width.
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(200.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(iconVioletBg),
                    contentAlignment = Alignment.Center,
                ) {
                    when {
                        info.imageFront != null && backendBaseUrl.isNotEmpty() && isPhoto -> {
                            // ANIM-1: crossfade the start/end frames for photos.
                            ExerciseDemo(
                                frontUrl = backendBaseUrl + info.imageFront,
                                backUrl = info.imageSide?.let { backendBaseUrl + it },
                                contentDescription = name,
                                modifier = Modifier.fillMaxSize(),
                            )
                        }
                        info.imageFront != null && backendBaseUrl.isNotEmpty() -> {
                            // Icon (.png) — single tinted frame.
                            AsyncImage(
                                model = backendBaseUrl + info.imageFront,
                                contentDescription = name,
                                modifier = Modifier.size(160.dp),
                                colorFilter = ColorFilter.tint(iconViolet),
                            )
                        }
                        isMobilityYoga -> {
                            app.myvitals.ui.YogaPoseIcon(
                                id = info.id, size = 160.dp,
                                tint = iconViolet,
                            )
                        }
                        else -> {
                            Text("No image", color = pal.muted, fontSize = 13.sp)
                        }
                    }
                }
                Spacer(Modifier.height(12.dp))
                // Muscle targets row — primary + secondary chips.
                Text(
                    "Targets",
                    color = pal.muted, fontSize = 11.sp,
                    fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
                )
                Spacer(Modifier.height(4.dp))
                val targets = buildList {
                    add(info.primaryMuscle.replace('_', ' '))
                    addAll(info.secondaryMuscles.map { it.replace('_', ' ') })
                }
                Text(
                    targets.joinToString(" · "),
                    color = pal.ink, fontSize = 13.sp,
                )
                if (info.equipment.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "Equipment",
                        color = pal.muted, fontSize = 11.sp,
                        fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        info.equipment.joinToString(" · ") { it.replace('_', ' ') },
                        color = pal.ink, fontSize = 13.sp,
                    )
                }
                if (info.instructions.isNotEmpty()) {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "How to",
                        color = pal.muted, fontSize = 11.sp,
                        fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
                    )
                    Spacer(Modifier.height(4.dp))
                    for ((idx, step) in info.instructions.withIndex()) {
                        Row(
                            modifier = Modifier.padding(vertical = 3.dp),
                            verticalAlignment = Alignment.Top,
                        ) {
                            Text(
                                "${idx + 1}.",
                                color = pal.muted,
                                fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.width(22.dp),
                            )
                            Text(
                                step,
                                color = pal.ink, fontSize = 13.sp,
                                lineHeight = 18.sp,
                            )
                        }
                    }
                } else {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "No how-to instructions for this exercise in " +
                        "the catalog. Tap YouTube below for a demo.",
                        color = pal.muted, fontSize = 12.sp,
                    )
                }
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(onClick = {
                onYouTube(); onDismiss()
            }) { Text("YouTube ↗", color = pal.muted) }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) {
                Text("Close")
            }
        },
    )
}


// PDF-1: compose a plain-text summary of a workout for the Android share
// sheet. Mirrors the web print summary (exercise, sets×reps, weight, and
// program/load notes) so both surfaces export the same content.
private fun buildWorkoutShareText(
    w: StrengthWorkoutDetail,
    catalog: Map<String, StrengthExerciseInfo>,
): String {
    fun fmtW(x: Double): String =
        if (x == x.toLong().toDouble()) "${x.toLong()}" else "$x"
    val split = w.splitFocus.replaceFirstChar { it.uppercase() }.replace('_', ' ')
    val sb = StringBuilder()
    sb.append("$split day — ${w.date}\n\n")
    w.exercises.forEachIndexed { i, wex ->
        val name = catalog[wex.exerciseId]?.name ?: wex.exerciseId.replace('_', ' ')
        val rep = if (wex.targetRepsLow == wex.targetRepsHigh) "${wex.targetRepsLow}"
                  else "${wex.targetRepsLow}-${wex.targetRepsHigh}"
        val unit = if (wex.isTimed) "s" else ""
        val wt = wex.targetWeightLb?.let { " @ ${fmtW(it)} lb" } ?: ""
        sb.append("${i + 1}. $name — ${wex.targetSets}×$rep$unit$wt")
        val extra = listOfNotNull(
            // SKIP-1 — a declined slot was prescribed but never performed.
            // Annotated rather than dropped so the export keeps the plan's
            // numbering and still matches what the screen shows.
            if (wex.skipped) "skipped" else null,
            wex.programScheme, wex.loadHint,
        ).joinToString(" · ")
        if (extra.isNotBlank()) sb.append("  ($extra)")
        sb.append("\n")
    }
    if (!w.notes.isNullOrBlank()) sb.append("\n${w.notes}")
    sb.append("\n\n— myvitals")
    return sb.toString()
}
