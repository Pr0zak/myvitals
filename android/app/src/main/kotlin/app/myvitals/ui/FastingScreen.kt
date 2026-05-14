package app.myvitals.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.fasting.FastingMilestoneWorker
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FastingEndRequest
import app.myvitals.sync.FastingSession
import app.myvitals.sync.FastingStartRequest
import app.myvitals.sync.FastingStats
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Duration
import java.time.Instant

/**
 * Fasting — Compose mirror of the web Fasting.vue. Protocol picker,
 * ring + elapsed counter, start/end controls, stats, history.
 *
 * Backend ownership: all stage thresholds + elapsed_h come from
 * /fasting/* so phone and web render identical labels.
 */

private data class ProtocolSpec(
    val slug: String,
    val label: String,
    val targetH: Double,
    val eatingH: Double?,
)

private val PROTOCOLS = listOf(
    ProtocolSpec("16:8", "16:8", 16.0, 8.0),
    ProtocolSpec("18:6", "18:6", 18.0, 6.0),
    ProtocolSpec("20:4", "20:4", 20.0, 4.0),
    ProtocolSpec("omad", "OMAD", 23.0, 1.0),
    ProtocolSpec("extended_24", "24h", 24.0, null),
    ProtocolSpec("extended_36", "36h", 36.0, null),
    ProtocolSpec("extended_48", "48h", 48.0, null),
    ProtocolSpec("extended_72", "72h", 72.0, null),
)

private val STAGE_LABELS = mapOf(
    "fed" to "Fed state",
    "gut_rest" to "Gut rest",
    "glycogen_depleting" to "Glycogen depleting",
    "ketosis" to "Ketosis",
    "autophagy" to "Autophagy",
    "deep_autophagy" to "Deep autophagy",
    "extended_36" to "36h territory",
    "extended_48" to "48h territory",
    "extended_72" to "72h+ territory",
)

