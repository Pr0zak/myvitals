package app.myvitals.ui.neon

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.shape.RoundedCornerShape
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
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Neon Refined (A1) home — the phone mirror of web `RingsRefined.vue`.
 *
 * A concentric tri-ring hero (Recovery cyan outer / Move lime middle / Sleep
 * magenta inner), a legend, real vitals tiles for whatever DailySummary fields
 * exist, Sober + Fasting streak cards, and a today's-workout pill. Same data
 * fetches + tap routes as [RingsScreen]; rendered by [NeonAppShell] when the
 * "Neon Refined home" toggle is on.
 *
 * onOpen routes: "vitals/HR" (recovery), "vitals/STEPS", "vitals/SLEEP",
 * "vitals/HRV", "vitals/SKIN_TEMP", "vitals/WEIGHT", "sober", "fasting",
 * "workout/today".
 */
@Composable
fun RefinedRingsScreen(
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

    val recoveryScore = summary?.recoveryScore
    val sleepScore = summary?.sleepScore
    val steps = summary?.stepsTotal
    val stepGoal = profile?.stepsGoal() ?: 10_000
    val movePct: Float = if (steps != null && stepGoal > 0)
        min(100f, (steps.toFloat() / stepGoal.toFloat()) * 100f) else 0f

    NeonScreen(title = "Today", contentPadding = contentPadding) {
        if (loading && summary == null) {
            Text(
                "Loading…",
                color = NeonMV.Muted,
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 8.dp, bottom = 8.dp),
            )
        }

        // ---- Hero: concentric tri-ring ----
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(NeonCardShape)
                .background(NeonMV.Card)
                .clickable { onOpen("vitals/HR") }
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(148.dp)
                    .aspectRatio(1f),
                contentAlignment = Alignment.Center,
            ) {
                TriRing(
                    recoveryPct = (recoveryScore ?: 0.0).toFloat(),
                    movePct = movePct,
                    sleepPct = (sleepScore ?: 0.0).toFloat(),
                    modifier = Modifier.size(148.dp),
                )
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    NeonNumber(
                        recoveryScore?.let { "${it.roundToInt()}" } ?: "—",
                        color = NeonMV.Ink,
                        size = 40,
                    )
                    Text(
                        "RECOVERY",
                        color = NeonMV.Muted,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.6.sp,
                        modifier = Modifier.padding(top = 3.dp),
                    )
                }
            }

            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                LegendRow(
                    dot = NeonMV.Cyan,
                    label = "Recovery",
                    value = recoveryScore?.let { "${it.roundToInt()}" } ?: "—",
                )
                LegendRow(
                    dot = NeonMV.Lime,
                    label = "Move · steps",
                    value = steps?.let { "%,d".format(it) } ?: "—",
                    sub = "/ ${"%,d".format(stepGoal)}",
                )
                LegendRow(
                    dot = NeonMV.Magenta,
                    label = "Sleep score",
                    value = sleepScore?.let { "${it.roundToInt()}" } ?: "—",
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        // ---- Vitals tiles — only for DailySummary fields that exist ----
        val tiles = buildList {
            summary?.hrvAvg?.let { add(VitalsTile("HRV", "${it.roundToInt()}", "ms", "vitals/HRV")) }
            summary?.restingHr?.let { add(VitalsTile("RESTING HR", "${it.roundToInt()}", "bpm", "vitals/HR")) }
            summary?.skinTempDeltaAvg?.let {
                val s = (if (it > 0) "+" else "") + "%.1f".format(it)
                add(VitalsTile("SKIN TEMP", s, "°C", "vitals/SKIN_TEMP"))
            }
            summary?.readinessScore?.let { add(VitalsTile("READINESS", "${it.roundToInt()}", null, "vitals/HR")) }
            summary?.weightKg?.let {
                add(VitalsTile("WEIGHT", "%.1f".format(it * 2.2046226), "lb", "vitals/WEIGHT"))
            }
            summary?.bodyFatPct?.let { add(VitalsTile("BODY FAT", "%.1f".format(it), "%", "vitals/WEIGHT")) }
        }
        if (tiles.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                tiles.chunked(2).forEach { pair ->
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        pair.forEach { t ->
                            VitalsTileCard(t, onClick = { onOpen(t.route) }, modifier = Modifier.weight(1f))
                        }
                        if (pair.size == 1) Spacer(Modifier.weight(1f))
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
        }

        // ---- Streaks: Sober + Fasting ----
        val soberDays = sober?.days
        StreakCard(
            glyph = "✦",
            accent = NeonMV.Magenta,
            label = "Sober",
            onClick = { onOpen("sober") },
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(soberDays?.let { "$it" } ?: "—", color = NeonMV.Ink, size = 22)
                Text(
                    " days",
                    color = NeonMV.Muted,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 2.dp),
                )
            }
        }

        Spacer(Modifier.height(9.dp))

        val activeFast = fasting?.takeIf { it.isActive }
        val fastH = activeFast?.elapsedH
        val fastTarget = fasting?.targetHours ?: 16.0
        val fastPct: Float = if (fastH != null && fastTarget > 0)
            min(100f, (fastH.toFloat() / fastTarget.toFloat()) * 100f) else 0f
        val fastStage = activeFast?.currentStage
        StreakCard(
            glyph = "◔",
            accent = NeonMV.Amber,
            label = if (fastStage != null) "Fasting · $fastStage" else "Fasting",
            onClick = { onOpen("fasting") },
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(
                    fastH?.let { "%.1f".format(it) } ?: "—",
                    color = NeonMV.Ink,
                    size = 22,
                )
                Text(
                    "h / ${fastTarget.roundToInt()}h",
                    color = NeonMV.Muted,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 2.dp),
                )
            }
            Spacer(Modifier.height(7.dp))
            ProgressBar(pct = fastPct, color = NeonMV.Amber)
        }

        Spacer(Modifier.height(12.dp))

        // ---- Today's workout pill ----
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(NeonPillShape)
                .background(NeonMV.Card)
                .clickable { onOpen("workout/today") }
                .padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(42.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(NeonMV.Cyan.copy(alpha = 0.14f)),
                contentAlignment = Alignment.Center,
            ) {
                Text("🏋", color = NeonMV.Cyan, fontSize = 19.sp)
            }
            Spacer(Modifier.width(13.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "Today's workout",
                    color = NeonMV.Ink,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Tap to open today's plan",
                    color = NeonMV.Muted,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            Text("›", color = NeonMV.Muted, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        }

        Spacer(Modifier.height(24.dp))
    }
}

