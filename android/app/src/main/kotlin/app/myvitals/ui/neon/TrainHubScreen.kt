package app.myvitals.ui.neon

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForwardIos
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Pool
import androidx.compose.material.icons.outlined.Terrain
import androidx.compose.material3.Icon
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.sync.StrengthWorkoutDetail
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import timber.log.Timber
import java.time.LocalDate

/**
 * Train — neon training hub. Mirrors web `Train.vue`: today's generated
 * strength plan summary (split focus + completed/total exercise ring) from
 * [BackendClient.strengthToday], a visual Strength/Cardio segment toggle, and
 * a bounded recent-activities feed from [BackendClient.activities] (limit 8).
 * Drills into the full workout + activity screens via [onOpen].
 *
 * onOpen routes: "workout/today", "workout/history", "workout/charts",
 * "workout/catalog", "activities", "activity/{source}/{sourceId}".
 *
 * Color intent mirrors the web tokens: strength/move = Lime, cardio/heart =
 * Cyan, trails/elevation = Amber.
 */
@Composable
fun TrainHubScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var activities by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    // Visual-only segment toggle, mirroring the web `segment` ref.
    var segment by remember { mutableStateOf(TrainSegment.STRENGTH) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) {
            loading = false
            return@LaunchedEffect
        }
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val workoutD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.strengthToday()
                        if (r.isSuccessful) r.body() else null
                    }.getOrNull()
                }
                val actsD = async(Dispatchers.IO) {
                    runCatching { api.activities(limit = 8) }.getOrDefault(emptyList())
                }
                workout = workoutD.await()
                activities = actsD.await()
            }
        }.onFailure { Timber.w(it, "train hub load failed") }
        loading = false
    }

    // ── Derived plan summary (mirrors the web computeds) ──────────────────
    val exercises = workout?.exercises ?: emptyList()
    val totalExercises: Int? = if (workout != null) exercises.size else null
    val doneExercises: Int = exercises.count { ex ->
        val target = ex.targetSets
        if (ex.sets.isEmpty() || target <= 0) return@count false
        val accounted = ex.sets.count { it.skipped || it.loggedAt != null }
        accounted >= target
    }
    val splitLabel = workout?.splitFocus?.let { titleCase(it) } ?: "Rest Day"
    val isRest = workout == null || workout!!.splitFocus.contains("rest", ignoreCase = true)
    val ringPct: Float = totalExercises?.takeIf { it > 0 }
        ?.let { (doneExercises.toFloat() / it).coerceIn(0f, 1f) } ?: 0f
    val ringLabel = if (totalExercises == null) "—" else "$doneExercises/$totalExercises"

    // This-week pill: activities started within the trailing 7 days.
    val weekCount = remember(activities) {
        val cutoff = LocalDate.now().minusDays(7).toString()
        activities.count { it.startAt >= cutoff }
    }

    NeonScreen(
        title = "Train",
        contentPadding = contentPadding,
        headerTrailing = {
            WeekChip(weekCount) { onOpen("activities") }
        },
    ) {
        // ── Strength / Cardio segment toggle (visual) ────────────────────
        Row(
            Modifier.fillMaxWidth().padding(bottom = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            SegmentPill(
                label = "Strength",
                selected = segment == TrainSegment.STRENGTH,
                modifier = Modifier.weight(1f),
            ) { segment = TrainSegment.STRENGTH }
            SegmentPill(
                label = "Cardio",
                selected = segment == TrainSegment.CARDIO,
                modifier = Modifier.weight(1f),
            ) { segment = TrainSegment.CARDIO }
        }

        // ── Today hero card ──────────────────────────────────────────────
        Caption("Today")
        Spacer(Modifier.height(11.dp))
        TodayHero(
            ringPct = ringPct,
            ringLabel = ringLabel,
            tag = if (isRest) "Today" else "${splitLabel} Day".takeIf {
                !splitLabel.endsWith("Day", ignoreCase = true)
            } ?: splitLabel,
            title = splitLabel,
            exerciseCount = totalExercises,
            ctaLabel = if (isRest) "View" else "Continue",
            loading = loading && workout == null,
            onClick = { onOpen("workout/today") },
        )

        // ── Recent activities feed ───────────────────────────────────────
        Spacer(Modifier.height(20.dp))
        Caption("Recent")
        Spacer(Modifier.height(11.dp))

        if (activities.isEmpty()) {
            ActivityPill(
                icon = Icons.AutoMirrored.Outlined.DirectionsRun,
                tone = NeonMV.Cyan,
                title = if (loading) "Loading…" else "No recent activity",
                sub = "Tap to open your feed",
                value = null,
                onClick = { onOpen("activities") },
            )
        } else {
            activities.forEach { a ->
                val cls = classify(a.type)
                ActivityPill(
                    icon = cls.icon,
                    tone = cls.tone,
                    title = a.name?.trim()?.takeIf { it.isNotEmpty() } ?: titleCase(a.type),
                    sub = activitySub(a),
                    value = activityValue(a, cls),
                    onClick = { onOpen("activity/${a.source}/${a.sourceId}") },
                )
                Spacer(Modifier.height(11.dp))
            }
        }

        // ── Footer links: history + charts + catalog ─────────────────────
        Spacer(Modifier.height(6.dp))
        LinkRow("Workout history", Icons.Outlined.History) { onOpen("workout/history") }
        Spacer(Modifier.height(11.dp))
        LinkRow("Workout charts", Icons.Outlined.BarChart) { onOpen("workout/charts") }
        Spacer(Modifier.height(11.dp))
        LinkRow("Exercise catalog", Icons.Outlined.FitnessCenter) { onOpen("workout/catalog") }

        Spacer(Modifier.height(24.dp))
    }
}

