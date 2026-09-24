package app.myvitals.ui.strength

import android.content.Intent
import app.myvitals.ui.common.userMessage
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
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.OndemandVideo
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.TrendingUp
import androidx.compose.material.icons.outlined.HelpOutline
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.CenterFocusStrong
import androidx.compose.material.icons.outlined.BatteryChargingFull
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
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
import app.myvitals.ui.neon.NeonBackgroundBrush
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonTitle
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Stable
import androidx.compose.runtime.staticCompositionLocalOf
import app.myvitals.update.Notifier
import coil.compose.AsyncImage
import androidx.compose.ui.graphics.ColorFilter
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Palette holder for this screen. The classic shell was retired in
 * v0.7.393, so every value is the neon token now; the holder survives
 * because ~every helper below reads it through [LocalStrengthPalette].
 *
 * UI-2: `cardLow` used to equal `card` under neon, which is why a finished
 * exercise and the one you were working on rendered identically. It is now
 * a surface visibly darker than Card, used for the collapsed rows of
 * finished work.
 */
internal class StrengthPalette(val neon: Boolean = true) {
    val bg = NeonMV.Bg
    val card = NeonMV.Card
    val cardLow = WorkoutDoneSurface
    val cardHigh = NeonMV.CardHigh
    val ink = NeonMV.Ink
    val muted = NeonMV.Muted
    val dim = NeonMV.Muted
    val outlineV = NeonMV.Line

    val accent = NeonMV.Cyan
    val good = NeonMV.Lime
    val caution = NeonMV.Amber
    val bad = NeonMV.Bad
    val rest = NeonMV.Cyan
    val info = NeonMV.Cyan
    val violet = NeonMV.Magenta
}

/** Darker than [NeonMV.Card]: finished work recedes, the live slot does not. */
internal val WorkoutDoneSurface = Color(0xFF12141D)

internal val LocalStrengthPalette = staticCompositionLocalOf { StrengthPalette() }

/**
 * Everything the workout screen renders, hoisted out of the composable so the
 * fetching wrapper ([StrengthTodayScreen]) and the stateless renderer
 * ([StrengthTodayContent]) can be split — the screenshot tests build one of
 * these by hand. Every field used to be a `remember` local of the wrapper;
 * the semantics of each are unchanged.
 */
@Stable
internal class StrengthTodayState {
    var workout by mutableStateOf<StrengthWorkoutDetail?>(null)
    var catalog by mutableStateOf<Map<String, StrengthExerciseInfo>>(emptyMap())
    var recoveryReason by mutableStateOf<String?>(null)
    var history by mutableStateOf<List<app.myvitals.sync.StrengthWorkoutSummary>>(emptyList())
    // OG2-A4: the dates the generator will actually train on, from the server.
    var projectedDates by mutableStateOf<Set<String>>(emptySet())
    var loading by mutableStateOf(true)
    /** Pull-to-refresh only. The spinner used to be bound to `loading`, which
     *  flips on every reload — i.e. after every logged set. */
    var refreshing by mutableStateOf(false)
    var generating by mutableStateOf(false)
    var deferring by mutableStateOf(false)
    var finishing by mutableStateOf(false)
    var swapping by mutableStateOf(false)
    var adding by mutableStateOf(false)
    var customGenerating by mutableStateOf(false)
    var cardioLogging by mutableStateOf(false)
    /** The last reload failed. Failure is not absence: with no cached plan
     *  this renders a banner and NOT "Generate today's plan". */
    var loadError by mutableStateOf<String?>(null)
    /** An action failed (swap, delete, pref…). Dismissable. */
    var error by mutableStateOf<String?>(null)
    // SKIP-1 — the in-flight id disables every Skip/Undo; the refusal lands
    // on the card it names, never in the screen-level slot.
    var skipBusyWexId by mutableStateOf<Long?>(null)
    var skipError by mutableStateOf<Pair<Long, String>?>(null)
    var online by mutableStateOf(true)
    var bufferedSets by mutableIntStateOf(0)
    var flushing by mutableStateOf(false)
    var review by mutableStateOf<StrengthReviewBody?>(null)
    var reviewLoading by mutableStateOf(false)
    var reviewError by mutableStateOf<String?>(null)
    // Per-set transient input, keyed "<wexId>-<setNumber>".
    val setInputs = mutableStateMapOf<String, SetInput>()
    // OG2-A9: the logged set being corrected, "<wexId>-<setNumber>".
    var editingSetKey by mutableStateOf<String?>(null)
    /** UI-2 — an up-next slot the user tapped to log out of order. Falls
     *  back to the NOW slot the moment it closes. */
    var focusWexId by mutableStateOf<Long?>(null)
    val expandedDone = mutableStateMapOf<Long, Boolean>()
    var restEndsAt by mutableLongStateOf(0L)
    var restTotal by mutableLongStateOf(0L)
    var nowMs by mutableLongStateOf(System.currentTimeMillis())
    var swapWexId by mutableStateOf<Long?>(null)
    var addSheetOpen by mutableStateOf(false)
    var addQuery by mutableStateOf("")
    var customSheetOpen by mutableStateOf(false)
    var showCardioLog by mutableStateOf(false)
    var confirmSkipNames by mutableStateOf<List<String>>(emptyList())
    var showCompleteDialog by mutableStateOf(false)
    var completeDialogDismissed by mutableStateOf(false)
    /** Which banner chip's sheet is open: coach|fasting|deload|paused|why. */
    var openSheet by mutableStateOf<String?>(null)

    val restRemainingS: Long get() = ((restEndsAt - nowMs) / 1000).coerceAtLeast(0L)
}

/** The screen's side effects, as lambdas, so [StrengthTodayContent] stays
 *  free of repositories and network. Defaults are no-ops for the tests. */
