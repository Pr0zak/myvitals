package app.myvitals.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.SoberResetRequest
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

@Composable
fun SoberHomeScreen(
    settings: SettingsRepository,
    onBack: (() -> Unit)? = null,
) {
    val scope = rememberCoroutineScope()

    var current by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var history by remember { mutableStateOf<List<app.myvitals.sync.SoberStreak>>(emptyList()) }
    var historyOpen by remember { mutableStateOf(false) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var resetting by remember { mutableStateOf(false) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun doReset() {
        if (!settings.isConfigured()) { loadError = "Backend not configured"; return }
        resetting = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                api.soberReset(SoberResetRequest(addiction = "alcohol"))
            }
            // Refetch from backend
            current = withContext(Dispatchers.IO) { api.soberCurrent() }
        } catch (e: Exception) {
            Timber.w(e, "soberReset failed")
            loadError = "Reset failed: ${e.message?.take(120)}"
        } finally { resetting = false }
    }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            loadError = "Backend not configured — open the Settings tab to set URL + token."
            return
        }
        loadError = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            current = withContext(Dispatchers.IO) { api.soberCurrent() }
            // History is non-critical — log + continue if it fails so the
            // counter still renders.
            history = runCatching {
                withContext(Dispatchers.IO) { api.soberHistory(limit = 100) }
            }.getOrElse {
                Timber.w(it, "soberHistory failed")
                emptyList()
            }
        } catch (e: Exception) {
            Timber.w(e, "soberCurrent failed")
            loadError = e.message?.take(160) ?: "Network error"
        }
    }

    LaunchedEffect(Unit) { fetch() }
    app.myvitals.ui.common.LifecycleResumeEffect {
        scope.launch { fetch() }
    }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            nowMs = System.currentTimeMillis()
        }
    }

    val active = current?.active
    val (d, h, m, s) = remember(active, nowMs) {
        if (active == null) intArrayOf(0, 0, 0, 0) else {
            val start = try { Instant.parse(active.startAt) } catch (_: Exception) { null }
            if (start == null) intArrayOf(0, 0, 0, 0) else {
                val totalS = maxOf(0, Duration.between(start, Instant.ofEpochMilli(nowMs)).seconds)
                intArrayOf(
                    (totalS / 86400).toInt(),
                    ((totalS % 86400) / 3600).toInt(),
                    ((totalS % 3600) / 60).toInt(),
                    (totalS % 60).toInt(),
                )
            }
        }
    }

    // Big faded BrandMark sits behind everything as a watermark — adds
    // brand identity to the screen without taking real estate from the
    // counter or reset button.
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MV.Bg),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = 80.dp),
            contentAlignment = Alignment.TopCenter,
        ) {
            BrandMark(
                dimension = 360.dp,
                heart = MV.BrandRed.copy(alpha = 0.05f),
                trace = MV.OnSurface.copy(alpha = 0.04f),
            )
        }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding(),
    ) {
        // ── Top brand row — wordmark only; the big logo is the watermark behind. ──
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 24.dp, end = 24.dp, top = 16.dp, bottom = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (onBack != null) {
                androidx.compose.material3.IconButton(onClick = onBack) {
                    androidx.compose.material3.Icon(
                        Icons.AutoMirrored.Outlined.ArrowBack,
                        contentDescription = "Back",
                        tint = MV.OnSurface,
                    )
                }
            } else {
                Text(
                    "myvitals",
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    letterSpacing = 0.4.sp,
                    color = MV.OnSurfaceVariant,
                )
            }
        }

        // ── Hero ──
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(horizontal = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            if (active == null) {
                EmptyState()
            } else {
                Text(
                    "SOBER TIME",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 3.6.sp,
                    color = MV.OnSurfaceVariant,
                )
                Spacer(Modifier.height(24.dp))

                // Milestone ring — wraps the day count. Stroke arc
                // sweeps clockwise from 12 o'clock to the fraction of
                // the next milestone reached. Mirrors web Sober.vue.
                val (mTarget, mFraction, mRemaining) = remember(d, h, m) {
                    val elapsedDays = d + h / 24.0 + m / 1440.0
                    val milestones = listOf(7, 14, 30, 60, 90, 180, 365, 730)
                    val next = milestones.firstOrNull { it > elapsedDays }
                    if (next == null) {
                        Triple(730, 1.0, 0.0)
                    } else {
                        val prev = milestones.reversed().firstOrNull { it <= elapsedDays } ?: 0
                        val frac = ((elapsedDays - prev) / (next - prev))
                            .coerceIn(0.0, 1.0)
                        Triple(next, frac, (next - elapsedDays).coerceAtLeast(0.0))
                    }
                }
                Box(
                    modifier = Modifier.size(280.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
                        val stroke = androidx.compose.ui.graphics.drawscope
                            .Stroke(width = 6.dp.toPx(),
                                    cap = androidx.compose.ui.graphics.StrokeCap.Round)
                        val ringColor = androidx.compose.ui.graphics.Color(0xFF22C55E)
                        val bgColor = ringColor.copy(alpha = 0.10f)
                        val padding = stroke.width / 2f
                        val arcSize = androidx.compose.ui.geometry.Size(
                            size.width - padding * 2, size.height - padding * 2,
                        )
                        val topLeft = androidx.compose.ui.geometry.Offset(padding, padding)
                        drawArc(
                            color = bgColor,
                            startAngle = 0f, sweepAngle = 360f, useCenter = false,
                            topLeft = topLeft, size = arcSize, style = stroke,
                        )
                        drawArc(
                            color = ringColor,
                            startAngle = -90f,
                            sweepAngle = (360f * mFraction).toFloat(),
                            useCenter = false,
                            topLeft = topLeft, size = arcSize, style = stroke,
                        )
                    }
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = "$d",
                            fontSize = 96.sp,
                            fontWeight = FontWeight.Light,
                            color = MV.OnSurface,
                            style = androidx.compose.ui.text.TextStyle(
                                fontFeatureSettings = "tnum",
                                letterSpacing = (-3).sp,
                            ),
                        )
                        Text(
                            text = if (d == 1) "day" else "days",
                            fontSize = 18.sp,
                            color = MV.OnSurface.copy(alpha = 0.92f),
                        )
                        Text(
                            text = if (mRemaining > 0)
                                "%.1f d to ${mTarget}d".format(mRemaining)
                            else "All milestones cleared",
                            fontSize = 11.sp,
                            color = MV.OnSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }

                Spacer(Modifier.height(28.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.Bottom,
                ) {
                    TickerSeg(value = h.toString(), unit = "h")
                    TickerSeg(value = m.toString().padStart(2, '0'), unit = "m")
                    TickerSeg(value = s.toString().padStart(2, '0'), unit = "s")
                }

                Spacer(Modifier.height(18.dp))
                val sinceLabel = remember(active) {
                    try {
                        val inst = Instant.parse(active.startAt)
                        val zoned = inst.atZone(ZoneId.systemDefault())
                        zoned.format(DateTimeFormatter.ofPattern("EEE d MMM, h:mm a"))
                    } catch (_: Exception) { active.startAt }
                }
                Text(
                    "since $sinceLabel",
                    fontSize = 13.sp,
                    color = MV.OnSurfaceDim,
                    letterSpacing = 0.2.sp,
                )
            }
        }

        // ── Past streaks (collapsed by default) ──
        // The active streak is included in history; filter it out so this
        // panel only lists CLOSED past attempts. Shows the top 5 longest
        // by default plus a button to expand the rest.
        val pastStreaks = remember(history) {
            history.filter { it.endAt != null }
                .sortedByDescending { it.days }
        }
        if (pastStreaks.isNotEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                TextButton(onClick = { historyOpen = !historyOpen }) {
                    Text(
                        text = if (historyOpen)
                            "Hide past streaks"
                        else
                            "Past streaks (${pastStreaks.size}) ›",
                        color = MV.OnSurfaceVariant,
                        fontSize = 13.sp, fontWeight = FontWeight.Medium,
                    )
                }
                AnimatedVisibility(visible = historyOpen) {
                    Column(modifier = Modifier.fillMaxWidth()) {
                        val show = pastStreaks.take(20)
                        for (st in show) {
                            StreakRow(streak = st)
                        }
                        if (pastStreaks.size > show.size) {
                            Text(
                                text = "+${pastStreaks.size - show.size} older",
                                color = MV.OnSurfaceDim, fontSize = 11.sp,
                                modifier = Modifier.padding(top = 4.dp),
                            )
                        }
                    }
                }
            }
        }

        // ── Reset button ──
        Box(modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 18.dp)) {
            ResetButton(
                hasActive = active != null,
                onTriggered = {
                    scope.launch { doReset() }
                },
                resetting = resetting,
            )
        }

        AnimatedVisibility(visible = loadError != null) {
            Text(
                text = loadError.orEmpty(),
                color = MV.Red,
                fontSize = 12.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 8.dp),
            )
        }
    }
    }   // Close watermark Box wrapper

    // (Hold-to-reset is now the home button itself — no popup.)
}

