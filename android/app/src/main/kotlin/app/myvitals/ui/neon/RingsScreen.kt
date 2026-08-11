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
    var rollup by remember {
        mutableStateOf<app.myvitals.sync.VitalTilesRollup?>(null)
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
                    tilesD.await()?.let { r ->
                        if (r.tiles.isNotEmpty()) vitalTiles = r.tiles
                        rollup = r.summary
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
        app.myvitals.ui.common.HealthStatus(readiness, rollup)


        // Key metrics — one card vocabulary, mirroring KeyMetrics.vue.
        app.myvitals.ui.common.KeyMetrics(
            tiles = vitalTiles,
            onOpen = onOpen,
            // The neon home was ignoring the reorder / hide preference the
            // classic home honours, so the same user saw two orders.
            order = profile?.extra?.vitalsOrder ?: emptyList(),
            hidden = profile?.extra?.vitalsHidden?.toSet() ?: emptySet(),
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


        // ---- Last-sync freshness — is my data up to date? ----
        // last_sync rides /summary/today (newest HR sample); no extra fetch.
        val syncAge = summary?.lastSync?.let { syncAgeMinutes(it) }
        if (syncAge != null) {
            Text(
                "Synced ${fmtSyncAge(syncAge)}",
                color = if (syncAge > 360) NeonMV.Amber else NeonMV.Muted,
                fontSize = 11.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(bottom = 18.dp),
            )
        } else {
            Spacer(Modifier.height(18.dp))
        }


        // Focus areas — navigation, not a dashboard. Replaces the pill list.
        app.myvitals.ui.common.FocusAreas(onOpen)

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun GoalRing(
    label: String,
    pct: Float,
    valueText: String,
    showPercent: Boolean,
    glyph: String,
    color: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f),
            contentAlignment = Alignment.Center,
        ) {
            RingArc(pct = pct, color = color, modifier = Modifier.fillMaxWidth().aspectRatio(1f))
            Text(glyph, color = color, fontSize = 22.sp)
        }
        Spacer(Modifier.height(8.dp))
        Text(
            label,
            color = NeonMV.Muted,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.2.sp,
        )
        Spacer(Modifier.height(1.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            NeonNumber(valueText, color = NeonMV.Ink, size = 18)
            if (showPercent) {
                Text(
                    "%",
                    color = NeonMV.Muted,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 2.dp),
                )
            }
        }
    }
}

/** Canvas goal-ring arc with a soft neon glow (a wider, translucent under-pass). */
@Composable
private fun RingArc(pct: Float, color: Color, modifier: Modifier = Modifier) {
    Canvas(modifier = modifier) {
        val p = pct.coerceIn(0f, 100f) / 100f
        val stroke = size.minDimension * 0.10f
        val pad = stroke / 2f + size.minDimension * 0.04f
        val arcSize = Size(size.width - pad * 2f, size.height - pad * 2f)
        val topLeft = Offset(pad, pad)
        val sweep = p * 360f

        // Track
        drawArc(
            color = NeonMV.Track,
            startAngle = -90f,
            sweepAngle = 360f,
            useCenter = false,
            topLeft = topLeft,
            size = arcSize,
            style = Stroke(width = stroke),
        )
        if (sweep <= 0f) return@Canvas
        // Glow under-pass — wider + translucent.
        drawArc(
            color = color.copy(alpha = 0.30f),
            startAngle = -90f,
            sweepAngle = sweep,
            useCenter = false,
            topLeft = topLeft,
            size = arcSize,
            style = Stroke(width = stroke * 1.9f, cap = StrokeCap.Round),
        )
        // Progress arc.
        drawArc(
            color = color,
            startAngle = -90f,
            sweepAngle = sweep,
            useCenter = false,
            topLeft = topLeft,
            size = arcSize,
            style = Stroke(width = stroke, cap = StrokeCap.Round),
        )
    }
}

@Composable
private fun PillRow(
    glyph: String,
    accent: Color,
    name: String,
    onClick: () -> Unit,
    value: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonPillShape)
            .background(NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape)
                .background(accent.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Text(glyph, color = accent, fontSize = 17.sp)
        }
        Spacer(Modifier.width(14.dp))
        Text(
            name,
            color = NeonMV.Ink,
            fontSize = 16.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(1f),
        )
        Row(verticalAlignment = Alignment.Bottom) { value() }
    }
}

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
