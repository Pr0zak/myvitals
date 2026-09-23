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
    // TILE-1: the tile order is its own endpoint now. Reading it from
    // profile.extra meant every client re-implemented the legacy enum
    // translation, and the two copies disagreed about skin temp.
    var tilePrefs by remember { mutableStateOf<app.myvitals.sync.TilePrefsOut?>(null) }
    var sober by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var fasting by remember { mutableStateOf<FastingSession?>(null) }
    var readiness by remember { mutableStateOf<app.myvitals.sync.ReadinessDetail?>(null) }
    var groupOrder by remember { mutableStateOf<List<String>>(emptyList()) }
    var week by remember { mutableStateOf<app.myvitals.sync.WeekProgress?>(null) }
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
                // Non-fatal: an older backend without /profile/tile-prefs
                // simply renders the tiles in their catalog order.
                val tilePrefsD = async(Dispatchers.IO) {
                    runCatching { api.tilePrefs() }.getOrNull()
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
                    tilePrefsD.await()?.let { tilePrefs = it }
                    sober = soberD.await()
                    fasting = fastingD.await()
                    readyD.await()?.let { readiness = it }
                    narrativeEvents = eventsD.await()
                    tilesD.await()?.let { r ->
                        if (r.tiles.isNotEmpty()) vitalTiles = r.tiles
                        rollup = r.summary
                        groupOrder = r.groupOrder
                        week = r.week
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

    RingsContent(
        summary = summary,
        readiness = readiness,
        rollup = rollup,
        vitalTiles = vitalTiles,
        week = week,
        tilePrefs = tilePrefs,
        groupOrder = groupOrder,
        narrativeEvents = narrativeEvents,
        focusCounts = focusCounts,
        error = error,
        loading = loading,
        refreshing = refreshing,
        contentPadding = contentPadding,
        onOpen = onOpen,
        weeklyLoad = { app.myvitals.ui.common.WeeklyLoad(settings) },
        onRefresh = {
            scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
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
}

/**
 * The Today screen from data, with no fetching of its own — so it renders
 * in a JVM screenshot test exactly as it does on the phone. [RingsScreen]
 * owns the state and the network; this owns the layout.
 */
@Composable
fun RingsContent(
    summary: DailySummary?,
    readiness: app.myvitals.sync.ReadinessDetail?,
    rollup: app.myvitals.sync.VitalTilesRollup?,
    vitalTiles: List<app.myvitals.sync.VitalTile>,
    week: app.myvitals.sync.WeekProgress?,
    tilePrefs: app.myvitals.sync.TilePrefsOut?,
    groupOrder: List<String>,
    narrativeEvents: List<app.myvitals.sync.NarrativeEvent>,
    focusCounts: Map<String, app.myvitals.sync.FocusCount>,
    error: String?,
    loading: Boolean,
    refreshing: Boolean,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
    weeklyLoad: @Composable () -> Unit,
    onRefresh: () -> Unit,
    onVote: (String, String?) -> Unit,
) {
    NeonScreen(
        title = "Today",
        contentPadding = contentPadding,
        // DAY-1: entry point to the single-day view. Opens on today; the
        // picker inside moves from there.
        headerTrailing = {
            androidx.compose.material3.Text(
                "Day view",
                color = NeonMV.Cyan,
                fontSize = 12.sp,
                modifier = Modifier
                    .clip(androidx.compose.foundation.shape.RoundedCornerShape(999.dp))
                    .clickable { onOpen("day/${java.time.LocalDate.now()}") }
                    .padding(horizontal = 10.dp, vertical = 5.dp),
            )
        },
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        // Nothing has loaded yet — first launch, or a cold start with the
        // backend unreachable. The cards below used to render anyway, so a
        // failed request read as "0% · 0 of 0" and "Readiness: No data · Not
        // enough data yet", with the actual error further down the page.
        // Failure is not absence: say which one it is, and skip the cards
        // that would otherwise claim the user has no data.
        val nothingYet = summary == null && vitalTiles.isEmpty()
        if (nothingYet && error != null) {
            NeonErrorBanner(error) { onRefresh() }
            app.myvitals.ui.common.FocusAreas(onOpen, counts = focusCounts)
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        if (nothingYet && loading) {
            TodaySkeleton()
            return@NeonScreen
        }

        // Hero: weekly ring + saturated chips + actions, per the reference.
        app.myvitals.ui.common.TodayHero(
            tiles = vitalTiles,
            week = week,
            readiness = readiness?.score,
            onOpen = onOpen,
        )

        // Weekly load, replacing the daily-goal framing for training. Sits
        // directly under the hero because it answers the same question the
        // ring does — "am I on track this week" — for effort rather than steps.
        weeklyLoad()

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
            order = tilePrefs?.order ?: emptyList(),
            hidden = tilePrefs?.hidden?.toSet() ?: emptySet(),
            groupOrder = groupOrder,
        )
        error?.let { NeonErrorBanner(it) { onRefresh() } }

        // Narrative cards — what actually happened today, in plain words.
        app.myvitals.ui.common.NarrativeCards(
            events = narrativeEvents,
            onOpenDetail = { onOpen("vitals/SLEEP") },
            onVote = onVote,
        )

        // Focus areas — navigation, not a dashboard. Replaces the pill list.
        app.myvitals.ui.common.FocusAreas(onOpen, counts = focusCounts)

        Spacer(Modifier.height(24.dp))
    }
}


/** Placeholder blocks in the shape of the loaded screen: hero, weekly
 *  load, health status, then a 2-up metric grid. Each block names what is
 *  loading into it and sweeps in that section's own colour, so the page
 *  reads as "on its way" rather than as a blank layout. */
@Composable
private fun TodaySkeleton() {
    @Composable
    fun Block(label: String, accent: Color, height: androidx.compose.ui.unit.Dp, modifier: Modifier) {
        Box(modifier.height(height)) {
            app.myvitals.ui.common.ShimmerBlock(
                Modifier.fillMaxWidth(), height = height, cornerRadius = 20.dp, accent = accent,
            )
            Text(
                label, color = accent.copy(alpha = 0.75f), fontSize = 12.sp,
                modifier = Modifier.padding(14.dp),
            )
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Block("Weekly steps", NeonMV.Lime, 200.dp, Modifier.weight(1f))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Block("Steps", NeonMV.Lime, 60.dp, Modifier.fillMaxWidth())
            Block("Readiness", NeonMV.Cyan, 60.dp, Modifier.fillMaxWidth())
            Block("Sleep", NeonMV.Magenta, 60.dp, Modifier.fillMaxWidth())
        }
    }
    Spacer(Modifier.height(14.dp))
    Block("Training load", NeonMV.Lime, 230.dp, Modifier.fillMaxWidth())
    Spacer(Modifier.height(14.dp))
    Block("Health status", NeonMV.Cyan, 48.dp, Modifier.fillMaxWidth())
    Spacer(Modifier.height(14.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Block("HRV", NeonMV.Cyan, 170.dp, Modifier.weight(1f))
        Block("Resting HR", NeonMV.Cyan, 170.dp, Modifier.weight(1f))
    }
    Spacer(Modifier.height(10.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Block("Sleep", NeonMV.Magenta, 170.dp, Modifier.weight(1f))
        Block("Recovery", NeonMV.Cyan, 170.dp, Modifier.weight(1f))
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
