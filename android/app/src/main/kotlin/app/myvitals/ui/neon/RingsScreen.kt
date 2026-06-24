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
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        runCatching {
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
                val fastingD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.fastingCurrent()
                        if (r.isSuccessful) r.body() else null
                    }.getOrNull()
                }
                summary = summaryD.await()
                profile = profileD.await()
                sober = soberD.await()
                fasting = fastingD.await()
            }
        }
        loading = false
    }

    val sleepScore = summary?.sleepScore
    val recoveryScore = summary?.recoveryScore
    val steps = summary?.stepsTotal
    val stepGoal = profile?.stepsGoal() ?: 10_000
    val movePct: Float = if (steps != null && stepGoal > 0)
        min(100f, (steps.toFloat() / stepGoal.toFloat()) * 100f) else 0f
    val stepsToGoal: Int? = if (steps != null) max(0, stepGoal - steps) else null

    NeonScreen(title = "Today", contentPadding = contentPadding) {
        if (loading && summary == null) {
            Text(
                "Loading…",
                color = NeonMV.Muted,
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 8.dp, bottom = 8.dp),
            )
        }

        // ---- Goal rings ----
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 4.dp, bottom = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            GoalRing(
                label = "SLEEP",
                pct = (sleepScore ?: 0.0).toFloat(),
                valueText = sleepScore?.let { "${it.roundToInt()}" } ?: "—",
                showPercent = sleepScore != null,
                glyph = "☾",
                color = NeonMV.Magenta,
                onClick = { onOpen("vitals/SLEEP") },
                modifier = Modifier.weight(1f),
            )
            GoalRing(
                label = "MOVE",
                pct = movePct,
                valueText = if (steps != null) "${movePct.roundToInt()}" else "—",
                showPercent = steps != null,
                glyph = "🏃",
                color = NeonMV.Lime,
                onClick = { onOpen("vitals/STEPS") },
                modifier = Modifier.weight(1f),
            )
            GoalRing(
                label = "RECOVERY",
                pct = (recoveryScore ?: 0.0).toFloat(),
                valueText = recoveryScore?.let { "${it.roundToInt()}" } ?: "—",
                showPercent = recoveryScore != null,
                glyph = "♥",
                color = NeonMV.Cyan,
                onClick = { onOpen("vitals/HR") },
                modifier = Modifier.weight(1f),
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

        // ---- Streaks & goals ----
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            val fastH = fasting?.takeIf { it.isActive }?.elapsedH
            val fastTarget = fasting?.targetHours ?: 16.0
            PillRow(
                glyph = "⏱",
                accent = NeonMV.Cyan,
                name = "Fasting",
                onClick = { onOpen("fasting") },
            ) {
                NeonNumber(
                    fastH?.let { "${it.roundToInt()}" } ?: "—",
                    color = NeonMV.Ink,
                    size = 15,
                )
                Text(
                    " / ${fastTarget.roundToInt()}h",
                    color = NeonMV.Muted,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                )
                if (fastH != null && fastH >= fastTarget) {
                    Spacer(Modifier.width(6.dp))
                    Text("✓", color = NeonMV.Lime, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                }
            }

            val soberDays = sober?.days
            PillRow(
                glyph = "🔥",
                accent = NeonMV.Magenta,
                name = "Sober",
                onClick = { onOpen("sober") },
            ) {
                NeonNumber(
                    soberDays?.let { "$it" } ?: "—",
                    color = NeonMV.Magenta,
                    size = 15,
                )
                Text(" days", color = NeonMV.Muted, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            }

            PillRow(
                glyph = "👟",
                accent = NeonMV.Lime,
                name = "Steps",
                onClick = { onOpen("vitals/STEPS") },
            ) {
                NeonNumber(
                    steps?.let { "%,d".format(it) } ?: "—",
                    color = NeonMV.Lime,
                    size = 15,
                )
                Text(
                    " / ${"%,d".format(stepGoal)}",
                    color = NeonMV.Muted,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                )
            }

            PillRow(
                glyph = "🏋",
                accent = NeonMV.Cyan,
                name = "Workout",
                onClick = { onOpen("workout/today") },
            ) {
                Text(
                    "Today's plan",
                    color = NeonMV.Muted,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.width(4.dp))
                Text("›", color = NeonMV.Muted, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            }
        }

        // ---- Move-ring nudge — headline scales with how close you are, so it
        // no longer says "Almost there!" at 0 steps. Hidden on a cold fetch
        // (steps == null) and once the goal is hit (stepsToGoal == 0). ----
        if (steps != null && stepsToGoal != null && stepsToGoal > 0) {
            AlmostThereCta(
                headline = when {
                    movePct >= 75f -> "Almost there!"
                    movePct >= 40f -> "Keep it up"
                    else -> "Let's get moving"
                },
                stepsToGoal = stepsToGoal,
                onClick = { onOpen("vitals/STEPS") },
            )
        }

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

@Composable
private fun AlmostThereCta(headline: String, stepsToGoal: Int, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 18.dp)
            .clip(NeonPillShape)
            .background(
                Brush.horizontalGradient(
                    listOf(NeonMV.Lime.copy(alpha = 0.22f), NeonMV.Lime.copy(alpha = 0.05f)),
                ),
            )
            .border(1.dp, NeonMV.Lime.copy(alpha = 0.30f), NeonPillShape)
            .clickable(onClick = onClick)
            .padding(20.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                headline,
                color = NeonMV.Ink,
                fontSize = 20.sp,
                fontWeight = FontWeight.ExtraBold,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                "${"%,d".format(stepsToGoal)} steps to close your Move ring",
                color = NeonMV.Lime,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        Spacer(Modifier.width(14.dp))
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(CircleShape)
                .background(NeonMV.Lime),
            contentAlignment = Alignment.Center,
        ) {
            Text("→", color = NeonMV.OnAccent, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        }
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