internal class StrengthTodayActions(
    val onBack: (() -> Unit)? = null,
    val onOpenHistory: () -> Unit = {},
    val onOpenCatalog: () -> Unit = {},
    val onOpenTrainingPrefs: () -> Unit = {},
    val onOpenEquipment: () -> Unit = {},
    val onOpenCoach: () -> Unit = {},
    val onOpenDay: (String) -> Unit = {},
    val onOpenCharts: () -> Unit = {},
    val refresh: () -> Unit = {},
    val regenerate: (force: Boolean) -> Unit = {},
    val fullWeight: () -> Unit = {},
    val discard: () -> Unit = {},
    val deferDay: () -> Unit = {},
    val unskipDay: () -> Unit = {},
    val pause: () -> Unit = {},
    val resume: () -> Unit = {},
    val finish: (closeRemaining: Boolean) -> Unit = {},
    val submitCardio: (String, String, Int, java.time.Instant) -> Unit = { _, _, _, _ -> },
    val logSet: (StrengthWorkoutExerciseRow, Int, Double?, Int?, Int?, String) -> Unit =
        { _, _, _, _, _, _ -> },
    val deleteSet: (Long) -> Unit = {},
    val skipExercise: (StrengthWorkoutExerciseRow, Boolean) -> Unit = { _, _ -> },
    val setPref: (String, String) -> Unit = { _, _ -> },
    val swapTo: (Long, String) -> Unit = { _, _ -> },
    val addExercise: (String) -> Unit = {},
    val customGenerate: (String, Int, String) -> Unit = { _, _, _ -> },
    val syncNow: () -> Unit = {},
    val loadReview: () -> Unit = {},
    val youTube: (String, String) -> Unit = { _, _ -> },
    val share: () -> Unit = {},
)

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
    onBack: (() -> Unit)? = null,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repo = remember(settings) { StrengthRepository(context, settings) }
    val st = remember { StrengthTodayState() }

    val workout = st.workout
    // OG2-A8: hold the screen on for exactly as long as a workout is
    // RUNNING. The effect used to be `DisposableEffect(Unit)` — keyed to the
    // composable, not to the workout — so the flag went up whenever this
    // screen was on top, pinning the display for a rest-day plan.
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
    // Incremented after each regenerate: the coach state re-fetches /latest
    // and we POST a fresh /deload-check in parallel (cached by signals hash —
    // free when nothing actually moved).
    var deloadRefreshKey by remember { mutableStateOf(0) }
    // Coach state keyed by workout id at the SCREEN level so it outlives any
    // CoachCard re-creation (LazyColumn slot churn dropped it once, and the
    // AI looked like it kept changing its mind).
    val coachState = remember(st.workout?.id) { CoachCardState() }

    // Pre-fetch the cached deload judgment. Lived inside CoachCard; it moved
    // here because the Coach chip names the severity while the card itself
    // is closed in its sheet. refreshKey != 0 invalidates after a regenerate.
    LaunchedEffect(deloadRefreshKey, st.workout?.id) {
        if (deloadRefreshKey != 0) {
            coachState.deload = null; coachState.focus = null
            coachState.swaps = null; coachState.explain = null
            coachState.dismissed.clear()
        }
        if (st.workout != null && settings.isConfigured()) {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val resp = withContext(Dispatchers.IO) { api.strengthDeloadLatest() }
                if (resp.isSuccessful) coachState.deload = resp.body()?.judgment
            } catch (e: Exception) { Timber.d(e, "coach deload prefetch") }
        }
    }

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

    val online by app.myvitals.ui.common.rememberOnlineState()
    suspend fun refreshBuffered() {
        st.bufferedSets = runCatching { repo.bufferedCount() }.getOrDefault(0)
    }
    LaunchedEffect(Unit) {
        while (true) {
            delay(5_000)
            refreshBuffered()
        }
    }

    suspend fun reload() {
        st.loading = true
        st.error = null
        st.loadError = null
        // A skip refusal is about the plan we're replacing.
        st.skipError = null
        try {
            val plan = repo.today()
            val rec = if (plan == null) repo.recovery() else null
            st.workout = plan
            st.recoveryReason = rec?.restDayReason
            if (st.catalog.isEmpty()) st.catalog = repo.catalog()
            st.history = repo.listHistory()
            st.projectedDates = repo.upcoming().map { it.date }.toSet()
        } catch (e: Exception) {
            Timber.w(e, "today reload failed")
            st.loadError = e.userMessage("Couldn't reach the server").take(160)
        } finally {
            st.loading = false
            st.refreshing = false
        }
    }

    LaunchedEffect(Unit) { reload(); refreshBuffered() }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { reload() } }

    // Dialog flags are per workout: a fresh plan starts undismissed.
    LaunchedEffect(st.workout?.id) {
        st.showCompleteDialog = false
        st.completeDialogDismissed = false
        st.confirmSkipNames = emptyList()
        st.focusWexId = null
    }
    // Workout-complete dialog: pops the moment the last prescribed set is
    // accounted for (server counters, never re-derived).
    val allSetsDone = (st.workout?.setsTotal ?: 0) > 0 &&
        (st.workout?.setsDone ?: 0) >= (st.workout?.setsTotal ?: 0)
    LaunchedEffect(allSetsDone, st.workout?.status) {
        if (allSetsDone
            && !st.completeDialogDismissed
            && st.workout?.status != "completed"
        ) st.showCompleteDialog = true
    }

    // Auto-flush both buffers (set logs + status patches) when network
    // returns. Sets first so the logged-set list is current before a patch.
    LaunchedEffect(online) {
        st.online = online
        if (online && st.bufferedSets > 0) {
            st.flushing = true
            try {
                repo.flushBufferedSets()
                repo.flushBufferedWorkoutWrites()
                refreshBuffered()
                if (st.bufferedSets == 0) reload()
            } finally { st.flushing = false }
        }
    }
    LaunchedEffect(Unit) {
        while (true) { delay(1000); st.nowMs = System.currentTimeMillis() }
    }
    // Fire haptic + notification at the moment the rest timer reaches 0.
    var lastNotifiedFor by remember { mutableLongStateOf(0L) }
    val restRemaining = st.restRemainingS
    LaunchedEffect(restRemaining, st.restEndsAt) {
        if (st.restEndsAt > 0L && restRemaining <= 0L && st.restEndsAt != lastNotifiedFor) {
            lastNotifiedFor = st.restEndsAt
            Notifier.postRestTimerDone(context, (st.restTotal / 1000).toInt())
        }
    }
    // WP-14 — keep the ongoing "workout paused" notification in sync.
    LaunchedEffect(st.workout?.status, st.workout?.id) {
        val w = st.workout
        if (w != null && w.status == "paused") {
            Notifier.postWorkoutPaused(context, w.id, w.splitFocus)
        } else {
            Notifier.cancelWorkoutPaused(context)
        }
    }

    fun launchCatching(block: suspend () -> Unit) = scope.launch {
        try { block() } catch (e: Exception) { st.error = e.message?.take(160) }
    }

    val actions = StrengthTodayActions(
        onBack = onBack,
        onOpenHistory = onOpenHistory,
        onOpenCatalog = onOpenCatalog,
        onOpenTrainingPrefs = onOpenTrainingPrefs,
        onOpenEquipment = onOpenEquipment,
        onOpenCoach = onOpenCoach,
        onOpenDay = onOpenDay,
        onOpenCharts = onOpenCharts,
        refresh = { scope.launch { st.refreshing = true; reload() } },
        regenerate = { force ->
            scope.launch {
                st.generating = true
                try {
                    st.workout = repo.regenerate(force); reload()
                    bumpDeload()
                } catch (e: Exception) { st.error = e.message?.take(160) }
                finally { st.generating = false }
            }
        },
        fullWeight = {
            launchCatching {
                st.workout = repo.regenerate(force = true, forceFullWeight = true)
                reload()
            }
        },
        discard = {
            scope.launch {
                st.deferring = true
                try { repo.discardWorkout(st.workout!!.id); reload() }
                catch (e: Exception) { st.error = e.message?.take(160) }
                finally { st.deferring = false }
            }
        },
        deferDay = {
            scope.launch {
                st.deferring = true
                try { repo.deferWorkout(st.workout!!.id); reload() }
                catch (e: Exception) { st.error = e.message?.take(160) }
                finally { st.deferring = false }
            }
        },
        unskipDay = {
            scope.launch {
                st.deferring = true
                try { repo.unskipWorkout(st.workout!!.id); reload() }
                catch (e: Exception) { st.error = e.message?.take(160) }
                finally { st.deferring = false }
            }
        },
        pause = { launchCatching { st.workout = repo.pauseWorkout(st.workout!!.id); reload() } },
        resume = { launchCatching { st.workout = repo.resumeWorkout(st.workout!!.id); reload() } },
        finish = { closeRemaining ->
            val id = st.workout?.id
            if (id != null) scope.launch {
                st.finishing = true
                try { st.workout = repo.completeWorkout(id, closeRemaining); reload() }
                catch (e: Exception) { st.error = e.message?.take(160) }
                finally { st.finishing = false }
            }
        },
        submitCardio = { label, type, durationMin, endedAt ->
            scope.launch {
                st.cardioLogging = true
                try {
                    // Anchor the HR window to the picked end time.
                    val startAt = endedAt.minusSeconds(durationMin * 60L)
                    st.workout = repo.completeCardio(
                        workoutId = st.workout!!.id,
                        label = label,
                        durationMinutes = durationMin.toDouble(),
                        startAt = startAt,
                        type = type,
                    )
                    st.showCardioLog = false
                    reload()
                } catch (e: Exception) {
                    Timber.w(e, "completeCardio failed")
                    st.error = "Couldn't log cardio: ${e.message?.take(120)}"
                } finally { st.cardioLogging = false }
            }
        },
        logSet = onLogSet@{ wex, setNum, weight, reps, rating, setType ->
            // WP-14: a paused session doesn't accept new sets.
            if (st.workout?.status == "paused") {
                st.error = "Workout paused — tap Resume to keep logging."
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
                // PR-1b: the KIND is the server's call.
                if (logged?.prKind != null) {
                    val what = when (logged.prKind) {
                        "weight" -> "weight"
                        "e1rm" -> "e1RM"
                        "added_load" -> "added-weight"
                        "hold" -> "hold"
                        "reps" -> "rep"
                        else -> "personal"
                    }
                    Toast.makeText(context, "\uD83C\uDFC6 New $what PR!", Toast.LENGTH_SHORT).show()
                }
                if (logged != null) {
                    // OG2-A9: a correction closes its own editor.
                    if (st.editingSetKey != null) {
                        st.editingSetKey = null
                        st.setInputs.clear()
                    }
                    // OG2-A7: the server decides the rest; 0 means do not rest.
                    val restMs = logged.restAfterS * 1000L
                    if (restMs > 0L) {
                        st.restTotal = restMs
                        st.restEndsAt = System.currentTimeMillis() + st.restTotal
                    }
                }
                reload()
            }
        },
        deleteSet = { setId ->
            scope.launch {
                try {
                    repo.deleteSet(setId)
                    st.editingSetKey = null
                    st.setInputs.clear()
                    reload()
                } catch (e: Exception) {
                    // Online only by design — a queued delete could replay
                    // before the insert it was meant to remove.
                    Timber.w(e, "deleteSet %d failed", setId)
                    st.error = "Couldn't delete that set — needs a connection."
                }
            }
        },
        skipExercise = { wex, skipped ->
            scope.launch {
                st.skipBusyWexId = wex.id
                st.skipError = null
                try {
                    st.workout = repo.skipExercise(wex.id, skipped)
                } catch (e: Exception) {
                    Timber.w(e, "skipExercise %s failed", wex.id)
                    st.skipError = wex.id to (e.message ?: "Skip failed")
                } finally { st.skipBusyWexId = null }
            }
        },
        setPref = { exerciseId, pref ->
            scope.launch {
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    withContext(Dispatchers.IO) {
                        api.setExercisePref(exerciseId, ExercisePrefBody(pref))
                    }
                    Timber.i("exercise pref set: %s = %s", exerciseId, pref)
                    st.error = null
                } catch (e: Exception) {
                    Timber.w(e, "set exercise pref failed")
                    st.error = "Pref save failed: ${e.message?.take(80)}"
                }
            }
        },
        swapTo = { wexId, altId ->
            scope.launch {
                st.swapping = true
                try {
                    repo.swapExercise(wexId, altId)
                    reload()
                    st.swapWexId = null
                } catch (e: Exception) {
                    st.error = e.message?.take(160)
                } finally { st.swapping = false }
            }
        },
        addExercise = { altId ->
            scope.launch {
                st.adding = true
                try {
                    repo.addExercise(st.workout!!.id, altId)
                    reload()
                    st.addSheetOpen = false
                    st.addQuery = ""
                } catch (e: Exception) {
                    // Needs the network: the prescription is server compute.
                    st.error = e.message?.take(160)
                } finally { st.adding = false }
            }
        },
        customGenerate = { type, durationMin, difficulty ->
            scope.launch {
                st.customGenerating = true
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    api.swapStrengthTodayType(
                        app.myvitals.sync.SwapTodayTypeRequest(
                            type = type,
                            durationMinutes = durationMin,
                            difficulty = difficulty,
                            // The user explicitly chose to stack a session.
                            replaceCompleted = true,
                        ),
                    )
                    st.customSheetOpen = false
                    reload()
                } catch (e: Exception) {
                    Timber.w(e, "custom workout generate failed")
                    st.error = e.message?.take(160)
                } finally { st.customGenerating = false }
            }
        },
        syncNow = {
            scope.launch {
                st.flushing = true
                try {
                    repo.flushBufferedSets()
                    repo.flushBufferedWorkoutWrites()
                    refreshBuffered()
                    if (st.bufferedSets == 0) reload()
                } finally { st.flushing = false }
            }
        },
        loadReview = {
            val id = st.workout?.id
            if (id != null) scope.launch {
                st.reviewLoading = true
                st.reviewError = null
                try { st.review = repo.aiReview(id).review }
                catch (e: Exception) { st.reviewError = e.userMessage().take(160) }
                finally { st.reviewLoading = false }
            }
        },
        youTube = { slug, name -> openYouTube(context, slug, name) },
        share = {
            st.workout?.takeIf { it.exercises.isNotEmpty() }?.let { w ->
                // PDF-1: the phone analog of web's "Print / Save PDF".
                val text = buildWorkoutShareText(w, st.catalog)
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_SUBJECT,
                        "${w.splitFocus.replaceFirstChar { it.uppercase() }.replace('_', ' ')} day — ${w.date}")
                    putExtra(Intent.EXTRA_TEXT, text)
                }
                context.startActivity(Intent.createChooser(send, "Share workout"))
            }
        },
    )

    StrengthTodayContent(
        st = st,
        coach = coachState,
        actions = actions,
        backendBaseUrl = settings.backendUrl.trimEnd('/'),
        coachSheetBody = {
            val plan = st.workout
            if (plan != null) CoachCard(
                settings = settings,
                workoutId = plan.id,
                state = coachState,
                onAcceptSwap = { targetExId, replacementExId ->
                    val wex2 = plan.exercises.firstOrNull { it.exerciseId == targetExId }
                    if (wex2 != null) {
                        // Feedback right away, so the section stays open
                        // visually while the swap + reload run.
                        Toast.makeText(
                            context,
                            "Swap applied: " + replacementExId.replace('_', ' '),
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
                                st.error = "Swap failed: ${e.message?.take(80)}"
                            }
                        }
                    }
                },
            )
        },
    )
}

