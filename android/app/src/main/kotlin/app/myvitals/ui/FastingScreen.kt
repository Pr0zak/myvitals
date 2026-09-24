package app.myvitals.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.fasting.FastingMilestoneWorker
import app.myvitals.fasting.FastingWidgetProvider
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FastingEndRequest
import app.myvitals.sync.FastingLogRequest
import app.myvitals.sync.FastingSession
import app.myvitals.sync.FastingStartRequest
import app.myvitals.sync.FastingStats
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonRing
import app.myvitals.ui.neon.NeonRingCaption
import app.myvitals.ui.neon.NeonScreen
import app.myvitals.ui.neon.NeonStatTile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Fasting — fetching wrapper around the stateless [FastingContent].
 *
 * Backend ownership: elapsed_h, the stage, its label, the next stage, every
 * stage threshold (the ring's ticks), the target end instant and whether a
 * past fast reached its target all come from the fasting endpoints. The only local
 * arithmetic is the live ticker from the server's start instant.
 * (Kotlin nests block comments — never write `/<asterisk>` inside a KDoc
 * block or the whole file stops parsing.)
 */

data class ProtocolSpec(
    val slug: String,
    val label: String,
    val targetH: Double,
    val eatingH: Double?,
)

val FASTING_PROTOCOLS = listOf(
    ProtocolSpec("16:8", "16:8", 16.0, 8.0),
    ProtocolSpec("18:6", "18:6", 18.0, 6.0),
    ProtocolSpec("20:4", "20:4", 20.0, 4.0),
    ProtocolSpec("omad", "OMAD", 23.0, 1.0),
    ProtocolSpec("extended_24", "24h", 24.0, null),
    ProtocolSpec("extended_36", "36h", 36.0, null),
    ProtocolSpec("extended_48", "48h", 48.0, null),
    ProtocolSpec("extended_72", "72h", 72.0, null),
)

/** An in-fast symptom log, as typed. */
data class FastingLogInput(val hunger: Int, val mood: Int, val hydrationMl: Int?, val notes: String?)

@Composable
fun FastingScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    var current by remember { mutableStateOf<FastingSession?>(null) }
    // Whether we actually KNOW if a fast is running. A failed /current must
    // not fall through to the "start a fast" picker, which reads as "not
    // fasting" — the old code also mapped any non-2xx to null.
    var currentKnown by remember { mutableStateOf(false) }
    var history by remember { mutableStateOf<List<FastingSession>>(emptyList()) }
    var stats by remember { mutableStateOf<FastingStats?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var actionError by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableStateOf(FASTING_PROTOCOLS[0].slug) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var logSaving by remember { mutableStateOf(false) }
    var logMsg by remember { mutableStateOf<String?>(null) }

    val historyType = remember { app.myvitals.data.JsonCache.listType(FastingSession::class.java) }

    suspend fun loadAll() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.fastingCurrent() }
            if (!resp.isSuccessful) throw IllegalStateException("fasting/current HTTP ${resp.code()}")
            current = resp.body()
            currentKnown = true
            current?.let {
                app.myvitals.data.JsonCache.write(context, "fasting_current", FastingSession::class.java, it)
            }
            val freshHist = withContext(Dispatchers.IO) { api.fastingHistory(20) }
            history = freshHist
            app.myvitals.data.JsonCache.write(context, "fasting_history", historyType, freshHist)
            val freshStats = withContext(Dispatchers.IO) { api.fastingStats(90) }
            stats = freshStats
            app.myvitals.data.JsonCache.write(context, "fasting_stats", FastingStats::class.java, freshStats)
            error = null
        } catch (e: Exception) {
            Timber.w(e, "fasting load failed")
            error = e.message?.take(160) ?: "Network error"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        app.myvitals.data.JsonCache.read<FastingSession>(
            context, "fasting_current", FastingSession::class.java,
        )?.let { current = it.value; currentKnown = true }
        app.myvitals.data.JsonCache.read<List<FastingSession>>(
            context, "fasting_history", historyType,
        )?.let { history = it.value }
        app.myvitals.data.JsonCache.read<FastingStats>(
            context, "fasting_stats", FastingStats::class.java,
        )?.let { stats = it.value }
        loadAll()
    }
    LaunchedEffect(Unit) {
        while (true) { delay(1_000); nowMs = System.currentTimeMillis() }
    }

    FastingContent(
        current = current,
        currentKnown = currentKnown,
        history = history,
        stats = stats,
        loading = loading,
        error = error,
        actionError = actionError,
        nowMs = nowMs,
        selected = selected,
        busy = busy,
        logSaving = logSaving,
        logMsg = logMsg,
        refreshing = refreshing,
        contentPadding = PaddingValues(0.dp),
        onBack = onBack,
        onRefresh = {
            scope.launch { refreshing = true; try { loadAll() } finally { refreshing = false } }
        },
        onSelect = { selected = it },
        onStart = { spec ->
            scope.launch {
                busy = true; actionError = null
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    val started = withContext(Dispatchers.IO) {
                        api.fastingStart(FastingStartRequest(
                            protocol = spec.slug, targetHours = spec.targetH,
                            targetEatingWindowH = spec.eatingH,
                        ))
                    }
                    // Milestone alarms are relative to the SERVER start so
                    // backdated starts hit the right boundaries.
                    val startMs = runCatching { Instant.parse(started.startedAt).toEpochMilli() }
                        .getOrDefault(System.currentTimeMillis())
                    FastingMilestoneWorker.schedule(context, started.id, startMs, spec.targetH)
                    FastingWidgetProvider.refreshAll(context)
                    loadAll()
                } catch (e: Exception) {
                    Timber.w(e, "start failed"); actionError = "Couldn't start: ${e.message?.take(140)}"
                } finally { busy = false }
            }
        },
        onEnd = { sessionId ->
            scope.launch {
                busy = true; actionError = null
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    withContext(Dispatchers.IO) { api.fastingEnd(FastingEndRequest()) }
                    FastingMilestoneWorker.cancelAll(context, sessionId)
                    FastingWidgetProvider.refreshAll(context)
                    loadAll()
                } catch (e: Exception) {
                    Timber.w(e, "end failed"); actionError = "Couldn't end: ${e.message?.take(140)}"
                } finally { busy = false }
            }
        },
        onLog = { sessionId, input ->
            scope.launch {
                logSaving = true; logMsg = null
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    withContext(Dispatchers.IO) {
                        api.fastingLogAdd(FastingLogRequest(
                            sessionId = sessionId, hunger = input.hunger, mood = input.mood,
                            hydrationMl = input.hydrationMl, notes = input.notes,
                        ))
                    }
                    logMsg = "Logged."
                } catch (e: Exception) {
                    Timber.w(e, "log add failed"); logMsg = e.message?.take(160)
                } finally { logSaving = false }
            }
        },
    )
}