private data class VitalsTile(
    val key: String,
    val value: String,
    val unit: String?,
    val route: String,
)

@Composable
private fun VitalsTileCard(
    tile: VitalsTile,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(13.dp))
            .background(NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 10.dp),
    ) {
        Text(
            tile.key,
            color = NeonMV.Muted,
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 0.4.sp,
        )
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            NeonNumber(tile.value, color = NeonMV.Ink, size = 19)
            tile.unit?.let {
                Text(
                    it,
                    color = NeonMV.Muted,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(start = 1.dp, bottom = 2.dp),
                )
            }
        }
    }
}

@Composable
private fun LegendRow(
    dot: Color,
    label: String,
    value: String,
    sub: String? = null,
) {
    Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Box(
            modifier = Modifier
                .padding(top = 5.dp)
                .size(8.dp)
                .clip(CircleShape)
                .background(dot),
        )
        Column {
            Text(
                label.uppercase(),
                color = NeonMV.Muted,
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 0.3.sp,
            )
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(value, color = NeonMV.Ink, size = 18)
                sub?.let {
                    Text(
                        " $it",
                        color = NeonMV.Muted,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier.padding(bottom = 2.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun StreakCard(
    glyph: String,
    accent: Color,
    label: String,
    onClick: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(15.dp))
            .background(NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(accent.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Text(glyph, color = accent, fontSize = 16.sp)
        }
        Spacer(Modifier.width(11.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                label,
                color = NeonMV.Muted,
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(1.dp))
            content()
        }
    }
}

@Composable
private fun ProgressBar(pct: Float, color: Color) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(4.dp)
            .clip(RoundedCornerShape(4.dp))
            .background(NeonMV.Track),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(pct.coerceIn(0f, 100f) / 100f)
                .height(4.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(color),
        )
    }
}

/**
 * Concentric tri-ring: Recovery (cyan, outer), Move (lime, middle), Sleep
 * (magenta, inner). Each arc is swept by its own percentage. Mirrors the web
 * SVG in RingsRefined.vue (r = 52 / 41 / 30 on a 120 viewport).
 */
@Composable
private fun TriRing(
    recoveryPct: Float,
    movePct: Float,
    sleepPct: Float,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier) {
        val stroke = size.minDimension * 0.075f
        val gap = stroke * 1.35f
        // Outer radius ratio, stepping inward by (stroke + gap) each ring.
        val outer = size.minDimension / 2f - stroke / 2f - size.minDimension * 0.02f
        val radii = listOf(outer, outer - (stroke + gap), outer - 2f * (stroke + gap))
        val colors = listOf(NeonMV.Cyan, NeonMV.Lime, NeonMV.Magenta)
        val pcts = listOf(recoveryPct, movePct, sleepPct)
        val center = Offset(size.width / 2f, size.height / 2f)

        radii.forEachIndexed { i, r ->
            if (r <= 0f) return@forEachIndexed
            val topLeft = Offset(center.x - r, center.y - r)
            val arcSize = Size(r * 2f, r * 2f)
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
            val sweep = pcts[i].coerceIn(0f, 100f) / 100f * 360f
            if (sweep <= 0f) return@forEachIndexed
            drawArc(
                color = colors[i],
                startAngle = -90f,
                sweepAngle = sweep,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
        }
    }
}