/**
 * Float incomplete exercises to the top. Within a superset PAIR alternate by
 * accounted-set count (v0.7.161); non-superset exercises keep their natural
 * order so the user finishes all sets of A before B. Done ones drop to the
 * bottom. Once the session is over nothing floats.
 */
internal fun orderExercises(
    plan: StrengthWorkoutDetail, sessionOver: Boolean,
): List<StrengthWorkoutExerciseRow> {
    if (sessionOver) return plan.exercises.sortedBy { it.orderIndex }
    // The bucket is decided by SETS alone — the slot-level skip flag is not
    // consulted, so tapping Skip can never move a card mid-session.
    fun setsComplete(w: StrengthWorkoutExerciseRow): Boolean =
        w.sets.count { it.actualReps != null || it.skipped } >= w.targetSets
    val incomplete = plan.exercises.filter { !setsComplete(it) }
    val complete = plan.exercises.filter { setsComplete(it) }.sortedBy { it.orderIndex }
    val groupedIncomplete = incomplete
        .groupBy { it.supersetId }
        .map { (ssId, exs) ->
            if (ssId == null) exs.sortedBy { it.orderIndex }
            // A declined partner counts as fully accounted, so it never wins
            // the alternation with its zero logged sets.
            else exs.sortedWith(compareBy({ accountedSets(it) }, { it.orderIndex }))
        }
        .sortedBy { it.first().orderIndex }
        .flatten()
    return groupedIncomplete + complete
}

/** First unlogged set number of a slot, or null when every set is accounted. */
internal fun nextSetOf(wex: StrengthWorkoutExerciseRow): Int? =
    (1..wex.targetSets).firstOrNull { n ->
        wex.sets.none { it.setNumber == n && (it.actualReps != null || it.skipped) }
    }

