package app.myvitals.ui.neon

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.FastingSession
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.SoberCurrentResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Today — the neon home. Mirrors web `Rings.vue`: three glanceable goal rings
 * (Sleep magenta / Move lime / Recovery cyan) wired to /summary/today, then
 * Fasting / Sober / Steps / Workout pills, and an "almost there" CTA. Tapping
 * a ring or pill drills into the existing detail screen via [onOpen].
 *
 * onOpen routes used: "vitals/SLEEP", "vitals/STEPS", "vitals/HR" (recovery),
 * "fasting", "sober", "workout/today".
 */
@Composable
fun RingsScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    var summary by remember { mutableStateOf<DailySummary?>(null) }
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    var sober by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var fasting by remember { mutableStateOf<FastingSession?>(null) }
    var readiness by remember { mutableStateOf<app.myvitals.sync.ReadinessDetail?>(null) }
    var groupOrder by remember { mutableStateOf<List<String>>(emptyList()) }
    var focusCounts by remember {
        mutableStateOf<Map<String, app.myvitals.sync.FocusCount>>(emptyMap())
    }
    var rollup by remember {
        mutableStateOf<app.myvitals.sync.VitalTilesRollup?>(null)
    }
    var narrativeEvents by remember {
        mutableStateOf<List<app.myvitals.sync.NarrativeEvent>>(emptyList())
    }
    var vitalTiles by remember {
        mutableStateOf<List<app.myvitals.sync.VitalTile>>(emptyList())
    }
    var showFormula by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(true) }
    // Previously this screen could not fail, refresh, or report staleness: a
    // bare runCatching with .getOrNull() on every inner call meant a dead
    // backend, an expired token and "no data yet" all rendered as "—".
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val summaryD = async(Dispatchers.IO) {
                    runCatching { api.summaryToday() }.getOrNull()
                }
                val profileD = async(Dispatchers.IO) {
                    runCatching { api.profile() }.getOrNull()
                }
                val soberD = async(Dispatchers.IO) {
                    runCatching { api.soberCurrent() }.getOrNull()
                }
                val readyD = async(Dispatchers.IO) {
                    runCatching { api.readinessDetail() }.getOrNull()
                }
                // Threshold semantics for the tile grid. Non-fatal: an older
                // backend without /summary/tiles just renders no grid.
                val tilesD = async(Dispatchers.IO) {
                    runCatching { api.summaryTiles() }.getOrNull()
                }
                val eventsD = async(Dispatchers.IO) {
                    runCatching { api.summaryEvents().events }.getOrDefault(emptyList())
                }
                val fastingD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.fastingCurrent()
                        if (r.isSuccessful) r.body() else null
                    }.getOrNull()
                }
                val s0 = summaryD.await()
                val p0 = profileD.await()
                // Both null with a configured backend means the requests
                // failed — surface it instead of rendering empty rings.
                if (s0 == null && p0 == null) {
                    if (summary == null) error = "Couldn't reach the backend."
                } else {
                    error = null
                    summary = s0
                    profile = p0
                    sober = soberD.await()
                    fasting = fastingD.await()
                    readyD.await()?.let { readiness = it }
                    narrativeEvents = eventsD.await()
                    tilesD.await()?.let { r ->
                        if (r.tiles.isNotEmpty()) vitalTiles = r.tiles
                        rollup = r.summary
                        groupOrder = r.groupOrder
                        focusCounts = r.focusAreas
                    }
                }
            }
        } catch (e: Exception) {
            timber.log.Timber.w(e, "rings load failed")
            if (summary == null) error = e.message?.take(140) ?: "Load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }
    // Re-fetch on resume — a home screen that loads once shows yesterday's
    // numbers after an overnight suspend.
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }

    val sleepScore = summary?.sleepScore
    val recoveryScore = summary?.recoveryScore
    val steps = summary?.stepsTotal
    val stepGoal = profile?.stepsGoal() ?: 10_000
    val movePct: Float = if (steps != null && stepGoal > 0)
        min(100f, (steps.toFloat() / stepGoal.toFloat()) * 100f) else 0f

    NeonScreen(
        title = "Today",
        contentPadding = contentPadding,
        refreshing = refreshing,
        onRefresh = {
            scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
    ) {
        // Health status: the roll-up + Readiness as a MetricCard. The old
        // hero was a third card style stacked above the Focus pills and the
        // Key metrics grid; readiness is a metric and now looks like one.
        app.myvitals.ui.common.HealthStatus(
            readiness = readiness,
            rollup = rollup,
            // Freshness belongs WITH the numbers it qualifies. As a bare
            // Text between two sections it read as debug output.
            syncNote = summary?.lastSync?.let { iso ->
                syncAgeMinutes(iso)?.let { "Synced ${fmtSyncAge(it)}" }
            },
        )


        // Key metrics — one card vocabulary, mirroring KeyMetrics.vue.
        app.myvitals.ui.common.KeyMetrics(
            tiles = vitalTiles,
            onOpen = onOpen,
            // The neon home was ignoring the reorder / hide preference the
            // classic home honours, so the same user saw two orders.
            order = profile?.extra?.vitalsOrder ?: emptyList(),
            hidden = profile?.extra?.vitalsHidden?.toSet() ?: emptySet(),
            groupOrder = groupOrder,
        )
        error?.let {
            NeonErrorBanner(it) {
                scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
            }
        }
        if (loading && summary == null) {
            Text(
                "Loading…",
                color = NeonMV.Muted,
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 8.dp, bottom = 8.dp),
            )
        }




        // Narrative cards — what actually happened today, in plain words.
        app.myvitals.ui.common.NarrativeCards(
            events = narrativeEvents,
            onVote = { id, vote ->
                // Optimistic: reflect the tap now, write after. A rejected
                // write reverts rather than leaving a thumb lit for a vote
                // the server never took.
                val before = narrativeEvents
                narrativeEvents = narrativeEvents.map {
                    if (it.id == id) it.copy(feedback = vote) else it
                }
                scope.launch {
                    runCatching {
                        BackendClient.create(settings.backendUrl, settings.bearerToken)
                            .eventFeedback(id, app.myvitals.sync.EventFeedbackRequest(vote))
                    }.onFailure { narrativeEvents = before }
                }
            },
        )

        // Focus areas — navigation, not a dashboard. Replaces the pill list.
        app.myvitals.ui.common.FocusAreas(onOpen, counts = focusCounts)

        Spacer(Modifier.height(24.dp))
    }
}


/** Canvas goal-ring arc with a soft neon glow (a wider, translucent under-pass). */


/** Minutes since an ISO timestamp (handles both +00:00 offset and Z forms). */
private fun syncAgeMinutes(iso: String): Long? = runCatching {
    val ms = runCatching { java.time.OffsetDateTime.parse(iso).toInstant().toEpochMilli() }
        .getOrElse { java.time.Instant.parse(iso).toEpochMilli() }
    (System.currentTimeMillis() - ms) / 60_000L
}.getOrNull()

/** "just now" / "Nm ago" / "Nh ago" / "Nd ago" — same shape as the Trails header. */
private fun fmtSyncAge(min: Long): String = when {
    min < 1 -> "just now"
    min < 60 -> "${min}m ago"
    min < 60 * 24 -> "${min / 60}h ago"
    else -> "${min / (60 * 24)}d ago"
}
