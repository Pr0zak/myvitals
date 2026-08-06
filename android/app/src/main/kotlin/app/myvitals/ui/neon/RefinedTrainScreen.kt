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
import androidx.compose.material.icons.outlined.FitnessCenter
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import timber.log.Timber
import java.time.LocalDate

/**
 * Neon Refined (A1) Train tab — the phone mirror of web `TrainRefined.vue`.
 *
 * A today's-workout HERO card (split focus → "<Cap> day", exercise count, an
 * amber deload note when the plan's load was eased, a cyan Start/View CTA) over
 * a bounded "Recent" activities feed (icon + name + relative day + duration or
 * distance). Same data source + tap routes as [TrainHubScreen] (which it
 * replaces when the "Neon Refined home" toggle is on, wired in [NeonAppShell]).
 *
 * onOpen routes: "workout/today", "activities".
 */
@Composable
fun RefinedTrainScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var activities by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var yearWorkouts by remember {
        mutableStateOf<List<app.myvitals.sync.StrengthWorkoutSummary>>(emptyList())
    }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) {
            loading = false
            return@LaunchedEffect
        }
        // SWR: paint last-known year data before the (now much larger)
        // fetch runs, so switching to Train never shows an empty calendar.
        app.myvitals.data.JsonCache.read<List<ActivityRow>>(
            ctx, CACHE_YEAR_ACTS,
            app.myvitals.data.JsonCache.listType(ActivityRow::class.java),
        )?.value?.let { if (it.isNotEmpty()) { activities = it; loading = false } }
        app.myvitals.data.JsonCache.read<List<app.myvitals.sync.StrengthWorkoutSummary>>(
            ctx, CACHE_YEAR_WKS,
            app.myvitals.data.JsonCache.listType(
                app.myvitals.sync.StrengthWorkoutSummary::class.java,
            ),
        )?.value?.let { if (it.isNotEmpty()) yearWorkouts = it }
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val workoutD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.strengthToday()
                        if (r.isSuccessful) r.body() else null
                    }.getOrNull()
                }
                // Widened from limit=6: the YTD pair and the year calendar
                // need the whole of this year and the same span of last year
                // for the comparison. `recent` is derived from the same list,
                // so this is one fetch, not two.
                val actsD = async(Dispatchers.IO) {
                    runCatching {
                        api.activities(limit = 2000, since = ytdSince())
                    }.getOrDefault(emptyList())
                }
                val wkD = async(Dispatchers.IO) {
                    runCatching {
                        api.strengthWorkouts().workouts
                            .filter {
                                it.status != "regenerated" && it.status != "planned" &&
                                    it.status != "skipped"
                            }
                            // Cardio days auto-completed by an Activity are
                            // already in the feed — counting both double-counts.
                            .filter {
                                !(it.splitFocus == "cardio" &&
                                    it.completedByActivitySource != null)
                            }
                    }.getOrDefault(emptyList())
                }
                workout = workoutD.await()
                val freshActs = actsD.await()
                val freshWks = wkD.await()
                if (freshActs.isNotEmpty()) {
                    activities = freshActs
                    app.myvitals.data.JsonCache.write(
                        ctx, CACHE_YEAR_ACTS,
                        app.myvitals.data.JsonCache.listType(ActivityRow::class.java),
                        freshActs,
                    )
                }
                if (freshWks.isNotEmpty()) {
                    yearWorkouts = freshWks
                    app.myvitals.data.JsonCache.write(
                        ctx, CACHE_YEAR_WKS,
                        app.myvitals.data.JsonCache.listType(
                            app.myvitals.sync.StrengthWorkoutSummary::class.java,
                        ),
                        freshWks,
                    )
                }
            }
        }.onFailure { Timber.w(it, "refined train load failed") }
        loading = false
    }

    // ── Hero copy (mirrors the web computeds) ─────────────────────────────
    val w = workout
    val splitFocus = w?.splitFocus
    val workoutTitle = if (splitFocus == null) "No workout planned"
    else "${titleCaseRefined(splitFocus)} day"
    val exCount = w?.exercises?.size ?: 0
    val workoutSub = when {
        w == null -> "Tap to generate today's plan"
        exCount == 1 -> "1 exercise"
        else -> "$exCount exercises"
    }
    val deloadNote: String? = w?.deloadFactor?.takeIf { it < 1.0 }?.let {
        "Load eased ${Math.round((1 - it) * 100)}% for recovery"
    }
    val workoutDone = w?.status == "completed"
    val ctaLabel = when {
        w == null -> "Generate plan"
        workoutDone -> "View workout"
        else -> "Start workout"
    }

    // ── Recent feed (bounded, client-side classify) ───────────────────────
    val recent = remember(activities) {
        activities.sortedByDescending { it.startAt }.take(6)
    }
    val ytd = remember(activities, yearWorkouts) {
        app.myvitals.ui.common.computeYtdComparison(activities, yearWorkouts)
    }
    val calYear = remember { java.time.LocalDate.now().year }
    val calIndex = remember(activities, yearWorkouts, calYear) {
        app.myvitals.ui.common.buildActivityCalendarIndex(activities, yearWorkouts, calYear)
    }
    val totalCount = activities.size + yearWorkouts.size

    NeonScreen(title = "Train", contentPadding = contentPadding) {
        // ── Today's workout hero ──
        Caption("Today")
        Spacer(Modifier.height(11.dp))
        HeroCard(
            title = workoutTitle,
            sub = if (loading && w == null) "Loading plan…" else workoutSub,
            deloadNote = deloadNote,
            ctaLabel = ctaLabel,
            onClick = { onOpen("workout/today") },
        )

        // ── This year ──
        // Same numbers as the Activities screen: both call
        // common.computeYtdComparison, so the two can't disagree.
        Spacer(Modifier.height(18.dp))
        Caption("This year")
        Spacer(Modifier.height(11.dp))
        app.myvitals.ui.common.YtdStatPair(
            cmp = ytd, neon = true, onClick = { onOpen("activities") },
        )

        // ── Activity calendar ──
        // Colour-coded per activity type (Strength / Yoga / Ride / Run /
        // Walk / Row), sharing ui/common/ActivityCalendar.kt with the
        // Activities screen so the palette can't drift between them.
        if (calIndex.isNotEmpty()) {
            Spacer(Modifier.height(18.dp))
            Caption("Activity calendar")
            Spacer(Modifier.height(11.dp))
            app.myvitals.ui.common.ActivityCalendarCard(
                rows = activities, workouts = yearWorkouts,
                neon = true, year = calYear, title = null,
            )
        }

        // ── Recent activities ──
        // The rows now drill into their own activity, so the full feed needs
        // a real entry point rather than riding on a mis-wired row tap.
        Spacer(Modifier.height(18.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Caption("Recent")
            if (recent.isNotEmpty()) {
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .clickable { onOpen("activities") }
                        .padding(horizontal = 6.dp, vertical = 3.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        // Deliberately no count: the destination applies its
                        // own 90d default filter, so any number printed here
                        // ("See all 291") is contradicted on arrival ("47 shown").
                        "See all",
                        color = NeonMV.Cyan,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.width(3.dp))
                    Icon(
                        Icons.AutoMirrored.Outlined.ArrowForwardIos,
                        contentDescription = "All activities",
                        tint = NeonMV.Cyan,
                        modifier = Modifier.size(10.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(11.dp))
        if (recent.isEmpty()) {
            FeedRow(
                icon = Icons.AutoMirrored.Outlined.DirectionsRun,
                tone = NeonMV.Cyan,
                title = if (loading) "Loading…" else "No recent activity",
                sub = "Tap to open your feed",
                value = null,
                onClick = { onOpen("activities") },
            )
        } else {
            recent.forEach { a ->
                val cls = classifyRefined(a.type)
                FeedRow(
                    icon = cls.icon,
                    tone = cls.tone,
                    title = a.name?.trim()?.takeIf { it.isNotEmpty() } ?: titleCaseRefined(a.type),
                    sub = feedSub(a, cls.strength),
                    value = feedValue(a),
                    valueTone = cls.tone,
                    // Open the activity itself. This used to route to the
                    // Activities LIST, so tapping a row you were already
                    // looking at dumped you into a feed to find and tap it
                    // again. TrainHubScreen (plain Vitality Neon) always did
                    // this correctly; only the Refined variant was wired to
                    // the list, because the rows doubled as its only way in.
                    onClick = { onOpen("activity/${a.source}/${a.sourceId}") },
                )
                Spacer(Modifier.height(10.dp))
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

/** Jan 1 of LAST year — the YTD card compares against the same span a year
 *  ago, so the fetch has to reach back that far. */
private const val CACHE_YEAR_ACTS = "refined_train_year_acts"
private const val CACHE_YEAR_WKS = "refined_train_year_workouts"

private fun ytdSince(): String =
    java.time.LocalDate.of(java.time.LocalDate.now().year - 1, 1, 1)
        .atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toString()

// ── Caption eyebrow (web `.cap`) ──────────────────────────────────────────
@Composable
private fun Caption(text: String) {
    Text(
        text.uppercase(),
        color = NeonMV.Muted,
        fontFamily = NeonNumberFamily,
        fontSize = 10.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.4.sp,
    )
}

// ── Today's workout hero card ─────────────────────────────────────────────
@Composable
private fun HeroCard(
    title: String,
    sub: String,
    deloadNote: String?,
    ctaLabel: String,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(NeonMV.CardHigh)
            .border(1.dp, NeonMV.Cyan.copy(alpha = 0.16f), RoundedCornerShape(18.dp))
            .padding(16.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(13.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(46.dp)
                    .clip(RoundedCornerShape(13.dp))
                    .background(NeonMV.Cyan.copy(alpha = 0.12f))
                    .border(1.dp, NeonMV.Cyan.copy(alpha = 0.22f), RoundedCornerShape(13.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Outlined.FitnessCenter,
                    contentDescription = null,
                    tint = NeonMV.Cyan,
                    modifier = Modifier.size(24.dp),
                )
            }
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    color = NeonMV.Ink,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = (-0.2).sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    sub,
                    color = NeonMV.Muted,
                    fontSize = 12.5.sp,
                    fontWeight = FontWeight.Medium,
                )
            }
        }

        if (deloadNote != null) {
            Spacer(Modifier.height(12.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(11.dp))
                    .background(NeonMV.Amber.copy(alpha = 0.12f))
                    .border(1.dp, NeonMV.Amber.copy(alpha = 0.22f), RoundedCornerShape(11.dp))
                    .padding(horizontal = 11.dp, vertical = 8.dp),
            ) {
                Text(
                    deloadNote,
                    color = NeonMV.Amber,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }

        Spacer(Modifier.height(14.dp))
        // CTA — cyan neon fill, mirroring the web `.startbtn`.
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(13.dp))
                .background(NeonMV.Cyan)
                .clickable(onClick = onClick)
                .padding(vertical = 12.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                ctaLabel,
                color = NeonMV.OnAccent,
                fontSize = 14.sp,
                fontWeight = FontWeight.ExtraBold,
                letterSpacing = 0.2.sp,
            )
        }
    }
}

// ── Recent-activity feed row ──────────────────────────────────────────────
@Composable
private fun FeedRow(
    icon: ImageVector,
    tone: Color,
    title: String,
    sub: String,
    value: String?,
    onClick: () -> Unit,
    valueTone: Color = NeonMV.Muted,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(15.dp))
            .background(NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape)
                .background(tone.copy(alpha = 0.13f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = tone, modifier = Modifier.size(21.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(
                title,
                color = NeonMV.Ink,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                sub,
                color = NeonMV.Muted,
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (value != null) {
            NeonNumber(value, color = valueTone, size = 15, weight = FontWeight.SemiBold)
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

// ── Activity classification (mirrors web `classify` + the icon tone) ──────
private data class FeedClass(val icon: ImageVector, val tone: Color, val strength: Boolean)

private fun classifyRefined(type: String?): FeedClass {
    val t = (type ?: "").lowercase()
    val isStrength = t.contains("strength") || t.contains("weight") || t.contains("workout")
    return when {
        isStrength -> FeedClass(Icons.Outlined.FitnessCenter, NeonMV.Magenta, true)
        t.contains("trail") || t.contains("hike") -> FeedClass(Icons.Outlined.Terrain, NeonMV.Amber, false)
        t.contains("ride") || t.contains("bike") || t.contains("cycl") ->
            FeedClass(Icons.AutoMirrored.Outlined.DirectionsBike, NeonMV.Cyan, false)
        t.contains("swim") -> FeedClass(Icons.Outlined.Pool, NeonMV.Cyan, false)
        else -> FeedClass(Icons.AutoMirrored.Outlined.DirectionsRun, NeonMV.Cyan, false)
    }
}

/** Sub-line: relative day · Strength/Cardio (mirrors the web `sub`). */
private fun feedSub(a: ActivityRow, strength: Boolean): String =
    listOf(relDayRefined(a.startAt), if (strength) "Strength" else "Cardio")
        .filter { it.isNotBlank() }
        .joinToString(" · ")

/** Primary value: distance (mi) when present, else duration (m), else "—". */
private fun feedValue(a: ActivityRow): String {
    val mi = a.distanceM?.takeIf { it > 0 }
    if (mi != null) return "%.1f mi".format(mi / 1609.344)
    val dur = a.durationS.takeIf { it > 0 }
    if (dur != null) return "${Math.round(dur / 60.0)}m"
    return "—"
}

private fun relDayRefined(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
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
    }.getOrDefault("")
}

private fun titleCaseRefined(s: String): String =
    s.replace(Regex("[_-]+"), " ")
        .split(" ")
        .filter { it.isNotBlank() }
        .joinToString(" ") { it.replaceFirstChar { c -> c.uppercase() } }