/** The seed for a set's entry, from the server's planned_sets prefill (TD-6).
 *  The rating is deliberately never pre-selected. */
internal fun seedInput(wex: StrengthWorkoutExerciseRow, n: Int): SetInput {
    val planned = wex.plannedSets.firstOrNull { it.setNumber == n }
    return SetInput(
        weight = (planned?.prefillWeightLb ?: wex.targetWeightLb)?.let { fmtLbPlain(it) }.orEmpty(),
        reps = (planned?.prefillReps?.takeIf { it > 0 } ?: wex.targetRepsLow).toString(),
        rating = planned?.prefillRating,
        setType = planned?.setType ?: "working",
    )
}

/** "47.5", "45" — no trailing ".0". */
internal fun fmtLbPlain(w: Double): String =
    if (w == w.toLong().toDouble()) "${w.toLong()}" else "%.1f".format(w)

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
internal fun StrengthTodayContent(
    st: StrengthTodayState,
    coach: CoachCardState,
    actions: StrengthTodayActions,
    backendBaseUrl: String = "",
    coachSheetBody: @Composable () -> Unit = {},
    /** Injected so a screenshot is the same image on any day. */
    today: java.time.LocalDate = java.time.LocalDate.now(),
) {
    val pal = remember { StrengthPalette() }
    val plan = st.workout
    val catalog = st.catalog

    // SKIP-1 — the slots the server would close as skipped if we finished
    // right now. Mirrors _close_remaining_exercises so the dialog names
    // exactly what the flag will touch. Catalog names, never raw slugs.
    val unloggedNames: List<String> = plan?.exercises.orEmpty()
        .filter { ex -> !ex.skipped && ex.sets.none { it.actualReps != null } }
        .map { catalog[it.exerciseId]?.name ?: it.exerciseId.replace('_', ' ') }
    /** Single entry point for every interactive "Finish workout" tap. */
    fun requestFinish() {
        if (unloggedNames.isEmpty()) actions.finish(false)
        else st.confirmSkipNames = unloggedNames
    }

    CompositionLocalProvider(LocalStrengthPalette provides pal) {
    Box(Modifier.fillMaxSize().background(NeonBackgroundBrush)) {
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        NeonTitle(
            // "{Split} day" — the same title StrengthToday.vue shows.
            title = plan?.splitFocus?.replace('_', ' ')?.replaceFirstChar(Char::titlecase)
                ?.let { "$it day" } ?: "Workout",
            onBack = actions.onBack,
            trailing = {
                WorkoutOverflowMenu(
                    plan = plan,
                    generating = st.generating,
                    onRegenerate = { actions.regenerate(true) },
                    actions = actions,
                    onCustom = { st.customSheetOpen = true },
                )
            },
        )

        // ONE progress read-out: a segment per exercise, the server counters
        // beside it. Replaces the header pip + second bar that said the same
        // "4/12 sets" twice.
        if (plan != null && plan.exercises.isNotEmpty()) {
            SegmentedProgress(plan)
            Spacer(Modifier.height(10.dp))
        }

        // Offline + buffered-sync banner.
        if (!st.online || st.bufferedSets > 0) {
            OfflineBanner(
                online = st.online,
                pending = st.bufferedSets,
                flushing = st.flushing,
                onSyncNow = actions.syncNow,
            )
        }
        st.loadError?.let {
            NeonErrorBanner(
                message = it, onRetry = actions.refresh,
                title = "Couldn't load today's workout", accent = NeonMV.Amber,
            )
        }
        st.error?.let {
            NeonErrorBanner(
                message = it, onRetry = { st.error = null },
                title = "That didn't go through", accent = NeonMV.Amber,
                actionLabel = "Dismiss",
            )
        }

        if (plan == null) {
            when {
                st.loading -> WorkoutHeroSkeleton()
                // Failure is not absence: the banner above says what went
                // wrong, and offering to generate a plan here would read as
                // "you have no workout today".
                st.loadError != null -> {}
                else -> NoPlanHero(
                    recoveryReason = st.recoveryReason,
                    online = st.online,
                    generating = st.generating,
                    onGenerate = { force -> actions.regenerate(force) },
                )
            }
            return@Column
        }

        val sessionOver = plan.status == "completed" || plan.status == "skipped"
        val orderedExercises = remember(plan.exercises, sessionOver) { orderExercises(plan, sessionOver) }
        // The single set that's genuinely NOW: the next set of the first
        // not-yet-closed exercise in render order — or an up-next slot the
        // user tapped, until it closes.
        val currentId = orderedExercises.firstOrNull { !isSlotClosed(it, plan.status) }?.id
        val heroWex = plan.exercises.firstOrNull {
            it.id == st.focusWexId && !isSlotClosed(it, plan.status)
        } ?: plan.exercises.firstOrNull { it.id == currentId }

        // Pinned: the hero never scrolls away. Everything below it does.
        NowHeroArea(
            st = st,
            plan = plan,
            heroWex = heroWex,
            info = heroWex?.let { catalog[it.exerciseId] },
            actions = actions,
            onFinish = { requestFinish() },
            onCardioLog = { st.showCardioLog = true },
        )

        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = st.refreshing,
            onRefresh = actions.refresh,
            modifier = Modifier.weight(1f),
        ) {
        LazyColumn(
            contentPadding = PaddingValues(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // Coach / fasting / deload / paused / why — one strip of chips,
            // each opening its unchanged content in a sheet.
            item(key = "chips") {
                BannerChipStrip(plan = plan, coach = coach, onOpen = { st.openSheet = it })
            }
            items(orderedExercises, key = { it.id }) { wex ->
                ExerciseSlot(
                    st = st,
                    plan = plan,
                    wex = wex,
                    info = catalog[wex.exerciseId],
                    isHero = wex.id == heroWex?.id,
                    sessionOver = sessionOver,
                    actions = actions,
                    backendBaseUrl = backendBaseUrl,
                )
            }
            // TD-10 — add an off-plan exercise, only while the session is open.
            if (!sessionOver) {
                item(key = "add") {
                    TextButton(
                        onClick = { st.addSheetOpen = true },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                    ) {
                        Icon(Icons.Filled.Add, null, tint = pal.accent,
                            modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Add exercise", color = pal.accent, fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            // Finishing early (walking away) is the flagship SKIP-1 flow, so a
            // Finish action is always one scroll away, not only in the hero.
            if (!sessionOver && plan.exercises.isNotEmpty()) {
                item(key = "session-actions") {
                    SessionActions(
                        plan = plan,
                        finishing = st.finishing,
                        onFinish = { requestFinish() },
                        onPause = actions.pause,
                        onResume = actions.resume,
                    )
                }
            }
            item(key = "week") {
                app.myvitals.ui.neon.NeonEyebrow("This week")
                WeekStrip(
                    history = st.history,
                    projectedDates = st.projectedDates,
                    todayStatus = plan.status,
                    today = today,
                    onDayClick = { dateIso -> actions.onOpenDay(dateIso) },
                )
            }
            // OG2-C2: the silhouette projected through today's plan. Below
            // the session, matching the web page.
            plan.projectedMuscleVolume.takeIf { it.isNotEmpty() }?.let { pv ->
                item(key = "bodymap") {
                    app.myvitals.ui.neon.NeonEyebrow(
                        if (plan.status == "completed") "This week, including today"
                        else "This week, after today",
                    )
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Box(Modifier.widthIn(max = 360.dp)) {
                            BodyMapCard(
                                muscles = pv.mapValues { (_, r) ->
                                    r.copy(
                                        sets = (r.setsProjected ?: r.sets.toDouble()).toInt(),
                                        status = r.statusProjected ?: r.status,
                                    )
                                },
                                neon = true,
                            )
                        }
                    }
                }
            }
            if (plan.status == "completed") {
                item(key = "review") {
                    Column(
                        Modifier.fillMaxWidth()
                            .clip(NeonCardShape)
                            .background(pal.card)
                            .border(1.dp, pal.outlineV, NeonCardShape)
                            .padding(16.dp),
                    ) {
                        Text("AI review", color = pal.ink, fontSize = 15.sp,
                            fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(8.dp))
                        ReviewBlock(
                            review = st.review,
                            loading = st.reviewLoading,
                            error = st.reviewError,
                            onLoad = actions.loadReview,
                        )
                    }
                }
            }
        }
        }  // end PullToRefreshBox
    }
    }

    WorkoutDialogsAndSheets(
        st = st,
        actions = actions,
        coachSheetBody = coachSheetBody,
        coach = coach,
        onFinishRequested = { requestFinish() },
    )
    }  // end CompositionLocalProvider
}

@Composable
private fun WorkoutOverflowMenu(
    plan: StrengthWorkoutDetail?,
    generating: Boolean,
    onRegenerate: () -> Unit,
    actions: StrengthTodayActions,
    onCustom: () -> Unit,
) {
    val pal = LocalStrengthPalette.current
    var open by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        if (plan?.status == "planned") {
            // Visible regenerate — mirrors the web header's "Regenerate".
            IconButton(onClick = onRegenerate, enabled = !generating) {
                Icon(Icons.Filled.Refresh, contentDescription = "Regenerate with latest signals",
                    tint = pal.muted)
            }
        }
        Box {
            IconButton(onClick = { open = true }) {
                Icon(Icons.Outlined.MoreVert, contentDescription = "More", tint = pal.ink)
            }
            DropdownMenu(
                expanded = open,
                onDismissRequest = { open = false },
                containerColor = NeonMV.CardHigh,
            ) {
                @Composable
                fun item(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector,
                         color: Color = pal.ink, onClick: () -> Unit) {
                    DropdownMenuItem(
                        text = { Text(label, color = color) },
                        leadingIcon = { Icon(icon, null, tint = color, modifier = Modifier.size(18.dp)) },
                        onClick = { open = false; onClick() },
                    )
                }
                item("Catalog", Icons.Filled.MenuBook) { actions.onOpenCatalog() }
                item("Charts", Icons.Filled.QueryStats) { actions.onOpenCharts() }
                item("History", Icons.Filled.History) { actions.onOpenHistory() }
                item("Training prefs", Icons.Filled.Tune) { actions.onOpenTrainingPrefs() }
                item("Equipment", Icons.Filled.FitnessCenter) { actions.onOpenEquipment() }
                item("Coach", Icons.Filled.Psychology) { actions.onOpenCoach() }
                item("Custom workout", Icons.Filled.AddCircle) { onCustom() }
                if (plan != null && plan.exercises.isNotEmpty()) {
                    item("Share workout", Icons.Filled.Share) { actions.share() }
                }
                if (plan?.status == "planned") {
                    item("Regenerate plan", Icons.Filled.Refresh) { onRegenerate() }
                }
                if (plan?.status == "planned" || plan?.status == "in_progress") {
                    // Discard — only while nothing is logged. Falls through to
                    // whatever was previously today's plan.
                    val anyLogged = plan.exercises.any { ex -> ex.sets.any { it.actualReps != null } }
                    if (!anyLogged) item("Discard workout", Icons.Outlined.Close) { actions.discard() }
                    item("Skip workout day", Icons.Filled.SkipNext, color = NeonMV.Amber) {
                        actions.deferDay()
                    }
                }
            }
        }
    }
}


@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
internal fun CustomWorkoutSheet(
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
        containerColor = pal.cardHigh,
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

/** OG3-C2 — tell the server a suggested swap was turned down.
 *
 *  Dismissal used to live only in Compose state, and `POST
 *  /ai/strength/nudge/{id}` caches by payload hash with no `force`
 *  parameter — so "Get fresh suggestions" after a decline returned exactly
 *  the swaps just dismissed, which reads as the coach not having listened.
 *
 *  Fire-and-forget on purpose. The row disappears on tap regardless; if this
 *  call fails the only consequence is the behaviour we already had, and
 *  blocking the UI on it would trade a real responsiveness cost for a
 *  best-effort improvement. The endpoint is idempotent, so a retry that
 *  arrives twice is harmless.
 */
private fun declineNudge(
    scope: kotlinx.coroutines.CoroutineScope,
    settings: SettingsRepository,
    workoutId: Long,
    targetExerciseId: String,
    replacementExerciseId: String,
) {
    if (!settings.isConfigured()) return
    scope.launch {
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                api.declineStrengthNudge(
                    workoutId,
                    app.myvitals.sync.NudgeDeclineBody(
                        targetExerciseId, replacementExerciseId,
                    ),
                )
            }
        } catch (e: Exception) {
            Timber.w(e, "nudge decline not recorded")
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
                                    Text(s.targetDisplay()
                                            .replaceFirstChar(Char::titlecase),
                                        color = pal.ink, fontSize = 12.sp,
                                        fontWeight = FontWeight.SemiBold)
                                    Text(" → ", color = pal.muted, fontSize = 12.sp)
                                    Text(s.replacementDisplay()
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
                                        onClick = {
                                            dismissed[s.targetExerciseId] = true
                                            declineNudge(
                                                scope, settings, workoutId,
                                                s.targetExerciseId,
                                                s.replacementExerciseId,
                                            )
                                        },
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
        "rest" -> NeonMV.Amber
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
    // UI-2: the /latest prefetch and the refreshKey reset moved to
    // StrengthTodayScreen, which owns `state` — the Coach chip names the
    // deload severity while this card sits closed in its sheet.

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
        "rest" -> NeonMV.Amber
        "moderate" -> if (pal.neon) NeonMV.Amber else Color(0xFFF97316)
        "light" -> if (pal.neon) NeonMV.Amber else Color(0xFFFACC15)
        else -> null
    }

    // UI-2: rendered inside the Coach chip's sheet, so it is always open;
    // the collapse header (and cardOpen) went with the card chrome.
    run {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            // Deload
            CoachRow(
                icon = Icons.Outlined.BatteryChargingFull,
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
                icon = Icons.Outlined.CenterFocusStrong,
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
                icon = Icons.Outlined.AutoAwesome,
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
                                Text(s.targetDisplay()
                                        .replaceFirstChar(Char::titlecase),
                                    color = pal.ink, fontSize = 11.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(" → ", color = pal.muted, fontSize = 11.sp)
                                Text(s.replacementDisplay()
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
                                    onClick = {
                                        state.dismissed[s.targetExerciseId] = true
                                        declineNudge(
                                            scope, settings, workoutId,
                                            s.targetExerciseId,
                                            s.replacementExerciseId,
                                        )
                                    },
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
                icon = Icons.Outlined.HelpOutline,
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
    icon: androidx.compose.ui.graphics.vector.ImageVector,
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
            modifier = Modifier.fillMaxWidth().heightIn(min = 44.dp).clickable { onToggle() },
        ) {
            Icon(icon, contentDescription = null, tint = accent ?: pal.muted,
                modifier = Modifier.padding(end = 8.dp).size(18.dp))
            Text(title, color = pal.ink, fontSize = 14.sp,
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

internal data class SetInput(
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
internal fun SlotStrip(
    label: String,
    state: String,
    error: String? = null,
    trailing: @Composable () -> Unit = {},
) {
    val pal = LocalStrengthPalette.current
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(pal.cardLow)
            .border(1.dp, pal.outlineV, shape),
    ) {
        Row(
            modifier = Modifier
                .heightIn(min = 56.dp)
                .padding(start = 14.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                color = pal.muted, fontSize = 15.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Text(state, color = pal.muted, fontSize = 12.sp,
                modifier = Modifier.padding(end = 10.dp))
            trailing()
        }
        error?.let {
            Text(
                it, color = pal.caution, fontSize = 12.sp,
                modifier = Modifier.padding(start = 14.dp, end = 14.dp, bottom = 8.dp),
            )
        }
    }
}

/**
 * The full card for one slot: header, actions, and the set grid. Rendered for
 * the hero's slot, and for a finished slot the user expanded. Entry for the
 * NEXT set lives in the hero now; this card marks that row and offers the
 * OG2-A9 correction on logged ones.
 */
@Composable
internal fun ExerciseCard(
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    inputs: androidx.compose.runtime.snapshots.SnapshotStateMap<String, SetInput>,
    canSwap: Boolean,
    canSkip: Boolean = false,
    // SKIP-1 — see isSlotClosed. Suppresses every writable affordance.
    closed: Boolean = false,
    skipBusy: Boolean = false,
    skipLocked: Boolean = false,
    skipError: String? = null,
    /** The set the hero is logging, outlined in the grid; null elsewhere. */
    heroSetNum: Int? = null,
    onLogSet: (setNum: Int, weight: Double?, reps: Int?, rating: Int?, setType: String) -> Unit,
    onYouTube: (slug: String, name: String) -> Unit,
    onSwap: () -> Unit,
    onSkipChange: (Boolean) -> Unit = {},
    onSetPref: (String) -> Unit = {},
    // OG2-A9: whether the SESSION accepts writes. Deliberately not `closed`,
    // which is also true for a slot whose sets are all logged — that is
    // exactly when a typo is noticed.
    sessionWritable: Boolean = true,
    editingSetNum: Int? = null,
    onEditSet: (Int) -> Unit = {},
    onDeleteSet: (setId: Long) -> Unit = {},
    partnerName: String? = null,
    backendBaseUrl: String = "",
) {
    val pal = LocalStrengthPalette.current
    val iconViolet = NeonMV.Magenta
    val iconVioletBg = NeonMV.Magenta.copy(alpha = 0.12f)
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    val supersetColor = wex.supersetId?.let {
        // Stable hash → hue (HSL)
        val h = it.fold(0) { acc, c -> (acc * 31 + c.code) % 360 }
        Color(android.graphics.Color.HSVToColor(floatArrayOf(h.toFloat(), 0.55f, 0.85f)))
    }
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
    val border = when {
        supersetColor != null -> supersetColor.copy(alpha = 0.5f)
        heroSetNum != null -> NeonMV.Cyan.copy(alpha = 0.30f)
        else -> pal.outlineV
    }
    Column(
        Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(pal.card)
            .border(if (supersetColor != null) 2.dp else 1.dp, border, NeonCardShape)
            .padding(16.dp),
    ) {
        if (wex.supersetId != null && partnerName != null) {
            Text(
                "Superset ${wex.supersetId} — alternate with $partnerName",
                color = supersetColor ?: pal.muted,
                fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(bottom = 4.dp),
            )
        }
        Row(verticalAlignment = Alignment.Top) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "${wex.orderIndex + 1}. $name",
                    color = pal.ink, fontSize = 17.sp, fontWeight = FontWeight.Bold,
                )
                // TD-10: keep the plan and its improvisations distinguishable.
                if (wex.addedAdHoc) {
                    Text("ADDED BY YOU", color = pal.accent, fontSize = 10.sp,
                        fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp)
                }
                // OG2-A6: flagged, never removed.
                if (wex.equipmentMissing) {
                    Text("NEEDS KIT YOU NO LONGER HAVE", color = pal.caution, fontSize = 10.sp,
                        fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp)
                }
                val rep = if (wex.targetRepsLow == wex.targetRepsHigh)
                    "${wex.targetRepsLow}" else "${wex.targetRepsLow}-${wex.targetRepsHigh}"
                val w = wex.targetWeightLb?.let { " @ ${fmtLbPlain(it)} lb" } ?: ""
                // OG3-B3: the per-side words are the server's.
                val side = wex.plannedSets.firstOrNull { it.perSide }
                    ?.sideLabel?.let { " $it" } ?: ""
                val unit = if (isTimedExercise(wex, info)) "s" else ""
                Text(
                    "${wex.targetSets}×$rep$unit$side$w  ·  ${wex.targetRestS}s rest",
                    color = pal.muted, fontSize = 13.sp,
                )
                // PROG-1: program-mode scheme badge on program lifts
                wex.programScheme?.let {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Outlined.TrendingUp, null, tint = pal.accent,
                            modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(4.dp))
                        Text(it, color = pal.accent, fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold)
                    }
                }
                // OG2-B3: why this weight, in the server's words.
                wex.notes?.takeIf { it.isNotBlank() }?.let {
                    Text(it, color = pal.muted, fontSize = 12.sp, lineHeight = 16.sp)
                }
                // LOAD-1: how to load it (only when micro-loaders needed)
                wex.loadHint?.let {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.FitnessCenter, null, tint = pal.muted,
                            modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(4.dp))
                        Text(it, color = pal.muted, fontSize = 12.sp)
                    }
                }
                // LOG-1: what you did last time (rep-based exercises only)
                if (!isTimedExercise(wex, info) && wex.lastSets.isNotEmpty()) {
                    val summary = wex.lastSets.joinToString(" · ") { ls ->
                        val wv = ls.weightLb?.let { fmtLbPlain(it) }
                        if (wv != null) "$wv×${ls.reps}" else "${ls.reps}"
                    }
                    // OG3-A3 — when, and the WORST rating of that session.
                    val when_ = lastSetsWhen(wex.lastSets)
                    val head = if (when_ != null) "Last ($when_)" else "Last"
                    Text("$head: $summary", color = pal.muted, fontSize = 12.sp)
                }
            }
            val thumb: (@Composable () -> Unit)? = when {
                info?.imageFront != null && backendBaseUrl.isNotEmpty() -> {
                    {
                        // Photo (.jpg) as-is; icon (.png) tinted so the
                        // black-on-transparent silhouette is legible.
                        val isPhoto = info.imageFront!!
                            .lowercase().let { it.endsWith(".jpg") || it.endsWith(".jpeg") }
                        AsyncImage(
                            model = backendBaseUrl + info.imageFront,
                            contentDescription = name,
                            modifier = if (isPhoto) Modifier.size(48.dp) else Modifier.size(38.dp),
                            colorFilter = if (isPhoto) null else ColorFilter.tint(iconViolet),
                        )
                    }
                }
                info?.movementPattern == "mobility" &&
                    app.myvitals.ui.hasYogaPoseIcon(wex.exerciseId) -> {
                    { app.myvitals.ui.YogaPoseIcon(id = wex.exerciseId, size = 34.dp, tint = iconViolet) }
                }
                else -> null
            }
            if (thumb != null) {
                Box(
                    Modifier
                        .size(48.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(iconVioletBg)
                        .clickable { showInfo = true },
                    contentAlignment = Alignment.Center,
                ) { thumb() }
            }
        }

        // Actions — Ink labels on 40dp targets (they were 12sp Muted, grey
        // on grey, and read as disabled).
        Spacer(Modifier.height(8.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            CardAction("Demo", Icons.Outlined.OndemandVideo) { onYouTube(wex.exerciseId, name) }
            if (canSwap) CardAction("Swap", Icons.Filled.SwapHoriz, onClick = onSwap)
            if (canSkip) {
                // Disabled while the PATCH is in flight.
                CardAction(if (skipBusy) "Skipping…" else "Skip", Icons.Filled.SkipNext,
                    enabled = !skipLocked) { onSkipChange(true) }
            }
            Spacer(Modifier.weight(1f))
            ExercisePrefMenu(onSetPref)
        }
        // A skip refusal (409 "N set(s) already logged") belongs here, verbatim.
        skipError?.let { Text(it, color = pal.caution, fontSize = 12.sp) }

        Spacer(Modifier.height(10.dp))
        SetGrid(
            wex = wex, info = info, inputs = inputs,
            closed = closed, heroSetNum = heroSetNum,
            sessionWritable = sessionWritable,
            editingSetNum = editingSetNum,
            onEditSet = onEditSet, onDeleteSet = onDeleteSet, onLogSet = onLogSet,
        )
    }
}

@Composable
private fun CardAction(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val pal = LocalStrengthPalette.current
    Row(
        Modifier
            .heightIn(min = 40.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(pal.cardHigh)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = if (enabled) pal.ink else pal.muted, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(label, color = if (enabled) pal.ink else pal.muted, fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold)
    }
}

private val GridSetW = 44.dp
private val GridLastW = 96.dp

/**
 * SET | LB | REPS | ✓ — a real grid. Logged rows tinted Lime, the hero's row
 * outlined Cyan, pending rows a muted ghost of the prescription. A logged row
 * being corrected (OG2-A9) turns back into the entry form in place.
 */
@Composable
private fun SetGrid(
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    inputs: androidx.compose.runtime.snapshots.SnapshotStateMap<String, SetInput>,
    closed: Boolean,
    heroSetNum: Int?,
    sessionWritable: Boolean,
    editingSetNum: Int?,
    onEditSet: (Int) -> Unit,
    onDeleteSet: (Long) -> Unit,
    onLogSet: (Int, Double?, Int?, Int?, String) -> Unit,
) {
    val pal = LocalStrengthPalette.current
    val timed = isTimedExercise(wex, info)
    Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically) {
        GridHead("SET", Modifier.width(GridSetW))
        GridHead(if (timed) "—" else "LB", Modifier.weight(1f))
        GridHead(if (timed) "HOLD" else "REPS", Modifier.weight(1f))
        Box(Modifier.width(GridLastW), contentAlignment = Alignment.CenterEnd) {
            Icon(Icons.Outlined.Check, contentDescription = "Status", tint = pal.muted,
                modifier = Modifier.padding(end = 12.dp).size(14.dp))
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (n in 1..wex.targetSets) {
            val key = "${wex.id}-$n"
            val side = bilateralSideLabel(n, wex.targetSets, info)
            val setLabel = side ?: "$n"
            val logged = wex.sets.firstOrNull { it.setNumber == n && it.actualReps != null }
            val skippedSet = wex.sets.firstOrNull { it.setNumber == n && it.skipped && it.actualReps == null }
            val planned = wex.plannedSets.firstOrNull { it.setNumber == n }
            if (logged != null && editingSetNum == n && sessionWritable && !timed) {
                // OG2-A9: the same entry form, seeded from the truth. The
                // set's real classification comes from planned_sets, so a
                // warm-up correction cannot silently become a working set.
                val input = inputs[key] ?: SetInput(
                    weight = logged.actualWeightLb?.let { fmtLbPlain(it) } ?: "",
                    reps = (logged.actualReps ?: 0).toString(),
                    rating = logged.rating,
                    setType = planned?.setType ?: "working",
                )
                SetEntryRow(
                    n = n, input = input,
                    onWeight = { inputs[key] = input.copy(weight = it) },
                    onReps = { inputs[key] = input.copy(reps = it) },
                    onRating = { inputs[key] = input.copy(rating = it) },
                    onSetType = { inputs[key] = input.copy(setType = it) },
                    canLog = input.rating != null,
                    onLog = {
                        onLogSet(n, input.weight.toDoubleOrNull(), input.reps.toIntOrNull(),
                            input.rating, input.setType)
                    },
                    // Log it as failed — NOT delete. Delete is its own control.
                    onFailed = {
                        onLogSet(n, input.weight.toDoubleOrNull(), input.reps.toIntOrNull(),
                            1, input.setType)
                    },
                    sideLabel = side,
                    isCurrent = false,
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = { onEditSet(-1) }, modifier = Modifier.heightIn(min = 40.dp)) {
                        Text("Cancel", color = pal.muted, fontSize = 13.sp)
                    }
                    // Destroys logged work with no undo, so it is said in words.
                    TextButton(onClick = { onDeleteSet(logged.id) }, modifier = Modifier.heightIn(min = 40.dp)) {
                        Text("Delete set", color = pal.caution, fontSize = 13.sp)
                    }
                }
                continue
            }
            val state = when {
                logged != null -> GridRowState.Logged
                skippedSet != null -> GridRowState.Skipped
                n == heroSetNum && !closed -> GridRowState.Current
                else -> GridRowState.Pending
            }
            val weightText: String
            val repsText: String
            if (logged != null) {
                weightText = if (timed) "—" else logged.actualWeightLb?.let { fmtLbPlain(it) } ?: "BW"
                repsText = if (timed) "${logged.actualReps ?: 0}s" else "${logged.actualReps ?: 0}"
            } else {
                val tw = planned?.targetWeightLb ?: wex.targetWeightLb
                weightText = if (timed) "—" else tw?.let { fmtLbPlain(it) } ?: "BW"
                repsText = if (timed) "${wex.targetRepsLow}s"
                    else if (planned?.isAmrap == true) "${wex.targetRepsLow}+"
                    else repsRange(wex.targetRepsLow, wex.targetRepsHigh)
            }
            GridRow(
                state = state,
                setLabel = setLabel,
                sideLabel = side != null,
                weight = weightText,
                reps = repsText,
                rating = logged?.rating,
                // Corrections are rep-based; a hold is re-done, not edited.
                // Gated on the SESSION, never on the slot being closed.
                onEdit = if (sessionWritable) ({ onEditSet(n) } as () -> Unit)
                    .takeIf { logged != null && !timed } else null,
            )
        }
    }
}

private enum class GridRowState { Logged, Current, Pending, Skipped }

@Composable
private fun GridHead(text: String, modifier: Modifier) {
    Text(text, color = NeonMV.Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold,
        letterSpacing = 1.2.sp, fontFamily = NeonNumberFamily,
        modifier = modifier.padding(start = 8.dp))
}

@Composable
private fun GridRow(
    state: GridRowState,
    setLabel: String,
    sideLabel: Boolean,
    weight: String,
    reps: String,
    rating: Int?,
    onEdit: (() -> Unit)?,
) {
    val pal = LocalStrengthPalette.current
    val shape = RoundedCornerShape(10.dp)
    val bg = when (state) {
        GridRowState.Logged -> NeonMV.Lime.copy(alpha = 0.08f)
        GridRowState.Current -> NeonMV.Cyan.copy(alpha = 0.06f)
        else -> Color.Transparent
    }
    val ink = when (state) {
        GridRowState.Logged, GridRowState.Current -> pal.ink
        else -> pal.muted.copy(alpha = 0.75f)
    }
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 44.dp)
            .clip(shape)
            .background(bg)
            .then(if (state == GridRowState.Current)
                Modifier.border(1.5.dp, NeonMV.Cyan, shape) else Modifier)
            .padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            setLabel,
            color = if (sideLabel) NeonMV.Magenta else ink,
            fontWeight = FontWeight.Bold, fontFamily = NeonNumberFamily, fontSize = 14.sp,
            modifier = Modifier.width(GridSetW).padding(start = 8.dp),
        )
        Text(weight, color = ink, fontFamily = NeonNumberFamily, fontSize = 16.sp,
            fontWeight = if (state == GridRowState.Pending) FontWeight.Medium else FontWeight.Bold,
            modifier = Modifier.weight(1f).padding(start = 8.dp))
        Text(reps, color = ink, fontFamily = NeonNumberFamily, fontSize = 16.sp,
            fontWeight = if (state == GridRowState.Pending) FontWeight.Medium else FontWeight.Bold,
            modifier = Modifier.weight(1f).padding(start = 8.dp))
        Row(
            Modifier.width(GridLastW),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            when (state) {
                GridRowState.Logged -> {
                    Text(ratingLabel(rating ?: 0), color = ratingColor(rating ?: 0, pal),
                        fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                    if (onEdit != null) {
                        // OG2-A9: a fat-fingered 225 for 25 used to be
                        // permanent. The target is 40dp now (it was ~16).
                        IconButton(onClick = onEdit, modifier = Modifier.size(40.dp)) {
                            Icon(Icons.Outlined.Edit, contentDescription = "Edit set $setLabel",
                                tint = pal.muted, modifier = Modifier.size(18.dp))
                        }
                    } else {
                        Icon(Icons.Outlined.Check, contentDescription = "Logged",
                            tint = NeonMV.Lime, modifier = Modifier.padding(horizontal = 11.dp).size(18.dp))
                    }
                }
                GridRowState.Current -> Text("NOW", color = NeonMV.Cyan, fontSize = 11.sp,
                    fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
                    modifier = Modifier.padding(end = 12.dp))
                GridRowState.Skipped -> Text("skipped", color = pal.muted, fontSize = 12.sp,
                    modifier = Modifier.padding(end = 12.dp))
                GridRowState.Pending -> {}
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
internal fun TimedSetRow(
    n: Int,
    holdSeconds: Int,
    onComplete: (elapsedSeconds: Int, rating: Int) -> Unit,
    exerciseName: String = "",
    sideLabel: String? = null,
    /** Rendered inside the NOW hero (UI-2); the inline states below are
     *  styled for it. */
    @Suppress("UNUSED_PARAMETER") hero: Boolean = true,
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

    // Three states: rating prompt, running countdown, or idle Start.
    if (pendingElapsed != null) {
        // Rate the hold (WP-16): Easy = 5, Good = 4, Failed = 1. The next
        // session's generator reads it via adjust_mobility_target().
        Text(
            "${pendingElapsed}s held — how was it?",
            color = pal.ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((value, label) in listOf(5 to "Easy", 4 to "Good", 1 to "Failed")) {
                val c = ratingColor(value, pal)
                Box(
                    Modifier
                        .weight(1f)
                        .height(44.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(c.copy(alpha = 0.10f))
                        .border(1.dp, c.copy(alpha = 0.45f), RoundedCornerShape(12.dp))
                        .clickable { onComplete(pendingElapsed!!, value); pendingElapsed = null },
                    contentAlignment = Alignment.Center,
                ) { Text(label, color = c, fontSize = 14.sp, fontWeight = FontWeight.Bold) }
            }
        }
        return
    }

    if (remaining != null) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            app.myvitals.ui.neon.NeonNumber(
                if (remaining >= 60) "${remaining / 60}:${(remaining % 60).toString().padStart(2, '0')}"
                else "${remaining}s",
                color = holdViolet, size = 40,
            )
            Text("  of ${holdSeconds}s", color = pal.muted, fontSize = 14.sp,
                modifier = Modifier.weight(1f))
            TextButton(onClick = {
                // "Done" — end the hold early but still capture it.
                val elapsed = ((nowMs - startedAt) / 1000L).coerceAtLeast(1L).toInt()
                pendingElapsed = elapsed
                endsAt = 0L
            }, modifier = Modifier.heightIn(min = 40.dp)) {
                Text("Done", color = holdViolet, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            }
            TextButton(onClick = { endsAt = 0L }, modifier = Modifier.heightIn(min = 40.dp)) {
                Text("Cancel", color = pal.muted, fontSize = 14.sp)
            }
        }
    } else {
        Row(verticalAlignment = Alignment.Bottom) {
            app.myvitals.ui.neon.NeonNumber("$holdSeconds", size = 40)
            Text(" s hold", color = pal.muted, fontSize = 18.sp,
                modifier = Modifier.padding(bottom = 6.dp))
        }
        Spacer(Modifier.height(10.dp))
        Button(
            onClick = {
                startedAt = System.currentTimeMillis()
                endsAt = startedAt + holdSeconds * 1000L
            },
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier.fillMaxWidth().height(48.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = holdViolet, contentColor = NeonMV.OnAccent,
            ),
        ) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("Start hold", fontSize = 15.sp, fontWeight = FontWeight.Bold)
        }
    }
}

/** "6" when low==high, else "6–8" — the prescribed rep window. */
internal fun repsRange(low: Int, high: Int): String =
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
        error != null -> Text(error, color = pal.caution, fontSize = 12.sp)
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
    today: java.time.LocalDate = java.time.LocalDate.now(),
    onDayClick: (dateIso: String) -> Unit = {},
) {
    val pal = LocalStrengthPalette.current
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
internal fun ratingColor(r: Int, pal: StrengthPalette) = when (r) {
    1 -> if (pal.neon) NeonMV.Bad else MV.Red
    2 -> if (pal.neon) NeonMV.Amber else androidx.compose.ui.graphics.Color(0xFFF97316)
    3 -> if (pal.neon) NeonMV.Lime else MV.Amber
    4 -> if (pal.neon) NeonMV.Lime else androidx.compose.ui.graphics.Color(0xFF84CC16)
    5 -> if (pal.neon) NeonMV.Cyan else MV.Green
    else -> if (pal.neon) NeonMV.Muted else MV.OnSurfaceDim
}

// WP-16 — four-button labels; historical 1–5 RPE data still maps cleanly.
internal fun ratingLabel(r: Int) = when (r) {
    1 -> "Failed"; 2 -> "Hard"; 3, 4 -> "Good"; 5 -> "Easy"; else -> "RPE $r"
}

/** OG3-A3 — "3d ago · Hard" for the ghost line, or null when the server sent
 *  no date (rows logged before the field existed).
 *
 *  Mirrors `lastSetsWhen` in `StrengthToday.vue`; the two must agree, since
 *  they annotate the same prefilled number on the same session. */
internal fun lastSetsWhen(sets: List<app.myvitals.sync.LastSet>): String? {
    val iso = sets.firstOrNull { it.date != null }?.date ?: return null
    val then = runCatching { java.time.LocalDate.parse(iso) }.getOrNull() ?: return null
    val days = java.time.temporal.ChronoUnit.DAYS.between(then, java.time.LocalDate.now())
    val when_ = when {
        days <= 0L -> "today"
        days == 1L -> "yesterday"
        days < 7L -> "${days}d ago"
        else -> then.format(java.time.format.DateTimeFormatter.ofPattern("MMM d"))
    }
    val worst = sets.mapNotNull { it.rating }.minOrNull()
    return if (worst == null) when_ else "$when_ · ${ratingLabel(worst)}"
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
internal fun CardioLogDialog(
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
        containerColor = NeonMV.CardHigh,
        titleContentColor = NeonMV.Ink,
        textContentColor = NeonMV.Muted,
        shape = RoundedCornerShape(22.dp),
        title = { Text("Log this workout", fontWeight = FontWeight.Bold) },
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
            ) { Text("Cancel", color = NeonMV.Muted) }
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
        containerColor = NeonMV.CardHigh,
        titleContentColor = NeonMV.Ink,
        textContentColor = NeonMV.Muted,
        shape = RoundedCornerShape(22.dp),
        title = { Text(name, fontWeight = FontWeight.Bold) },
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
            }) { Text("Watch on YouTube", color = NeonMV.Lime) }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) {
                Text("Close", color = NeonMV.Muted)
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
