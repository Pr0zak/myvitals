package app.myvitals.ui.neon

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
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForwardIos
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.automirrored.outlined.FormatListBulleted
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.Event
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.UpcomingDay
import app.myvitals.ui.MV
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
    val neon = settings.neonShellEnabled

    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var activities by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var upcoming by remember { mutableStateOf<List<UpcomingDay>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    // Selected activity filter — `null` = All. Client-side substring match on
    // ActivityRow.type against the already-loaded list (the screen now loads a
    // wide range). Mirrors the web Activities filter chips for parity.
    var filter by remember { mutableStateOf<ActivityFilter?>(null) }

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
                    // Load a wide range so the filter chips have something to
                    // bite on — filtering is client-side over this list.
                    runCatching { api.activities(limit = 100) }.getOrDefault(emptyList())
                }
                // Read-only schedule forecast → "Next session" card.
                val upcomingD = async(Dispatchers.IO) {
                    runCatching { api.upcomingWorkouts().upcoming }.getOrDefault(emptyList())
                }
                workout = workoutD.await()
                activities = actsD.await()
                upcoming = upcomingD.await()
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

    // This-week pill: activities started within the trailing 7 days. Counts
    // the full (unfiltered) list — the pill is a global stat, not filtered.
    val weekCount = remember(activities) {
        val cutoff = LocalDate.now().minusDays(7).toString()
        activities.count { it.startAt >= cutoff }
    }

    // Which filter chips actually have matches in the loaded list — never show
    // a chip that would yield an empty feed. "All" is always present.
    val availableFilters = remember(activities) {
        ActivityFilter.entries.filter { f -> activities.any { f.matches(it.type) } }
    }
    // The visible feed: filtered (client-side) then capped to a sane count so
    // the page stays a "recent" hub, not an unbounded scroll.
    val shown = remember(activities, filter) {
        val f = filter
        val base = if (f == null) activities else activities.filter { f.matches(it.type) }
        base.take(25)
    }

    NeonScreen(
        title = "Train",
        contentPadding = contentPadding,
        headerTrailing = {
            WeekChip(weekCount) { onOpen("activities") }
        },
    ) {
        // ── Today hero card (with the next sessions as a week-timeline strip) ──
        Caption("Today")
        Spacer(Modifier.height(11.dp))
        val nextSessions = remember(upcoming) { upcoming.filter { !it.isToday }.take(3) }
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
            upcoming = nextSessions,
            onClick = { onOpen("workout/today") },
        )

        // ── Recent activities feed ───────────────────────────────────────
        Spacer(Modifier.height(20.dp))
        CaptionRow("Recent") {
            // Cheap "See all" affordance — only worth showing once there's a
            // feed to open into. Routes to the same full activity list as the
            // footer "All activities" link.
            if (activities.isNotEmpty()) {
                SeeAll { onOpen("activities") }
            }
        }
        Spacer(Modifier.height(11.dp))

        // ── Filter bar — theme-aware chip row (web parity) ───────────────
        // Only render once there's a feed to filter and at least one non-All
        // category present. Selected chip: neon → Cyan, classic → BrandRed.
        if (availableFilters.size > 1) {
            FilterBar(
                available = availableFilters,
                selected = filter,
                neon = neon,
                onSelect = { filter = it },
            )
            Spacer(Modifier.height(11.dp))
        }

        if (activities.isEmpty()) {
            ActivityPill(
                icon = Icons.AutoMirrored.Outlined.DirectionsRun,
                tone = NeonMV.Cyan,
                title = if (loading) "Loading…" else "No recent activity",
                sub = "Tap to open your feed",
                value = null,
                onClick = { onOpen("activities") },
            )
        } else if (shown.isEmpty()) {
            // Filtered to empty — keep the chips visible above and explain why.
            ActivityPill(
                icon = Icons.AutoMirrored.Outlined.FormatListBulleted,
                tone = NeonMV.Muted,
                title = "No ${filter?.label ?: "matching"} activities",
                sub = "Tap to open the full feed",
                value = null,
                onClick = { onOpen("activities") },
            )
        } else {
            shown.forEach { a ->
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

        // ── Footer links: all activities + history + charts + catalog ────
        // "All activities" is the FIRST link — the full activity feed used to
        // be reachable only via the disguised "This week · N" header chip,
        // which read as a stat, not a button. An explicit list LinkRow makes
        // the whole feed discoverable (web-dashboard parity).
        Spacer(Modifier.height(6.dp))
        LinkRow("All activities", Icons.AutoMirrored.Outlined.FormatListBulleted) { onOpen("activities") }
        Spacer(Modifier.height(11.dp))
        LinkRow("Workout history", Icons.Outlined.History) { onOpen("workout/history") }
        Spacer(Modifier.height(11.dp))
        LinkRow("Workout charts", Icons.Outlined.BarChart) { onOpen("workout/charts") }
        Spacer(Modifier.height(11.dp))
        LinkRow("Exercise catalog", Icons.Outlined.FitnessCenter) { onOpen("workout/catalog") }

        Spacer(Modifier.height(24.dp))
    }
}

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

