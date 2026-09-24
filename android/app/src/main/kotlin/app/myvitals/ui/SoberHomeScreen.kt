package app.myvitals.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.SoberResetRequest
import app.myvitals.sync.SoberStreak
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonPillShape
import app.myvitals.ui.neon.NeonRing
import app.myvitals.ui.neon.NeonRingCaption
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private const val HOLD_DURATION_MS = 1500L

/**
 * Sober time. Fetching wrapper around the stateless [SoberContent].
 *
 * UI-6: the milestone ladder, the ring fill and the next milestone all come
 * from `/sober/current`; only the seconds ticker runs locally, from the
 * server's start instant. The phone used to keep its own milestone list and
 * derive "next" from a locally ticked day count.
 */
@Composable
fun SoberHomeScreen(
    settings: SettingsRepository,
    onBack: (() -> Unit)? = null,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current

    var current by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var history by remember { mutableStateOf<List<SoberStreak>>(emptyList()) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var actionError by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var resetting by remember { mutableStateOf(false) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val historyType = remember {
        app.myvitals.data.JsonCache.listType(SoberStreak::class.java)
    }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            loadError = "Backend not configured — open Settings to set URL + token."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val fresh = withContext(Dispatchers.IO) { api.soberCurrent() }
            current = fresh
            loadError = null
            app.myvitals.data.JsonCache.write(
                context, "sober_current", SoberCurrentResponse::class.java, fresh,
            )
            // History is non-critical — the counter still renders without it.
            val freshHist = runCatching {
                withContext(Dispatchers.IO) { api.soberHistory(limit = 100) }
            }.getOrElse { Timber.w(it, "soberHistory failed"); null }
            if (freshHist != null) {
                history = freshHist
                app.myvitals.data.JsonCache.write(context, "sober_history", historyType, freshHist)
            }
        } catch (e: Exception) {
            Timber.w(e, "soberCurrent failed")
            // A failed request must never read as "no active streak":
            // keep the cached streak if there is one, otherwise SAY it failed.
            loadError = e.message?.take(160) ?: "Network error"
        } finally {
            loading = false
        }
    }

    suspend fun doReset() {
        if (!settings.isConfigured()) { actionError = "Backend not configured"; return }
        resetting = true
        actionError = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) { api.soberReset(SoberResetRequest(addiction = "alcohol")) }
            fetch()
        } catch (e: Exception) {
            Timber.w(e, "soberReset failed")
            actionError = "Reset didn't go through: ${e.message?.take(120)}"
        } finally { resetting = false }
    }

    LaunchedEffect(Unit) {
        app.myvitals.data.JsonCache.read<SoberCurrentResponse>(
            context, "sober_current", SoberCurrentResponse::class.java,
        )?.let { current = it.value; loading = false }
        app.myvitals.data.JsonCache.read<List<SoberStreak>>(
            context, "sober_history", historyType,
        )?.let { history = it.value }
        fetch()
    }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { fetch() } }
    LaunchedEffect(Unit) {
        while (true) { delay(1000); nowMs = System.currentTimeMillis() }
    }
    // The day count and milestones are the server's. When the local ticker
    // crosses into a new day (or past the named milestone), ask again rather
    // than advancing the number here.
    val active = current?.active
    val tickerDays = active?.let { elapsedSeconds(it.startAt, nowMs)?.div(86400) }
    val nextAtMs = current?.nextMilestoneAt?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }
    LaunchedEffect(tickerDays, nextAtMs != null && nowMs >= nextAtMs) {
        val serverDays = current?.days
        if (tickerDays != null && serverDays != null && tickerDays > serverDays) fetch()
    }

    SoberContent(
        current = current,
        history = history,
        loading = loading,
        error = loadError,
        actionError = actionError,
        nowMs = nowMs,
        resetting = resetting,
        refreshing = refreshing,
        contentPadding = PaddingValues(0.dp),
        onBack = onBack,
        onReset = { scope.launch { doReset() } },
        onRefresh = {
            scope.launch { refreshing = true; try { fetch() } finally { refreshing = false } }
        },
    )
}

private fun elapsedSeconds(startIso: String, nowMs: Long): Long? =
    runCatching { Instant.parse(startIso) }.getOrNull()?.let {
        maxOf(0L, Duration.between(it, Instant.ofEpochMilli(nowMs)).seconds)
    }

/** "17d 16h", "5h 12m", "12m" — a countdown to a server-given instant. */
internal fun fmtCountdown(seconds: Long): String {
    val d = seconds / 86400
    val h = (seconds % 86400) / 3600
    val m = (seconds % 3600) / 60
    return when {
        d > 0 -> "${d}d ${h}h"
        h > 0 -> "${h}h ${m}m"
        else -> "${m}m"
    }
}

/**
 * Stateless Sober screen. Renders exactly what it is given; the only local
 * arithmetic is the seconds ticker and the countdown to the server's
 * `next_milestone_at`.
 */