private val TIME_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("h:mm a")
private val START_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("EEE d MMM, h:mm a")

/** Server ISO instant → the user's LOCAL wall clock. Never the raw UTC string. */
internal fun localTime(iso: String?, fmt: DateTimeFormatter = TIME_FMT): String? =
    iso?.let { runCatching { Instant.parse(it).atZone(ZoneId.systemDefault()).format(fmt) }.getOrNull() }

private fun liveElapsedH(cur: FastingSession, nowMs: Long): Double {
    val start = runCatching { Instant.parse(cur.startedAt) }.getOrNull() ?: return cur.elapsedH
    return Duration.between(start, Instant.ofEpochMilli(nowMs)).seconds.coerceAtLeast(0) / 3600.0
}

@Composable
fun FastingContent(
    current: FastingSession?,
    currentKnown: Boolean,
    history: List<FastingSession>,
    stats: FastingStats?,
    loading: Boolean,
    error: String?,
    actionError: String?,
    nowMs: Long,
    selected: String,
    busy: Boolean,
    logSaving: Boolean,
    logMsg: String?,
    refreshing: Boolean,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onSelect: (String) -> Unit,
    onStart: (ProtocolSpec) -> Unit,
    onEnd: (Long) -> Unit,
    onLog: (Long, FastingLogInput) -> Unit,
) {
    NeonScreen(
        title = "Fasting",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
        headerTrailing = {
            stats?.let { Pill("${it.currentStreakDays}d streak", NeonMV.Cyan) }
        },
    ) {
        if (error != null && currentKnown) StaleNote("Showing what we last loaded — refresh failed.")

        when {
            !currentKnown && error != null ->
                LoadFailedCard("Couldn't load your fast", error, onRefresh)
            !currentKnown -> NeonHeroCard(accent = NeonMV.Cyan) {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    NeonRing(0f, NeonMV.Cyan, 260.dp, stroke = 12.dp) {
                        Text("Loading your fast…", color = NeonMV.Muted, fontSize = 13.sp)
                    }
                }
            }
            current != null && current.isActive -> {
                ActiveFastHero(current, nowMs)
                if (current.protocol.startsWith("extended_") || liveElapsedH(current, nowMs) >= 12.0) {
                    FastingLogForm(saving = logSaving, msg = logMsg) { onLog(current.id, it) }
                }
                Spacer(Modifier.height(12.dp))
                OutlinedAction(if (busy) "Ending…" else "End fast", enabled = !busy) { onEnd(current.id) }
            }
            else -> {
                NeonEyebrow("Start a fast")
                ProtocolCarousel(selected, onSelect)
                Spacer(Modifier.height(12.dp))
                val spec = FASTING_PROTOCOLS.firstOrNull { it.slug == selected } ?: FASTING_PROTOCOLS[0]
                Box(
                    Modifier.fillMaxWidth().height(52.dp).clip(RoundedCornerShape(16.dp))
                        .background(NeonMV.Cyan).clickable(enabled = !busy) { onStart(spec) },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(if (busy) "Starting…" else "Start ${spec.label}",
                        color = NeonMV.OnAccent, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
        actionError?.let {
            Text(it, color = NeonMV.Amber, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
        }

        if (history.isNotEmpty()) {
            NeonEyebrow("Last ${history.size} fasts")
            FastHistoryChart(history)
            Spacer(Modifier.height(8.dp))
            for (row in history.take(5)) {
                Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(localTime(row.startedAt, START_FMT) ?: "—", color = NeonMV.Muted, fontSize = 12.sp,
                        modifier = Modifier.weight(1f))
                    Text(row.protocol, color = NeonMV.Muted, fontSize = 12.sp, modifier = Modifier.padding(end = 10.dp))
                    NeonNumber("%.1fh".format(row.elapsedH), size = 13,
                        color = if (row.reachedTarget == true) NeonMV.Cyan else NeonMV.Ink)
                }
            }
        }

        stats?.let { s ->
            if (s.sessionsCount > 0) {
                NeonEyebrow("Last 90 days")
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NeonStatTile("${s.completedCount} / ${s.sessionsCount}", "completed", Modifier.weight(1f))
                    NeonStatTile(s.avgDurationH?.let { "%.1fh".format(it) } ?: "—", "average", Modifier.weight(1f))
                }
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    NeonStatTile(s.medianDurationH?.let { "%.1fh".format(it) } ?: "—", "median", Modifier.weight(1f))
                    NeonStatTile(s.longestH?.let { "%.1fh".format(it) } ?: "—", "longest", Modifier.weight(1f),
                        accent = NeonMV.Cyan)
                }
            }
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun ActiveFastHero(cur: FastingSession, nowMs: Long) {
    val elapsedH = liveElapsedH(cur, nowMs)
    // Ring scale: the target when there is one, otherwise the next stage
    // threshold (so an open-ended fast still shows where the next tick is).
    val lastStage = cur.stages.lastOrNull()?.atH ?: 72.0
    val scale = cur.targetHours
        ?: cur.stages.firstOrNull { it.atH > elapsedH }?.atH
        ?: lastStage
    val ticks = cur.stages.filter { it.atH > 0 && it.atH < scale }.map { (it.atH / scale).toFloat() }
    val wh = elapsedH.toInt()
    val wm = ((elapsedH - wh) * 60).toInt()
    NeonHeroCard(accent = NeonMV.Cyan) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            NeonRing(
                fraction = (elapsedH / scale).toFloat(),
                color = NeonMV.Cyan, size = 260.dp, stroke = 12.dp, ticks = ticks,
            ) {
                NeonNumber("$wh:${wm.toString().padStart(2, '0')}", color = NeonMV.Ink, size = 48)
                NeonRingCaption(cur.targetHours?.let { "of ${it.toInt()}h · ${cur.protocol}" } ?: cur.protocol)
            }
            Spacer(Modifier.height(12.dp))
            Pill(cur.currentStageLabel ?: cur.currentStage, NeonMV.Cyan)
            Spacer(Modifier.height(8.dp))
            val parts = buildList {
                localTime(cur.targetEndAt)?.let { add("Ends $it") }
                val nxt = cur.nextStageAtH
                val label = cur.nextStageLabel
                if (nxt != null && label != null) {
                    add("$label in ${"%.1f".format((nxt - elapsedH).coerceAtLeast(0.0))}h")
                }
            }
            if (parts.isNotEmpty()) {
                Text(parts.joinToString(" · "), color = NeonMV.Muted, fontSize = 13.sp, textAlign = TextAlign.Center)
            }
            localTime(cur.startedAt, START_FMT)?.let {
                Text("started $it", color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp))
            }
        }
    }
}

/** Last N fasts as bars (oldest left), each with its target as a tick. */
@Composable
private fun FastHistoryChart(history: List<FastingSession>) {
    val rows = history.take(20).reversed()
    val maxH = rows.maxOf { maxOf(it.elapsedH, it.targetHours ?: 0.0) }.coerceAtLeast(1.0)
    Box(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape).padding(14.dp),
    ) {
        Canvas(Modifier.fillMaxWidth().height(120.dp)) {
            val n = rows.size
            val slot = size.width / n
            val bw = (slot * 0.62f).coerceAtMost(18.dp.toPx())
            rows.forEachIndexed { i, r ->
                val x = slot * i + (slot - bw) / 2
                val h = (r.elapsedH / maxH).toFloat() * size.height
                // Completed = reached target (server-judged). A short fast is
                // Muted, not red: stopping early is allowed.
                val c = when (r.reachedTarget) {
                    true -> NeonMV.Cyan
                    false -> NeonMV.Muted.copy(alpha = 0.55f)
                    null -> NeonMV.Periwinkle.copy(alpha = 0.7f)
                }
                drawRoundRect(c, Offset(x, size.height - h),
                    androidx.compose.ui.geometry.Size(bw, h.coerceAtLeast(2f)),
                    androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()))
                r.targetHours?.let { t ->
                    val y = size.height - (t / maxH).toFloat() * size.height
                    drawLine(NeonMV.Ink.copy(alpha = 0.75f), Offset(x - 2.dp.toPx(), y),
                        Offset(x + bw + 2.dp.toPx(), y), strokeWidth = 2.dp.toPx())
                }
            }
        }
    }
    Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        LegendDot(NeonMV.Cyan, "reached target")
        LegendDot(NeonMV.Muted.copy(alpha = 0.55f), "short")
        Text("— target", color = NeonMV.Muted, fontSize = 11.sp)
    }
}