@Composable
fun FastingScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    var current by remember { mutableStateOf<FastingSession?>(null) }
    var history by remember { mutableStateOf<List<FastingSession>>(emptyList()) }
    var stats by remember { mutableStateOf<FastingStats?>(null) }
    var loading by remember { mutableStateOf(true) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableStateOf(PROTOCOLS[0].slug) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun loadAll() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.fastingCurrent() }
            // Endpoint returns 200 + null body for "no active fast". Retrofit
            // surfaces that as a successful Response with body() == null.
            current = if (resp.isSuccessful) resp.body() else null
            history = withContext(Dispatchers.IO) { api.fastingHistory(20) }
            stats = withContext(Dispatchers.IO) { api.fastingStats(90) }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "fasting load failed")
            error = e.message?.take(160)
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { loadAll() }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1_000)
            nowMs = System.currentTimeMillis()
        }
    }

    fun selectedSpec(): ProtocolSpec =
        PROTOCOLS.firstOrNull { it.slug == selected } ?: PROTOCOLS[0]

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MV.Bg)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = MV.OnSurface)
            }
            Text("Fasting", color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.weight(1f))
            stats?.let {
                Text(
                    "${it.currentStreakDays}d streak",
                    color = MV.OnSurfaceVariant,
                    fontSize = 12.sp,
                )
            }
        }

        error?.let {
            Text(it, color = MV.Red, fontSize = 12.sp,
                modifier = Modifier.padding(vertical = 4.dp))
        }

        if (loading && current == null) {
            Text("Loading…", color = MV.OnSurfaceVariant)
            return@Column
        }

        val cur = current
        if (cur != null && cur.isActive) {
            // ── Active fast hero ──
            val startInstant = runCatching { Instant.parse(cur.startedAt) }.getOrNull()
            val elapsedS = if (startInstant != null) {
                Duration.between(startInstant, Instant.ofEpochMilli(nowMs)).seconds
                    .coerceAtLeast(0)
            } else 0L
            val elapsedH = elapsedS / 3600.0
            val targetH = cur.targetHours ?: 16.0
            val progress = (elapsedH / targetH).coerceIn(0.0, 1.0)

            Spacer(Modifier.height(20.dp))
            Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                ProgressRing(progress = progress.toFloat())
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        fmtHours(elapsedH),
                        color = MV.OnSurface,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        (STAGE_LABELS[cur.currentStage] ?: cur.currentStage).uppercase(),
                        color = MV.BrandRed,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = 1.5.sp,
                    )
                    Text(
                        "of ${targetH.toInt()}h target",
                        color = MV.OnSurfaceVariant,
                        fontSize = 11.sp,
                    )
                }
            }

            Spacer(Modifier.height(20.dp))
            Section("Details")
            Kv("Protocol", cur.protocol)
            cur.nextStageAtH?.let { nxt ->
                Kv("Next milestone", "${(nxt - elapsedH).coerceAtLeast(0.0).format1()}h")
            }
            Kv("Started", cur.startedAt.take(16).replace("T", " "))

            Spacer(Modifier.height(16.dp))
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                            val sessionId = cur.id
                            withContext(Dispatchers.IO) {
                                api.fastingEnd(FastingEndRequest())
                            }
                            // Drop any pending milestone alarms for the
                            // session we just ended.
                            FastingMilestoneWorker.cancelAll(context, sessionId)
                            loadAll()
                        } catch (e: Exception) {
                            Timber.w(e, "end failed"); error = e.message?.take(160)
                        } finally { busy = false }
                    }
                },
                enabled = !busy,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MV.SurfaceContainerLow, contentColor = MV.Red,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (busy) "Ending…" else "End fast")
            }
        } else {
            // ── Idle / picker ──
            Section("Start a new fast")
            val rows = PROTOCOLS.chunked(4)
            for (row in rows) {
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 2.dp),
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    for (p in row) {
                        val on = selected == p.slug
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .height(56.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .background(if (on) MV.BrandRed else MV.SurfaceContainerLow)
                                .border(
                                    1.dp,
                                    if (on) MV.BrandRed else MV.OutlineVariant,
                                    RoundedCornerShape(8.dp),
                                )
                                .clickable { selected = p.slug },
                            contentAlignment = Alignment.Center,
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(p.label,
                                    color = if (on) MV.OnSurface else MV.OnSurfaceVariant,
                                    fontSize = 13.sp,
                                    fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                                )
                                Text("${p.targetH.toInt()}h",
                                    color = if (on) MV.OnSurface.copy(alpha = 0.85f) else MV.OnSurfaceDim,
                                    fontSize = 10.sp,
                                )
                            }
                        }
                    }
                    // Pad partial last row
                    repeat(4 - row.size) {
                        Box(modifier = Modifier.weight(1f))
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val spec = selectedSpec()
                            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                            val started = withContext(Dispatchers.IO) {
                                api.fastingStart(FastingStartRequest(
                                    protocol = spec.slug,
                                    targetHours = spec.targetH,
                                    targetEatingWindowH = spec.eatingH,
                                ))
                            }
                            // Schedule milestone notifications relative to
                            // the server-recorded start (not local now) so
                            // backdated starts hit the right boundaries.
                            val startMs = runCatching {
                                Instant.parse(started.startedAt).toEpochMilli()
                            }.getOrDefault(System.currentTimeMillis())
                            FastingMilestoneWorker.schedule(
                                context, started.id, startMs, spec.targetH,
                            )
                            loadAll()
                        } catch (e: Exception) {
                            Timber.w(e, "start failed"); error = e.message?.take(160)
                        } finally { busy = false }
                    }
                },
                enabled = !busy,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (busy) "Starting…" else "Start ${selectedSpec().label}")
            }
        }

        stats?.let { s ->
            if (s.sessionsCount > 0) {
                Spacer(Modifier.height(20.dp))
                Section("Last 90 days")
                Kv("Completed", "${s.completedCount} / ${s.sessionsCount}")
                s.avgDurationH?.let { Kv("Avg", "${it.format1()}h") }
                s.medianDurationH?.let { Kv("Median", "${it.format1()}h") }
                s.longestH?.let { Kv("Longest", "${it.format1()}h") }
            }
        }

        if (history.isNotEmpty()) {
            Spacer(Modifier.height(20.dp))
            Section("Recent")
            for (row in history) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(row.protocol, color = MV.OnSurface, fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.width(80.dp))
                    Text("${row.elapsedH.format1()}h", color = MV.OnSurface, fontSize = 13.sp)
                    Spacer(Modifier.weight(1f))
                    Text(row.startedAt.take(16).replace("T", " "),
                        color = MV.OnSurfaceVariant, fontSize = 11.sp)
                }
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun ProgressRing(progress: Float) {
    Canvas(modifier = Modifier.size(200.dp)) {
        val stroke = 14.dp.toPx()
        val diam = size.minDimension - stroke
        val tl = Offset((size.width - diam) / 2f, (size.height - diam) / 2f)
        // Track
        drawArc(
            color = Color(0xFF1F2738),
            startAngle = -90f,
            sweepAngle = 360f,
            useCenter = false,
            topLeft = tl,
            size = Size(diam, diam),
            style = Stroke(width = stroke, cap = StrokeCap.Round),
        )
        // Fill
        drawArc(
            color = Color(0xFFEF4444),
            startAngle = -90f,
            sweepAngle = 360f * progress.coerceIn(0f, 1f),
            useCenter = false,
            topLeft = tl,
            size = Size(diam, diam),
            style = Stroke(width = stroke, cap = StrokeCap.Round),
        )
    }
}

@Composable
private fun Section(title: String) {
    Text(
        title.uppercase(),
        color = MV.OnSurfaceVariant,
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.sp,
        modifier = Modifier.padding(top = 16.dp, bottom = 6.dp),
    )
}

@Composable
private fun Kv(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    ) {
        Text(label, color = MV.OnSurfaceVariant, fontSize = 13.sp,
            modifier = Modifier.weight(1f))
        Text(value, color = MV.OnSurface, fontSize = 13.sp)
    }
}

private fun fmtHours(h: Double): String {
    val wh = h.toInt()
    val m = ((h - wh) * 60).toInt()
    return "${wh}h ${m.toString().padStart(2, '0')}m"
}

private fun Double.format1(): String = "%.1f".format(this)
