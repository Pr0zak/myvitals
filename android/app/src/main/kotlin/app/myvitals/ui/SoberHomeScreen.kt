package app.myvitals.ui

import androidx.compose.animation.AnimatedVisibility
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
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()

    var current by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
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
            loadError = "Backend not configured — swipe right to set URL + token."
            return
        }
        refreshing = true
        loadError = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            current = withContext(Dispatchers.IO) { api.soberCurrent() }
        } catch (e: Exception) {
            Timber.w(e, "soberCurrent failed")
            loadError = e.message?.take(160) ?: "Network error"
        } finally {
            refreshing = false
        }
    }

    LaunchedEffect(Unit) { fetch() }
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
            Text(
                "myvitals",
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.4.sp,
                color = MV.OnSurfaceVariant,
            )
            PagerDots(active = 0)
            Spacer(Modifier.width(48.dp))
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
                Spacer(Modifier.height(36.dp))

                Text(
                    text = "$d",
                    fontSize = 132.sp,
                    fontWeight = FontWeight.Light,
                    color = MV.OnSurface,
                    style = androidx.compose.ui.text.TextStyle(
                        fontFeatureSettings = "tnum",
                        letterSpacing = (-4).sp,
                    ),
                )
                Text(
                    text = if (d == 1) "day" else "days",
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Normal,
                    color = MV.OnSurface.copy(alpha = 0.92f),
                    letterSpacing = 0.2.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )

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

        // ── Sync pill + actions (full-width column so the children's
        //     CenterHorizontally + Center arrangement actually centers) ──
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, bottom = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            SyncStatusPill(settings = settings, nowMs = nowMs)
            Spacer(Modifier.height(14.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = { scope.launch { fetch() } }) {
                    Text(
                        if (refreshing) "Refreshing…" else "Refresh",
                        color = MV.OnSurfaceVariant,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }
                Spacer(Modifier.width(8.dp))
                Text("·", color = MV.OnSurfaceDim, fontSize = 14.sp)
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = onOpenSettings) {
                    Text(
                        "Settings ›",
                        color = MV.OnSurfaceVariant,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
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


@Composable
private fun SyncStatusPill(settings: SettingsRepository, nowMs: Long) {
    val lastSync = settings.lastSyncInstant()
    val lastSuccess = settings.lastSuccessInstant()
    val permsLost = settings.permissionsLost
    val freshest = listOfNotNull(lastSync, lastSuccess).maxByOrNull { it.epochSecond }
    val ageS = freshest?.let { (nowMs / 1000) - it.epochSecond } ?: -1L

    val (dot, text) = when {
        permsLost -> MV.Red to "perms revoked — open Settings"
        freshest == null -> MV.OnSurfaceDim to "no sync yet"
        ageS < 60 -> MV.Green to "synced just now"
        ageS < 3600 -> MV.Green to "synced ${ageS / 60}m ago"
        ageS < 86400 -> MV.Amber to "synced ${ageS / 3600}h ago"
        else -> MV.Amber to "synced ${ageS / 86400}d ago"
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(MV.SurfaceContainer)
            .border(1.dp, MV.OutlineVariant, RoundedCornerShape(50))
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(RoundedCornerShape(50))
                .background(dot),
        )
        Text(
            text = text,
            fontSize = 13.sp,
            color = MV.OnSurfaceVariant,
            letterSpacing = 0.1.sp,
        )
    }
}

@Composable
private fun PagerDots(active: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        for (i in 0..1) {
            val isActive = i == active
            Box(
                modifier = Modifier
                    .height(6.dp)
                    .width(if (isActive) 18.dp else 6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(
                        if (isActive) MV.OnSurface.copy(alpha = 0.95f)
                        else MV.OnSurfaceDim.copy(alpha = 0.5f),
                    ),
            )
        }
    }
}