@Composable
private fun LegendDot(c: Color, label: String) {
    Box(Modifier.width(8.dp).height(8.dp).clip(RoundedCornerShape(2.dp)).background(c))
    Text(label, color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(start = 4.dp, end = 12.dp))
}

@Composable
private fun ProtocolCarousel(selected: String, onSelect: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        for (p in FASTING_PROTOCOLS) {
            val on = p.slug == selected
            Column(
                Modifier.width(118.dp).clip(NeonCardShape)
                    .background(if (on) NeonMV.CardHigh else NeonMV.Card)
                    .border(if (on) 1.5.dp else 1.dp, if (on) NeonMV.Cyan else NeonMV.Line, NeonCardShape)
                    .clickable { onSelect(p.slug) }
                    .padding(12.dp),
            ) {
                NeonNumber(p.label, color = if (on) NeonMV.Cyan else NeonMV.Ink, size = 20)
                Text("${p.targetH.toInt()}h fast", color = NeonMV.Muted, fontSize = 11.sp)
                Spacer(Modifier.height(10.dp))
                EatingWindowBar(p)
                Text(
                    p.eatingH?.let { "${it.toInt()}h eating" } ?: "no eating window",
                    color = NeonMV.Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp),
                )
            }
        }
    }
}

/** A 24h day: fasting hours in cyan, the eating window in lime at the end. */
@Composable
private fun EatingWindowBar(p: ProtocolSpec) {
    val eat = ((p.eatingH ?: 0.0) / 24.0).toFloat().coerceIn(0f, 1f)
    Row(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(NeonMV.Track)) {
        Box(Modifier.weight(1f - eat + 0.0001f).fillMaxHeight().background(NeonMV.Cyan.copy(alpha = 0.55f)))
        if (eat > 0f) Box(Modifier.weight(eat).fillMaxHeight().background(NeonMV.Lime))
    }
}