private enum class TrainSegment { STRENGTH, CARDIO }

// ── Header week chip ──────────────────────────────────────────────────────
@Composable
private fun WeekChip(count: Int, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .background(NeonMV.Lime.copy(alpha = 0.12f))
            .border(1.dp, NeonMV.Lime.copy(alpha = 0.25f), RoundedCornerShape(20.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "This week · ",
            color = NeonMV.Lime,
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
        )
        NeonNumber("$count", color = NeonMV.Lime, size = 13, weight = FontWeight.Bold)
    }
}

// ── Caption eyebrow (web `.cap`) ──────────────────────────────────────────
@Composable
private fun Caption(text: String) {
    Text(
        text.uppercase(),
        color = NeonMV.Muted,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.4.sp,
    )
}

// ── Segment toggle pill ───────────────────────────────────────────────────
@Composable
private fun SegmentPill(
    label: String,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(if (selected) NeonMV.Lime else NeonMV.Card)
            .then(
                if (selected)
                    Modifier.border(1.dp, NeonMV.Lime, RoundedCornerShape(16.dp))
                else Modifier,
            )
            .clickable(onClick = onClick)
            .padding(vertical = 11.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = if (selected) NeonMV.OnAccent else NeonMV.Muted,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}

// ── Today hero card ───────────────────────────────────────────────────────
@Composable
private fun TodayHero(
    ringPct: Float,
    ringLabel: String,
    tag: String,
    title: String,
    exerciseCount: Int?,
    ctaLabel: String,
    loading: Boolean,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp))
            .background(NeonMV.CardHigh)
            .border(1.dp, NeonMV.Lime.copy(alpha = 0.18f), RoundedCornerShape(24.dp))
            .clickable(onClick = onClick)
            .padding(18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        ProgressRing(pct = ringPct, label = ringLabel, color = NeonMV.Lime)
        Column(Modifier.weight(1f)) {
            Text(
                tag.uppercase(),
                color = NeonMV.Lime,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.4.sp,
                maxLines = 1,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                title,
                color = NeonMV.Ink,
                fontSize = 20.sp,
                fontWeight = FontWeight.ExtraBold,
                letterSpacing = (-0.3).sp,
                maxLines = 1,
            )
            Spacer(Modifier.height(5.dp))
            Text(
                when {
                    loading -> "Loading plan…"
                    exerciseCount == null -> "No plan today"
                    exerciseCount == 0 -> "Rest"
                    exerciseCount == 1 -> "1 exercise"
                    else -> "$exerciseCount exercises"
                },
                color = NeonMV.Muted,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(12.dp))
            // CTA pill — neon lime fill with glow border, mirroring web `.cont`.
            Row(
                modifier = Modifier
                    .clip(RoundedCornerShape(14.dp))
                    .background(NeonMV.Lime)
                    .border(1.dp, NeonMV.Lime.copy(alpha = 0.5f), RoundedCornerShape(14.dp))
                    .padding(horizontal = 16.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    ctaLabel,
                    color = NeonMV.OnAccent,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.ExtraBold,
                )
            }
        }
    }
}

// ── Hero progress ring ────────────────────────────────────────────────────
@Composable
private fun ProgressRing(pct: Float, label: String, color: Color) {
    Box(
        modifier = Modifier.size(84.dp),
        contentAlignment = Alignment.Center,
    ) {
        androidx.compose.foundation.Canvas(Modifier.size(84.dp)) {
            val stroke = 8.dp.toPx()
            val inset = stroke / 2f
            val arcSize = androidx.compose.ui.geometry.Size(
                size.width - stroke, size.height - stroke,
            )
            val topLeft = androidx.compose.ui.geometry.Offset(inset, inset)
            drawArc(
                color = NeonMV.Track,
                startAngle = -90f, sweepAngle = 360f, useCenter = false,
                topLeft = topLeft, size = arcSize,
                style = androidx.compose.ui.graphics.drawscope.Stroke(width = stroke),
            )
            if (pct > 0f) {
                drawArc(
                    color = color,
                    startAngle = -90f, sweepAngle = 360f * pct, useCenter = false,
                    topLeft = topLeft, size = arcSize,
                    style = androidx.compose.ui.graphics.drawscope.Stroke(
                        width = stroke,
                        cap = androidx.compose.ui.graphics.StrokeCap.Round,
                    ),
                )
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            NeonNumber(label, color = color, size = 20, weight = FontWeight.Bold)
            Text(
                "DONE",
                color = NeonMV.Muted,
                fontSize = 9.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp,
            )
        }
    }
}

// ── Recent-activity pill row ──────────────────────────────────────────────
@Composable
private fun ActivityPill(
    icon: ImageVector,
    tone: Color,
    title: String,
    sub: String,
    value: String?,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonPillShape)
            .background(NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape)
                .background(tone.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = tone, modifier = Modifier.size(20.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(
                title,
                color = NeonMV.Ink,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                sub,
                color = NeonMV.Muted,
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
            )
        }
        if (value != null) {
            NeonNumber(value, color = tone, size = 14, weight = FontWeight.Bold)
            Spacer(Modifier.width(4.dp))
        }
        Icon(
            Icons.AutoMirrored.Outlined.ArrowForwardIos,
            contentDescription = null,
            tint = NeonMV.Muted,
            modifier = Modifier.size(12.dp),
        )
    }
}

