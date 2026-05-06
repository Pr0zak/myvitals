package app.myvitals.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.SoberResetRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val GREEN = Color(0xFF22C55E)
private val GREEN_SOFT = Color(0xFFA7F3D0)
// Reset button uses amber rather than red — "caution, this clears your
// streak" reads better than alarm-level red, and stays clearly distinct
// from the green active-streak text above it.
private val ACCENT = Color(0xFFF59E0B)        // amber-500
private val ACCENT_DIM = Color(0xFF78350F)    // amber-900 (hold-base)
private val DIM = Color(0xFF94A3B8)
private val ERROR = Color(0xFFEF4444)          // still red for actual errors

@Composable
fun SoberHomeScreen(
    settings: SettingsRepository,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    var current by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var showResetDialog by remember { mutableStateOf(false) }
    var resetting by remember { mutableStateOf(false) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

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

    // First load + a 1s ticker so the d/h/m/s display feels alive.
    LaunchedEffect(Unit) { fetch() }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            nowMs = System.currentTimeMillis()
        }
    }

    val active = current?.active
    val (d, h, m, s) = remember(active, nowMs) {
        if (active == null) intArrayOf(0, 0, 0, 0)
        else {
            val start = try { Instant.parse(active.startAt) } catch (_: Exception) { null }
            if (start == null) intArrayOf(0, 0, 0, 0)
            else {
                val dur = Duration.between(start, Instant.ofEpochMilli(nowMs))
                val totalS = maxOf(0, dur.seconds)
                intArrayOf(
                    (totalS / 86400).toInt(),
                    ((totalS % 86400) / 3600).toInt(),
                    ((totalS % 3600) / 60).toInt(),
                    (totalS % 60).toInt(),
                )
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(20.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            // ── Header ──
            Text(
                text = "Sober time",
                style = MaterialTheme.typography.labelLarge,
                color = DIM,
            )
            Spacer(Modifier.height(6.dp))

            // ── Big counter ──
            if (active != null) {
                Row(verticalAlignment = Alignment.Bottom) {
                    NumberAndLabel(d, "d", color = GREEN, sizeSp = 88)
                    Spacer(Modifier.width(10.dp))
                    NumberAndLabel(h, "h", color = GREEN_SOFT, sizeSp = 56)
                    Spacer(Modifier.width(6.dp))
                    NumberAndLabel(m, "m", color = GREEN_SOFT, sizeSp = 56)
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    text = "%02ds".format(s),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 18.sp,
                    color = DIM,
                )
                Spacer(Modifier.height(8.dp))
                val sinceLabel = remember(active) {
                    try {
                        val inst = Instant.parse(active.startAt)
                        val zoned = inst.atZone(ZoneId.systemDefault())
                        zoned.format(DateTimeFormatter.ofPattern("EEE d MMM, HH:mm"))
                    } catch (_: Exception) { active.startAt }
                }
                Text(
                    text = "since $sinceLabel",
                    color = DIM,
                    fontSize = 14.sp,
                )
            } else {
                Text(
                    text = if (refreshing) "Loading…" else "No active streak",
                    color = DIM,
                    fontSize = 18.sp,
                )
            }

            Spacer(Modifier.height(40.dp))

            // ── Big reset button ──
            Button(
                onClick = { showResetDialog = true },
                enabled = settings.isConfigured() && !resetting,
                colors = ButtonDefaults.buttonColors(
                    containerColor = ACCENT,
                    contentColor = Color.Black,
                ),
                shape = RoundedCornerShape(20.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(96.dp),
            ) {
                Text(
                    text = if (active == null) "Start streak"
                           else if (resetting) "Resetting…" else "Reset",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            Spacer(Modifier.height(16.dp))

            AnimatedVisibility(visible = loadError != null) {
                Text(
                    text = loadError.orEmpty(),
                    color = ERROR,
                    fontSize = 12.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }

        // Bottom-right hint to swipe for settings
        Row(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = { scope.launch { fetch() } }) {
                Text(if (refreshing) "Refreshing…" else "Refresh", color = DIM, fontSize = 12.sp)
            }
            TextButton(onClick = onOpenSettings) {
                Text("Settings ›", color = DIM, fontSize = 12.sp)
            }
        }
    }

    // ── Reset confirmation dialog ──
    if (showResetDialog) {
        AlertDialog(
            onDismissRequest = { showResetDialog = false },
            confirmButton = {
                HoldToConfirmButton(
                    label = if (active == null) "Hold to start" else "Hold to reset",
                    onConfirm = {
                        showResetDialog = false
                        scope.launch {
                            resetting = true
                            try {
                                if (!settings.isConfigured()) {
                                    loadError = "Backend not configured"
                                    return@launch
                                }
                                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                                withContext(Dispatchers.IO) {
                                    api.soberReset(SoberResetRequest(addiction = "alcohol"))
                                }
                                fetch()
                            } catch (e: Exception) {
                                Timber.w(e, "soberReset failed")
                                loadError = "Reset failed: ${e.message?.take(120)}"
                            } finally {
                                resetting = false
                            }
                        }
                    },
                )
            },
            dismissButton = {
                TextButton(onClick = { showResetDialog = false }) { Text("Cancel") }
            },
            title = { Text(if (active == null) "Start a new streak?" else "Reset sober timer?") },
            text = {
                Text(
                    if (active == null)
                        "Hold the red button below for a moment to start tracking from now."
                    else
                        "Closes the current ${d}d ${h}h streak and starts a new one from now. " +
                        "The closed streak stays in your history. " +
                        "Hold the red button below to confirm — release to cancel."
                )
            },
        )
    }
}

@Composable
private fun NumberAndLabel(
    value: Int,
    label: String,
    color: Color,
    sizeSp: Int,
) {
    Row(verticalAlignment = Alignment.Bottom) {
        Text(
            text = value.toString(),
            color = color,
            fontSize = sizeSp.sp,
            fontWeight = FontWeight.SemiBold,
            fontFamily = FontFamily.Monospace,
        )
        Spacer(Modifier.width(2.dp))
        Text(
            text = label,
            color = DIM,
            fontSize = (sizeSp * 0.32).toInt().sp,
            modifier = Modifier.padding(bottom = (sizeSp * 0.12).toInt().dp),
        )
    }
}

private const val HOLD_DURATION_MS = 1500L

/**
 * A red confirm button that fires [onConfirm] only after the user
 * holds it for [HOLD_DURATION_MS]. Lifting before completion cancels
 * the animation and the action — prevents accidental taps from
 * destroying a streak.
 *
 * Implementation: pointerInput(detectTapGestures) drives a coroutine
 * that ramps a `progress` ref from 0→1 over the hold duration;
 * if that coroutine is cancelled (finger lifted), the action never fires.
 * The fill bar inside the button visualises the held progress.
 */
@Composable
private fun HoldToConfirmButton(
    label: String,
    onConfirm: () -> Unit,
) {
    val progress = remember { mutableFloatStateOf(0f) }
    val scope = rememberCoroutineScope()
    var heldJob: Job? = remember { null }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(ACCENT_DIM)          // dim amber base
            .pointerInput(Unit) {
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
                                    onConfirm()
                                    break
                                }
                                kotlinx.coroutines.delay(16)
                            }
                        }
                        // Suspend until release / cancel
                        val released = tryAwaitRelease()
                        if (!released || progress.floatValue < 1f) {
                            heldJob?.cancel()
                        }
                        progress.floatValue = 0f
                    },
                )
            },
    ) {
        // Progress fill
        Box(
            modifier = Modifier
                .fillMaxHeight()
                .fillMaxWidth(progress.floatValue)
                .background(ACCENT),
        )
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                text = if (progress.floatValue > 0f && progress.floatValue < 1f) "Keep holding…" else label,
                color = Color.White,
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}