@Composable
fun SoberContent(
    current: SoberCurrentResponse?,
    history: List<SoberStreak>,
    loading: Boolean,
    error: String?,
    actionError: String?,
    nowMs: Long,
    resetting: Boolean,
    refreshing: Boolean,
    contentPadding: PaddingValues,
    onBack: (() -> Unit)?,
    onReset: () -> Unit,
    onRefresh: () -> Unit,
) {
    NeonScreen(
        title = "Sober",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (error != null && current != null) {
            // Cached streak on screen, refresh failed: say so, keep it visible.
            StaleNote("Showing the last streak we loaded — refresh failed.")
        }
        when {
            current == null && error != null ->
                LoadFailedCard("Couldn't load your streak", error, onRefresh)
            current == null -> SoberHeroLoading()
            current.active == null -> SoberHeroEmpty()
            else -> SoberHero(current, current.active, nowMs)
        }

        // Past streaks — every one, current included, as neutral bars. A
        // streak that ended is a fact about the past, not a failure: magenta
        // like the rest of the screen, never red or amber.
        val bars = remember(history) { history.sortedByDescending { it.startAt }.take(12) }
        if (bars.isNotEmpty()) {
            NeonEyebrow("Streaks")
            StreakBars(bars)
            if (history.size > bars.size) {
                Text("+${history.size - bars.size} older", color = NeonMV.Muted, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp))
            }
        }

        // Reset sits BELOW the history and is deliberately quiet: an outlined
        // bar in Line/Muted. It used to be a full-width solid amber slab —
        // colouring a reset as a warning is the one thing this screen must
        // not do.
        if (current != null) {
            Spacer(Modifier.height(20.dp))
            ResetButton(hasActive = current.active != null, resetting = resetting, onTriggered = onReset)
        }
        actionError?.let {
            Text(it, color = NeonMV.Muted, fontSize = 12.sp, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun SoberHero(current: SoberCurrentResponse, active: SoberStreak, nowMs: Long) {
    val ms = current.milestones
    val reached = current.milestonesReached
    val dots = ms.mapIndexed { i, _ -> (i + 1).toFloat() / ms.size to (i < reached) }
    val totalS = elapsedSeconds(active.startAt, nowMs) ?: 0L
    val days = current.days ?: 0
    NeonHeroCard(accent = NeonMV.Magenta) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            NeonRing(
                fraction = (current.milestoneProgress ?: 0.0).toFloat(),
                color = NeonMV.Magenta,
                size = 260.dp,
                stroke = 12.dp,
                dots = dots,
            ) {
                NeonNumber("$days", color = NeonMV.Magenta, size = 76)
                NeonRingCaption(if (days == 1) "day sober" else "days sober")
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.Bottom) {
                    TickerSeg(((totalS % 86400) / 3600).toString(), "h")
                    TickerSeg(((totalS % 3600) / 60).toString().padStart(2, '0'), "m")
                    TickerSeg((totalS % 60).toString().padStart(2, '0'), "s")
                }
            }
            Spacer(Modifier.height(14.dp))
            val nextDays = current.nextMilestoneDays
            val nextAt = current.nextMilestoneAt?.let { runCatching { Instant.parse(it) }.getOrNull() }
            if (nextDays != null && nextAt != null) {
                val left = maxOf(0L, Duration.between(Instant.ofEpochMilli(nowMs), nextAt).seconds)
                Pill("Next · $nextDays days in ${fmtCountdown(left)}", NeonMV.Magenta)
            }
            Spacer(Modifier.height(8.dp))
            val since = remember(active.startAt) {
                runCatching {
                    Instant.parse(active.startAt).atZone(ZoneId.systemDefault())
                        .format(DateTimeFormatter.ofPattern("EEE d MMM yyyy, h:mm a"))
                }.getOrDefault(active.startAt)
            }
            Text("since $since", color = NeonMV.Muted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun SoberHeroEmpty() {
    NeonHeroCard(accent = NeonMV.Magenta) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            NeonRing(fraction = 0f, color = NeonMV.Magenta, size = 260.dp, stroke = 12.dp) {
                NeonNumber("0", color = NeonMV.Muted, size = 64)
                NeonRingCaption("no active streak")
            }
            Spacer(Modifier.height(12.dp))
            Text("Start counting from now, or pick a date in Settings.",
                color = NeonMV.Muted, fontSize = 13.sp, textAlign = TextAlign.Center)
        }
    }
}

@Composable
private fun SoberHeroLoading() {
    NeonHeroCard(accent = NeonMV.Magenta) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            NeonRing(fraction = 0f, color = NeonMV.Magenta, size = 260.dp, stroke = 12.dp) {
                Text("Loading your streak…", color = NeonMV.Muted, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun StreakBars(streaks: List<SoberStreak>) {
    val longest = streaks.maxOf { it.days }.coerceAtLeast(0.01)
    val df = remember { DateTimeFormatter.ofPattern("MMM d, yyyy") }
    Column(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        for (st in streaks) {
            val isCurrent = st.endAt == null
            val alpha = if (isCurrent) 1f else 0.6f
            val start = runCatching {
                Instant.parse(st.startAt).atZone(ZoneId.systemDefault()).format(df)
            }.getOrDefault(st.startAt.take(10))
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (isCurrent) "Now · since $start" else "from $start",
                        color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                    NeonNumber("%.1f d".format(st.days), color = NeonMV.Ink.copy(alpha = alpha), size = 13)
                }
                Spacer(Modifier.height(4.dp))
                Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(NeonMV.Track)) {
                    Box(Modifier.fillMaxHeight()
                        .fillMaxWidth((st.days / longest).toFloat().coerceIn(0.02f, 1f))
                        .clip(RoundedCornerShape(4.dp))
                        .background(NeonMV.Magenta.copy(alpha = alpha)))
                }
            }
        }
    }
}

@Composable
private fun TickerSeg(value: String, unit: String) {
    Row(verticalAlignment = Alignment.Bottom) {
        NeonNumber(value, color = NeonMV.Ink.copy(alpha = 0.85f), size = 16, weight = FontWeight.Medium)
        Text(unit, color = NeonMV.Muted, fontSize = 11.sp,
            modifier = Modifier.padding(start = 1.dp, end = 5.dp, bottom = 2.dp))
    }
}

@Composable
internal fun Pill(text: String, color: Color) {
    Text(
        text, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier
            .clip(NeonPillShape)
            .background(color.copy(alpha = 0.12f))
            .border(1.dp, color.copy(alpha = 0.35f), NeonPillShape)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

/** A cached render is on screen but the refresh failed. */
@Composable
internal fun StaleNote(text: String) {
    Text(text, color = NeonMV.Muted, fontSize = 11.sp,
        modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp))
}

/**
 * A request failed and there is nothing cached. Amber, not rose (rose is for
 * crisis surfaces), and never the "empty" state of the screen — a dead
 * backend is not "no streak", "not fasting" or "nothing logged".
 */
@Composable
internal fun LoadFailedCard(title: String, message: String, onRetry: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(NeonMV.Amber.copy(alpha = 0.08f))
            .border(1.dp, NeonMV.Amber.copy(alpha = 0.30f), RoundedCornerShape(14.dp))
            .clickable(onClick = onRetry)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(title, color = NeonMV.Amber, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(2.dp))
        Text(message, color = NeonMV.Muted, fontSize = 12.sp)
        Spacer(Modifier.height(4.dp))
        Text("Tap to retry", color = NeonMV.Cyan, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun ResetButton(hasActive: Boolean, resetting: Boolean, onTriggered: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    if (!hasActive) {
        Box(
            Modifier.fillMaxWidth().height(56.dp).clip(shape)
                .border(1.dp, NeonMV.Magenta.copy(alpha = 0.45f), shape)
                .clickable(enabled = !resetting, onClick = onTriggered),
            contentAlignment = Alignment.Center,
        ) {
            Text(if (resetting) "Starting…" else "Start counting",
                color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
        }
        return
    }
    // Hold-to-reset guards against a stray tap. The hold fill is a faint
    // periwinkle wash — it shows progress without turning the bar into an
    // alarm. "Resetting…" stays in the same calm Muted.
    val progress = remember { mutableFloatStateOf(0f) }
    val scope = rememberCoroutineScope()
    var heldJob: Job? = remember { null }
    val holding = progress.floatValue > 0f && progress.floatValue < 1f
    Box(
        Modifier
            .fillMaxWidth()
            .height(56.dp)
            .clip(shape)
            .border(1.dp, NeonMV.Line, shape)
            .pointerInput(resetting) {
                if (resetting) return@pointerInput
                detectTapGestures(onPress = {
                    progress.floatValue = 0f
                    heldJob?.cancel()
                    heldJob = scope.launch {
                        val start = System.currentTimeMillis()
                        while (isActive) {
                            val p = ((System.currentTimeMillis() - start).toFloat() / HOLD_DURATION_MS)
                                .coerceIn(0f, 1f)
                            progress.floatValue = p
                            if (p >= 1f) { onTriggered(); break }
                            delay(16)
                        }
                    }
                    val released = tryAwaitRelease()
                    if (!released || progress.floatValue < 1f) heldJob?.cancel()
                    progress.floatValue = 0f
                })
            },
    ) {
        if (holding) {
            Box(Modifier.fillMaxHeight().fillMaxWidth(progress.floatValue)
                .background(NeonMV.Periwinkle.copy(alpha = 0.30f)))
        }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                when {
                    resetting -> "Resetting…"
                    holding -> "Keep holding…"
                    else -> "Press & hold to reset"
                },
                color = NeonMV.Muted, fontSize = 15.sp, fontWeight = FontWeight.Medium,
            )
        }
    }
}