@Composable
private fun StreakRow(streak: app.myvitals.sync.SoberStreak) {
    val df = remember { DateTimeFormatter.ofPattern("MMM d, yyyy") }
    val startStr = remember(streak.startAt) {
        runCatching {
            Instant.parse(streak.startAt).atZone(ZoneId.systemDefault()).format(df)
        }.getOrDefault(streak.startAt.take(10))
    }
    val endStr = remember(streak.endAt) {
        streak.endAt?.let {
            runCatching {
                Instant.parse(it).atZone(ZoneId.systemDefault()).format(df)
            }.getOrDefault(it.take(10))
        }
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "${"%.1f".format(streak.days)} day${if (streak.days >= 2) "s" else ""}",
                color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.Medium,
            )
            Text(
                text = if (endStr != null) "$startStr → $endStr" else startStr,
                color = MV.OnSurfaceDim, fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun TickerSeg(value: String, unit: String) {
    Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(
            text = value,
            fontSize = 22.sp,
            fontWeight = FontWeight.Medium,
            color = MV.OnSurface.copy(alpha = 0.85f),
            style = androidx.compose.ui.text.TextStyle(fontFeatureSettings = "tnum"),
        )
        Text(
            text = unit,
            fontSize = 13.sp,
            color = MV.OnSurfaceDim,
            modifier = Modifier.padding(end = 4.dp, bottom = 2.dp),
        )
    }
}

@Composable
private fun EmptyState() {
    Box(
        modifier = Modifier
            .size(84.dp)
            .clip(RoundedCornerShape(50))
            .border(1.5.dp, MV.Outline, RoundedCornerShape(50)),
        contentAlignment = Alignment.Center,
    ) { BrandMark(dimension = 40.dp) }
    Spacer(Modifier.height(24.dp))
    Text(
        "SOBER TIME",
        fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 3.6.sp,
        color = MV.OnSurfaceVariant,
    )
    Spacer(Modifier.height(16.dp))
    Text(
        "No active streak yet",
        fontSize = 28.sp, fontWeight = FontWeight.Normal,
        color = MV.OnSurface, textAlign = TextAlign.Center,
    )
    Spacer(Modifier.height(10.dp))
    Text(
        "Start counting from now, or pick a date in Settings.",
        fontSize = 14.sp, color = MV.OnSurfaceVariant,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun ResetButton(hasActive: Boolean, onTriggered: () -> Unit, resetting: Boolean) {
    // No-active-streak: simple tap, this is the lightweight "Start counting" path.
    if (!hasActive) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(88.dp)
                .clip(RoundedCornerShape(24.dp))
                .background(MV.SurfaceContainer)
                .pointerInput(Unit) { detectTapGestures(onTap = { onTriggered() }) },
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "Start counting",
                fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.5.sp, color = MV.OnSurfaceVariant,
            )
        }
        return
    }
    // Active streak: hold-to-open. Same gesture pattern as the dialog's
    // confirm button — completing the hold opens the popup instead of
    // firing the reset, so casual taps never even see the dialog.
    val progress = remember { mutableFloatStateOf(0f) }
    val scope = rememberCoroutineScope()
    var heldJob: Job? = remember { null }
    val holding = progress.floatValue > 0f && progress.floatValue < 1f

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(96.dp)
            .clip(RoundedCornerShape(28.dp))
            .background(MV.AmberDim)
            .pointerInput(resetting) {
                if (resetting) return@pointerInput
                detectTapGestures(
                    onPress = {
                        progress.floatValue = 0f
                        heldJob?.cancel()
                        heldJob = scope.launch {
                            val start = System.currentTimeMillis()
                            while (isActive) {
                                val elapsed = System.currentTimeMillis() - start
                                val p = (elapsed.toFloat() / HOLD_DURATION_MS).coerceIn(0f, 1f)
                                progress.floatValue = p
                                if (p >= 1f) {
                                    onTriggered(); break
                                }
                                delay(16)
                            }
                        }
                        val released = tryAwaitRelease()
                        if (!released || progress.floatValue < 1f) heldJob?.cancel()
                        progress.floatValue = 0f
                    },
                )
            },
    ) {
        Box(
            modifier = Modifier
                .fillMaxHeight()
                .fillMaxWidth(if (resetting) 1f else progress.floatValue.coerceAtLeast(if (holding) 0.001f else 1f))
                .background(MV.Amber),
        )
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                text = when {
                    resetting -> "Resetting…"
                    holding -> "Keep holding…"
                    else -> "Press & hold to reset"
                },
                fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.6.sp, color = MV.AmberOn,
            )
        }
    }
}