@Composable
private fun OutlinedAction(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Box(
        Modifier.fillMaxWidth().height(52.dp).clip(shape).border(1.dp, NeonMV.Line, shape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(text, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold) }
}

@Composable
private fun FastingLogForm(saving: Boolean, msg: String?, onSubmit: (FastingLogInput) -> Unit) {
    var hunger by remember { mutableIntStateOf(5) }
    var mood by remember { mutableIntStateOf(5) }
    var hydration by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    NeonEyebrow("How are you feeling?")
    Column(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape).padding(14.dp),
    ) {
        LogSlider("Hunger", hunger) { hunger = it }
        LogSlider("Mood", mood) { mood = it }
        val fieldColors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
            focusedTextColor = NeonMV.Ink, unfocusedTextColor = NeonMV.Ink,
        )
        androidx.compose.material3.OutlinedTextField(
            value = hydration, onValueChange = { v -> hydration = v.filter { it.isDigit() } },
            label = { Text("Hydration today (ml)", fontSize = 11.sp) }, singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), colors = fieldColors,
        )
        androidx.compose.material3.OutlinedTextField(
            value = notes, onValueChange = { notes = it },
            label = { Text("Notes", fontSize = 11.sp) }, minLines = 2,
            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), colors = fieldColors,
        )
        Spacer(Modifier.height(6.dp))
        OutlinedAction(if (saving) "Saving…" else "Log entry", enabled = !saving) {
            onSubmit(FastingLogInput(hunger, mood, hydration.toIntOrNull(), notes.ifBlank { null }))
            notes = ""
        }
        msg?.let { Text(it, color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 4.dp)) }
    }
}

@Composable
private fun LogSlider(label: String, value: Int, onChange: (Int) -> Unit) {
    Column(Modifier.padding(vertical = 2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = NeonMV.Muted, fontSize = 12.sp, modifier = Modifier.weight(1f))
            Text("$value / 10", color = NeonMV.Ink, fontSize = 12.sp)
        }
        androidx.compose.material3.Slider(
            value = value.toFloat(),
            onValueChange = { onChange(it.toInt().coerceIn(0, 10)) },
            valueRange = 0f..10f, steps = 9,
            colors = androidx.compose.material3.SliderDefaults.colors(
                thumbColor = NeonMV.Cyan, activeTrackColor = NeonMV.Cyan, inactiveTrackColor = NeonMV.Track,
            ),
        )
    }
}