// ── Footer navigation link row ────────────────────────────────────────────
@Composable
private fun LinkRow(label: String, icon: ImageVector, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .border(1.dp, NeonMV.Line, RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(icon, contentDescription = null, tint = NeonMV.Muted, modifier = Modifier.size(18.dp))
        Text(
            label,
            color = NeonMV.Muted,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(1f),
        )
        Icon(
            Icons.AutoMirrored.Outlined.ArrowForwardIos,
            contentDescription = null,
            tint = NeonMV.Muted,
            modifier = Modifier.size(12.dp),
        )
    }
}

// ── Activity classification (mirrors web `classifyType`) ──────────────────
private data class ActivityClass(val icon: ImageVector, val tone: Color, val isTrail: Boolean)

private fun classify(type: String?): ActivityClass {
    val t = (type ?: "").lowercase()
    val isStrength = t.contains("strength") || t.contains("weight") || t.contains("workout")
    val isTrail = t.contains("trail") || t.contains("hike")
    return when {
        isStrength -> ActivityClass(Icons.Outlined.FitnessCenter, NeonMV.Lime, false)
        isTrail -> ActivityClass(Icons.Outlined.Terrain, NeonMV.Amber, true)
        t.contains("ride") || t.contains("bike") || t.contains("cycl") ->
            ActivityClass(Icons.AutoMirrored.Outlined.DirectionsBike, NeonMV.Cyan, false)
        t.contains("swim") -> ActivityClass(Icons.Outlined.Pool, NeonMV.Cyan, false)
        else -> ActivityClass(Icons.AutoMirrored.Outlined.DirectionsRun, NeonMV.Cyan, false)
    }
}

// ── Sub-line: relative day · distance (or type) ───────────────────────────
private fun activitySub(a: ActivityRow): String {
    val parts = mutableListOf(relDay(a.startAt))
    val mi = milesOrNull(a.distanceM)
    if (mi != null) parts.add(mi) else parts.add(titleCase(a.type))
    return parts.filter { it.isNotBlank() }.joinToString(" · ")
}

// ── Primary value: elevation (ft) for trail rows, else duration (h:mm) ────
private fun activityValue(a: ActivityRow, cls: ActivityClass): String {
    if (cls.isTrail) {
        val ft = a.elevationGainM?.takeIf { it > 0 }?.let { (it * 3.28084).toInt() }
        if (ft != null) return "%,d ft".format(ft)
    }
    return hms(a.durationS)
}

private fun milesOrNull(distanceM: Double?): String? {
    if (distanceM == null || distanceM <= 0) return null
    return "%.1f mi".format(distanceM / 1609.344)
}

private fun hms(durationS: Int?): String {
    if (durationS == null || durationS <= 0) return "—"
    val h = durationS / 3600
    val m = (durationS % 3600) / 60
    return if (h > 0) "%d:%02d".format(h, m)
    else "%d:%02d".format(m, durationS % 60)
}

private fun relDay(iso: String?): String {
    if (iso.isNullOrBlank()) return "—"
    return runCatching {
        val date = LocalDate.parse(iso.substring(0, 10))
        val today = LocalDate.now()
        val diff = today.toEpochDay() - date.toEpochDay()
        when {
            diff <= 0L -> "Today"
            diff == 1L -> "Yesterday"
            diff < 7L -> date.dayOfWeek.name.lowercase().replaceFirstChar { it.uppercase() }.take(3)
            else -> "%s %d".format(
                date.month.name.lowercase().replaceFirstChar { it.uppercase() }.take(3),
                date.dayOfMonth,
            )
        }
    }.getOrDefault("—")
}

private fun titleCase(s: String): String =
    s.replace(Regex("[_-]+"), " ")
        .split(" ")
        .filter { it.isNotBlank() }
        .joinToString(" ") { it.replaceFirstChar { c -> c.uppercase() } }