/**
 * Caption eyebrow with an optional trailing action (e.g. a "See all" link)
 * pushed to the right edge. Used for the "Recent" header so the full activity
 * feed has a clear inline affordance, not just the footer link.
 */
@Composable
private fun CaptionRow(text: String, trailing: @Composable () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Caption(text)
        trailing()
    }
}

/** Small cyan "See all" text + chevron affordance. */
@Composable
private fun SeeAll(onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 4.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(
            "See all",
            color = NeonMV.Cyan,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 0.6.sp,
        )
        Icon(
            Icons.AutoMirrored.Outlined.ArrowForwardIos,
            contentDescription = null,
            tint = NeonMV.Cyan,
            modifier = Modifier.size(9.dp),
        )
    }
}

// ── Activity filter categories (web Activities parity) ────────────────────
// Each chip matches ActivityRow.type by case-insensitive substring. Keep the
// keyword sets aligned with the web ActivityIcon classifier + the planner's
// manual_cardio / elliptical generic-cardio bucket.
private enum class ActivityFilter(val label: String, val keywords: List<String>) {
    Ride("Ride", listOf("ride", "cycl", "bike", "vr")),
    Run("Run", listOf("run")),
    Walk("Walk", listOf("walk")),
    Hike("Hike", listOf("hike")),
    Row("Row", listOf("row")),
    Ski("Ski", listOf("ski")),
    Cardio("Cardio", listOf("manual_cardio", "elliptical", "cardio")),
    ;

    fun matches(type: String?): Boolean {
        val t = (type ?: "").lowercase()
        return keywords.any { t.contains(it) }
    }
}

// ── Theme-aware filter chip row ───────────────────────────────────────────
@Composable
private fun FilterBar(
    available: List<ActivityFilter>,
    selected: ActivityFilter?,
    neon: Boolean,
    onSelect: (ActivityFilter?) -> Unit,
) {
    // Selected-chip accent: neon shell → Cyan, classic shell → brand red. The
    // chip bar is a NEW control so it's fine in both shells; only the accent
    // colour flips so it reads native to whichever theme is active.
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FilterChip(label = "All", active = selected == null, accent = accent) { onSelect(null) }
        available.forEach { f ->
            FilterChip(label = f.label, active = selected == f, accent = accent) {
                // Tapping the active chip again clears back to All.
                onSelect(if (selected == f) null else f)
            }
        }
    }
}

@Composable
private fun FilterChip(
    label: String,
    active: Boolean,
    accent: Color,
    onClick: () -> Unit,
) {
    val bg = if (active) accent.copy(alpha = 0.16f) else NeonMV.Card
    val border = if (active) accent.copy(alpha = 0.5f) else NeonMV.Line
    val ink = if (active) accent else NeonMV.Muted
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(18.dp))
            .background(bg)
            .border(1.dp, border, RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            color = ink,
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 0.3.sp,
            maxLines = 1,
        )
    }
}

/** "SAT" / "TMRW" / "9D" — compact day label for the timeline strip. */
private fun shortDay(iso: String): String = try {
    val d = java.time.LocalDate.parse(iso)
    val days = java.time.temporal.ChronoUnit.DAYS.between(java.time.LocalDate.now(), d)
    when {
        days == 1L -> "TMRW"
        days in 0..6 -> d.dayOfWeek.getDisplayName(
            java.time.format.TextStyle.SHORT, java.util.Locale.getDefault()).uppercase()
        else -> "${days}D"
    }
} catch (e: Exception) { "SOON" }

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
    upcoming: List<UpcomingDay>,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp))
            .background(NeonMV.CardHigh)
            .border(1.dp, NeonMV.Lime.copy(alpha = 0.18f), RoundedCornerShape(24.dp))
            .clickable(onClick = onClick)
            .padding(18.dp),
    ) {
        // ── Today ──
        Row(
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

        // ── Week-timeline strip: the next sessions, inside the same bubble ──
        if (upcoming.isNotEmpty()) {
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                upcoming.forEach { s ->
                    val lead = s === upcoming.first()
                    Column(
                        modifier = Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(14.dp))
                            .background(NeonMV.Card)
                            .border(
                                1.dp,
                                if (lead) NeonMV.Lime.copy(alpha = 0.30f) else NeonMV.Track,
                                RoundedCornerShape(14.dp),
                            )
                            .padding(horizontal = 11.dp, vertical = 10.dp),
                    ) {
                        Text(
                            shortDay(s.date),
                            color = if (lead) NeonMV.Lime else NeonMV.Periwinkle,
                            fontFamily = NeonNumberFamily,
                            fontSize = 10.sp, fontWeight = FontWeight.Bold,
                            letterSpacing = 0.8.sp, maxLines = 1,
                        )
                        Spacer(Modifier.height(3.dp))
                        Text(
                            titleCase(s.splitFocus),
                            color = NeonMV.Ink, fontSize = 14.sp, fontWeight = FontWeight.Bold,
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        if (s.exerciseCount > 0) {
                            Spacer(Modifier.height(2.dp))
                            Text("${s.exerciseCount} ex", color = NeonMV.Muted, fontSize = 11.sp)
                        }
                    }
                }
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
