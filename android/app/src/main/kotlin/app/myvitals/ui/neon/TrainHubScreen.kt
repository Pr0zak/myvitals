package app.myvitals.ui.neon

import app.myvitals.data.Units
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.Handyman
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Pool
import androidx.compose.material.icons.outlined.Terrain
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.ActivityStatsOut
import app.myvitals.sync.BackendClient
import app.myvitals.sync.MuscleVolumeResponse
import app.myvitals.sync.MuscleVolumeRow
import app.myvitals.sync.StrengthStats
import app.myvitals.sync.StrengthWeekVolume
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.sync.UpcomingDay
import app.myvitals.ui.MV
import app.myvitals.ui.common.ShimmerBlock
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Train — neon training hub (UI-1). Mirrors web `Train.vue`.
 *
 *   1. Session hero: sets ring (outer arc = exercises), split, muscle chips,
 *      a full-width Continue button naming the next slot, and a Mon–Sun dot
 *      timeline.
 *   2. This week's volume as seven columns with last week's same weekday
 *      ghosted behind — totals, change and its direction from `/stats.week`.
 *   3. Working sets per muscle against its MEV–MAV band (`/muscle-volume`).
 *   4. This year, the activity calendar, the recent feed and a tile grid.
 *
 * Split into [TrainHubScreen] (fetching) and the stateless [TrainHubContent]
 * so the screen can be rendered from fixed data in a screenshot test.
 *
 * onOpen routes: "workout/today", "workout/history", "workout/charts",
 * "workout/catalog", "workout/training-prefs", "workout/equipment",
 * "workout/day/{date}", "activities", "activity/{source}/{sourceId}".
 */

/** The Recent feed shows a WEEK. The fetch behind it spans a year for the
 *  calendar and YTD stats, so this window has to be applied explicitly. */
private const val RECENT_DAYS = 7L

/** One row of the Recent feed: either a logged activity or a completed
 *  strength session. They come from different endpoints and have to be
 *  interleaved by time, not concatenated. */
private data class FeedEntry(
    val at: Instant,
    val activity: ActivityRow?,
    val workout: StrengthWorkoutSummary?,
)

@Composable
fun TrainHubScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    var workout by remember { mutableStateOf<StrengthWorkoutDetail?>(null) }
    var activities by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var upcoming by remember { mutableStateOf<List<UpcomingDay>>(emptyList()) }
    var yearWorkouts by remember { mutableStateOf<List<StrengthWorkoutSummary>>(emptyList()) }
    var stats by remember { mutableStateOf<StrengthStats?>(null) }
    var muscles by remember { mutableStateOf<MuscleVolumeResponse?>(null) }
    var activityStats by remember { mutableStateOf<ActivityStatsOut?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var reloadKey by remember { mutableIntStateOf(0) }

    LaunchedEffect(reloadKey) {
        if (!settings.isConfigured()) {
            loading = false; refreshing = false
            return@LaunchedEffect
        }
        // UX-F1: every call reports whether it FAILED, separately from what
        // it returned. A failed `/today` used to fall through to null, which
        // this screen renders as "Rest Day" — a dead backend read as a day
        // off. A failure now raises the banner and suppresses every empty
        // state that would otherwise speak for it.
        val failures = mutableListOf<String>()
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val workoutD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.strengthToday()
                        if (!r.isSuccessful) error("HTTP ${r.code()}")
                        r.body()
                    }
                }
                val actsD = async(Dispatchers.IO) {
                    runCatching { api.activities(limit = 2000, since = ytdSinceIso()) }
                }
                val yearWkD = async(Dispatchers.IO) {
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
                    }
                }
                val upcomingD = async(Dispatchers.IO) {
                    runCatching { api.upcomingWorkouts().upcoming }
                }
                val statsD = async(Dispatchers.IO) {
                    runCatching { api.strengthStats(days = 30) }
                }
                val musclesD = async(Dispatchers.IO) {
                    runCatching { api.strengthMuscleVolume(days = 7) }
                }
                val actStatsD = async(Dispatchers.IO) {
                    runCatching { api.activitiesStats(days = 30) }
                }
                workoutD.await().onSuccess { workout = it }.onFailure { failures += "today's plan" }
                actsD.await().onSuccess { activities = it }.onFailure { failures += "activities" }
                yearWkD.await().onSuccess { yearWorkouts = it }.onFailure { failures += "workouts" }
                upcomingD.await().onSuccess { upcoming = it }
                statsD.await().onSuccess { stats = it }.onFailure { failures += "volume" }
                musclesD.await().onSuccess { muscles = it }
                actStatsD.await().onSuccess { activityStats = it }
            }
        }.onFailure {
            Timber.w(it, "train hub load failed")
            failures += "backend"
        }
        error = if (failures.isEmpty()) null
            else "Couldn't load ${failures.distinct().joinToString(", ")}."
        loading = false
        refreshing = false
    }

    TrainHubContent(
        workout = workout,
        upcoming = upcoming,
        stats = stats,
        muscles = muscles,
        activities = activities,
        yearWorkouts = yearWorkouts,
        activityStats = activityStats,
        loading = loading,
        refreshing = refreshing,
        error = error,
        contentPadding = contentPadding,
        neon = settings.neonShellEnabled,
        onOpen = onOpen,
        onRefresh = { refreshing = true; reloadKey++ },
    )
}

/**
 * The Train tab rendered from data. [today] / [zone] / [now] are parameters
 * so a screenshot test renders a fixed day; the phone passes the defaults.
 */
@Composable
fun TrainHubContent(
    workout: StrengthWorkoutDetail?,
    upcoming: List<UpcomingDay>,
    stats: StrengthStats?,
    muscles: MuscleVolumeResponse?,
    activities: List<ActivityRow>,
    yearWorkouts: List<StrengthWorkoutSummary>,
    activityStats: ActivityStatsOut?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
    neon: Boolean = true,
    zone: ZoneId = ZoneId.systemDefault(),
    now: Instant = Instant.now(),
) {
    val today = now.atZone(zone).toLocalDate()
    var filter by remember { mutableStateOf<ActivityFilter?>(null) }

    // CONS-1: the count is the server's (local-day, full history).
    val weekCount = activityStats?.consistency?.sessionsLast7d

    val cutoff = now.minus(java.time.Duration.ofDays(RECENT_DAYS))
    val inWindow = remember(activities, now) {
        activities.filter { a -> parseInstant(a.startAt)?.isAfter(cutoff) ?: false }
    }
    // Offer a chip only if it would yield something in the visible window.
    val availableFilters = remember(inWindow) {
        ActivityFilter.entries.filter { f -> inWindow.any { f.matches(it.type) } }
    }
    val feed = remember(inWindow, yearWorkouts, filter, today) {
        val f = filter
        val acts = inWindow.filter { f == null || f.matches(it.type) }.take(25)
        // Completed STRENGTH sessions belong in Recent too; the chips filter
        // activity types, so a chip hides them.
        val wks = if (f != null) emptyList() else {
            val cutoffDay = today.minusDays(RECENT_DAYS)
            yearWorkouts.filter { w ->
                w.status == "completed" &&
                    runCatching { LocalDate.parse(w.date) }.getOrNull()?.isAfter(cutoffDay) == true
            }
        }
        (acts.map { FeedEntry(parseInstant(it.startAt) ?: Instant.EPOCH, it, null) } +
            wks.map { w ->
                FeedEntry(
                    at = parseInstant(w.completedAt)
                        ?: runCatching {
                            LocalDate.parse(w.date).atTime(12, 0).atZone(zone).toInstant()
                        }.getOrNull() ?: Instant.EPOCH,
                    activity = null, workout = w,
                )
            })
            .sortedByDescending { it.at }.take(25)
    }

    NeonScreen(
        title = "Train",
        contentPadding = contentPadding,
        headerTrailing = {
            if (weekCount != null) WeekChip(weekCount) { onOpen("activities") }
        },
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (error != null) {
            NeonErrorBanner(error, onRetry = onRefresh)
        }

        // ── 1. Session hero ────────────────────────────────────────────
        when {
            loading && workout == null -> HeroSkeleton()
            // A failed `/today` names no split and no rest day: the banner
            // above is the whole statement (UX-F1).
            error != null && workout == null -> Unit
            else -> SessionHero(
                workout = workout,
                timeline = weekTimeline(today, upcoming, yearWorkouts, activities, zone),
                onClick = { onOpen("workout/today") },
            )
        }

        // ── 2. Weekly volume chart ─────────────────────────────────────
        stats?.week?.let { w ->
            NeonEyebrow("This week's volume")
            WeekVolumeCard(w, sessions = stats.consistency?.sessionsLast7d, zone = zone) {
                onOpen("workout/charts")
            }
        }

        // ── 3. Muscle volume vs range ──────────────────────────────────
        muscles?.let { mv ->
            if (mv.muscles.isNotEmpty()) {
                NeonEyebrow("Sets per muscle · last ${mv.windowDays} days")
                MuscleRangeCard(mv.muscles) { onOpen("workout/history") }
            }
        }

        // ── 4. This year + activity calendar ───────────────────────────
        val ytd = remember(activities, yearWorkouts, today) {
            app.myvitals.ui.common.computeYtdComparison(activities, yearWorkouts, today)
        }
        val calIndex = remember(activities, yearWorkouts, today.year) {
            app.myvitals.ui.common.buildActivityCalendarIndex(activities, yearWorkouts, today.year)
        }
        if (activities.isNotEmpty() || yearWorkouts.isNotEmpty()) {
            NeonEyebrow("This year")
            app.myvitals.ui.common.YtdStatPair(
                cmp = ytd, neon = true, onClick = { onOpen("activities") },
            )
        }
        if (calIndex.isNotEmpty()) {
            NeonEyebrow("Activity calendar")
            app.myvitals.ui.common.ActivityCalendarCard(
                rows = activities, workouts = yearWorkouts,
                neon = true, year = today.year, title = null,
            )
        }

        // ── 5. Recent feed ─────────────────────────────────────────────
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            NeonEyebrow("Recent · last 7 days")
            SeeAll { onOpen("activities") }
        }
        if (availableFilters.size > 1) {
            FilterBar(
                available = availableFilters,
                selected = filter,
                neon = neon,
                onSelect = { filter = it },
            )
            Spacer(Modifier.height(11.dp))
        }
        // Rows are spaced by the column, not by a Spacer each branch has to
        // remember: the strength branch used to `return@forEach` before its
        // spacer, so workout pills sat flush against the next row.
        Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
            when {
                loading && activities.isEmpty() && yearWorkouts.isEmpty() -> {
                    ShimmerBlock(Modifier.fillMaxWidth(), height = 68.dp,
                        cornerRadius = 22.dp, accent = NeonMV.Cyan)
                    ShimmerBlock(Modifier.fillMaxWidth(), height = 68.dp,
                        cornerRadius = 22.dp, accent = NeonMV.Cyan)
                }
                // A failed fetch is not a quiet week (UX-F1).
                error != null && feed.isEmpty() -> Unit
                feed.isEmpty() -> ActivityPill(
                    icon = Icons.AutoMirrored.Outlined.FormatListBulleted,
                    tone = NeonMV.Muted,
                    title = filter?.let { "No ${it.label} activities this week" }
                        ?: "No activity in the last ${RECENT_DAYS.toInt()} days",
                    sub = "Tap to see your full history",
                    value = null,
                    onClick = { onOpen("activities") },
                )
                else -> feed.forEach { entry ->
                    val w = entry.workout
                    val a = entry.activity
                    if (w != null) {
                        ActivityPill(
                            icon = Icons.Outlined.FitnessCenter,
                            tone = NeonMV.Magenta,
                            title = titleCase(w.splitFocus) + " workout",
                            sub = relDay(entry.at, today, zone),
                            value = null,
                            onClick = { onOpen("workout/day/${w.date}") },
                        )
                    } else if (a != null) {
                        val cls = classify(a.type)
                        ActivityPill(
                            icon = cls.icon,
                            tone = cls.tone,
                            title = a.name?.trim()?.takeIf { it.isNotEmpty() } ?: titleCase(a.type),
                            sub = activitySub(a, today, zone),
                            value = activityValue(a, cls),
                            onClick = { onOpen("activity/${a.source}/${a.sourceId}") },
                        )
                    }
                }
            }
        }

        // ── 6. Tile grid ───────────────────────────────────────────────
        NeonEyebrow("More")
        TileGrid(
            listOf(
                Tile("Activities", Icons.AutoMirrored.Outlined.FormatListBulleted, NeonMV.Cyan, "activities"),
                Tile("History", Icons.Outlined.History, NeonMV.Lime, "workout/history"),
                Tile("Charts", Icons.Outlined.BarChart, NeonMV.Lime, "workout/charts"),
                Tile("Catalog", Icons.Outlined.FitnessCenter, NeonMV.Periwinkle, "workout/catalog"),
                Tile("Preferences", Icons.Outlined.Tune, NeonMV.Periwinkle, "workout/training-prefs"),
                Tile("Equipment", Icons.Outlined.Handyman, NeonMV.Amber, "workout/equipment"),
            ),
            onOpen = onOpen,
        )
        Spacer(Modifier.height(24.dp))
    }
}

// ── Session hero ─────────────────────────────────────────────────────────

/** One dot of the hero's Mon–Sun timeline. */
private enum class DotState { Done, Today, TodayDone, Planned, Empty }

private data class TimelineDot(val date: LocalDate, val state: DotState)

/**
 * This local Mon–Sun week as dots. Past and today read "done" from completed
 * sessions and logged activities; future days read "planned" from the
 * generator-authoritative `/upcoming` forecast, which omits rest days, so an
 * absent day is simply empty. Nothing here is a number — it is which days
 * something happened, from rows the server already dated.
 */
private fun weekTimeline(
    today: LocalDate,
    upcoming: List<UpcomingDay>,
    workouts: List<StrengthWorkoutSummary>,
    activities: List<ActivityRow>,
    zone: ZoneId,
): List<TimelineDot> {
    val monday = today.minusDays((today.dayOfWeek.value - 1).toLong())
    val done = buildSet {
        workouts.filter { it.status == "completed" }.forEach { add(it.date) }
        activities.forEach { a ->
            parseInstant(a.startAt)?.atZone(zone)?.toLocalDate()?.let { add(it.toString()) }
        }
    }
    val planned = upcoming.filter { !it.splitFocus.contains("rest", true) }.map { it.date }.toSet()
    return (0 until 7).map { i ->
        val d = monday.plusDays(i.toLong())
        val iso = d.toString()
        val state = when {
            d == today && iso in done -> DotState.TodayDone
            d == today -> DotState.Today
            d.isBefore(today) && iso in done -> DotState.Done
            d.isAfter(today) && iso in planned -> DotState.Planned
            else -> DotState.Empty
        }
        TimelineDot(d, state)
    }
}

/** The hero's button: label, whether it is the muted "finished" form. */
private data class HeroCta(
    val label: String,
    val muted: Boolean,
    /** The next exercise, rendered between `label` and `suffix`. */
    val name: String? = null,
    val suffix: String? = null,
)

/**
 * OG3-A1 — the button reads the session's own `status`, never only its
 * focus: a completed or skipped workout must not present as an outstanding
 * task on the most prominent card of the tab. The next slot and whether the
 * session has started come from the server's `next_up`, which is decided by
 * the same predicates as the progress counters.
 */
private fun heroCta(w: StrengthWorkoutDetail?): HeroCta {
    if (w == null) return HeroCta("View", muted = true)
    if (w.status == "completed") return HeroCta("Done · see review", muted = true)
    if (w.status == "skipped") return HeroCta("Skipped · view", muted = true)
    if (w.splitFocus.contains("rest", true)) return HeroCta("View", muted = true)
    val n = w.nextUp
    return when {
        n != null && n.started -> HeroCta("Continue", muted = false,
            name = n.name, suffix = ", set ${n.setNumber}")
        n != null -> HeroCta("Start", muted = false)
        w.status == "in_progress" || w.status == "paused" -> HeroCta("Resume", muted = false)
        else -> HeroCta("Start", muted = false)
    }
}

/** Per-muscle accent, shared by the hero chips and the range rows. Never
 *  rose: rose is the crisis colour, and chest is not a crisis. */
private fun muscleColor(m: String): Color = when (m.lowercase()) {
    "chest" -> NeonMV.Magenta
    "back", "lats", "middle back", "lower back", "traps" -> NeonMV.Cyan
    "shoulders" -> NeonMV.Amber
    "biceps", "forearms" -> NeonMV.Magenta
    "triceps" -> NeonMV.Periwinkle
    "quadriceps", "quads", "hamstrings", "calves", "glutes", "adductors", "abductors" -> NeonMV.Lime
    "abdominals", "abs", "core" -> NeonMV.Amber
    else -> NeonMV.Muted
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun SessionHero(
    workout: StrengthWorkoutDetail?,
    timeline: List<TimelineDot>,
    onClick: () -> Unit,
) {
    val cta = heroCta(workout)
    val isRest = workout == null || workout.splitFocus.contains("rest", true)
    val completed = workout?.status == "completed"
    // SKIP-1: both counters are the server's, rendered verbatim.
    val setsDone = workout?.setsDone ?: 0
    val setsTotal = workout?.setsTotal ?: 0
    val exDone = workout?.exercisesDone ?: 0
    val exTotal = workout?.exercisesTotal ?: 0
    // The plan's muscles: rows of the projection that today's plan adds to.
    val chips = workout?.projectedMuscleVolume
        ?.filter { (it.value.setsPlanned ?: 0.0) > 0.0 }
        ?.entries?.sortedByDescending { it.value.setsPlanned ?: 0.0 }
        ?.map { it.key }?.take(5).orEmpty()

    NeonHeroCard(accent = NeonMV.Lime) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            NeonRing(
                fraction = if (setsTotal > 0) setsDone.toFloat() / setsTotal else 0f,
                color = NeonMV.Lime,
                size = 120.dp,
                stroke = 10.dp,
                outerFraction = if (exTotal > 0) exDone.toFloat() / exTotal else 0f,
                outerColor = NeonMV.Cyan,
            ) {
                if (setsTotal > 0) {
                    NeonNumber("$setsDone/$setsTotal", color = NeonMV.Lime, size = 22)
                    NeonRingCaption("sets")
                    Text("$exDone/$exTotal ex", color = NeonMV.Cyan, fontSize = 10.sp,
                        fontFamily = NeonNumberFamily, fontWeight = FontWeight.Bold)
                } else {
                    NeonNumber("—", color = NeonMV.Muted, size = 22)
                    NeonRingCaption(if (isRest) "rest" else "no sets")
                }
            }
            Column(Modifier.weight(1f)) {
                Text(
                    when {
                        completed -> "TODAY · DONE"
                        workout?.status == "skipped" -> "TODAY · SKIPPED"
                        exTotal == 1 -> "TODAY · 1 EXERCISE"
                        exTotal > 1 -> "TODAY · $exTotal EXERCISES"
                        else -> "TODAY"
                    },
                    color = if (completed) NeonMV.Muted else NeonMV.Lime,
                    fontFamily = NeonNumberFamily,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp,
                    maxLines = 1,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    if (isRest) "Rest day" else titleCase(workout!!.splitFocus),
                    color = NeonMV.Ink, fontSize = 26.sp, fontWeight = FontWeight.ExtraBold,
                    letterSpacing = (-0.5).sp, maxLines = 2, lineHeight = 28.sp,
                )
                if (chips.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) { chips.forEach { MuscleChip(it) } }
                }
            }
        }

        Spacer(Modifier.height(14.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(48.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(if (cta.muted) NeonMV.Card else NeonMV.Lime)
                .border(1.dp, if (cta.muted) NeonMV.Track else NeonMV.Lime, RoundedCornerShape(14.dp))
                .clickable(onClick = onClick)
                .semantics { role = Role.Button }
                .padding(horizontal = 16.dp),
            contentAlignment = Alignment.Center,
        ) {
            // Only the exercise NAME may ellipsize: a long name used to push
            // "set 3" — the part that says where you are — off the button.
            val ink = if (cta.muted) NeonMV.Muted else NeonMV.OnAccent
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(cta.label, color = ink, fontSize = 15.sp, fontWeight = FontWeight.ExtraBold, maxLines = 1)
                if (cta.name != null) {
                    Text(" · ", color = ink, fontSize = 15.sp, fontWeight = FontWeight.ExtraBold)
                    Text(cta.name, color = ink, fontSize = 15.sp, fontWeight = FontWeight.ExtraBold,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false))
                    Text(cta.suffix.orEmpty(), color = ink, fontSize = 15.sp,
                        fontWeight = FontWeight.ExtraBold, maxLines = 1)
                }
            }
        }

        Spacer(Modifier.height(14.dp))
        WeekDots(timeline)
    }
}

@Composable
private fun MuscleChip(muscle: String) {
    val c = muscleColor(muscle)
    Text(
        titleCase(muscle),
        color = c, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1,
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(c.copy(alpha = 0.14f))
            .border(1.dp, c.copy(alpha = 0.35f), RoundedCornerShape(10.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@Composable
private fun WeekDots(dots: List<TimelineDot>) {
    val desc = dots.joinToString(", ") { d ->
        val day = d.date.dayOfWeek.getDisplayName(java.time.format.TextStyle.FULL, java.util.Locale.getDefault())
        day + " " + when (d.state) {
            DotState.Done, DotState.TodayDone -> "done"
            DotState.Today -> "today"
            DotState.Planned -> "planned"
            DotState.Empty -> "nothing"
        }
    }
    Row(
        Modifier.fillMaxWidth().semantics { contentDescription = "This week: $desc" },
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        dots.forEach { d ->
            Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(32.dp)) {
                Canvas(Modifier.size(14.dp)) {
                    val r = size.minDimension / 2
                    when (d.state) {
                        DotState.Done, DotState.TodayDone -> drawCircle(NeonMV.Lime, r)
                        DotState.Today -> {
                            drawCircle(NeonMV.Lime.copy(alpha = 0.18f), r)
                            drawCircle(NeonMV.Lime, r - 1.dp.toPx(), style = Stroke(2.dp.toPx()))
                        }
                        DotState.Planned -> drawCircle(NeonMV.Periwinkle, r * 0.72f)
                        DotState.Empty -> drawCircle(NeonMV.Track, r * 0.72f)
                    }
                    if (d.state == DotState.TodayDone) {
                        drawCircle(NeonMV.Ink, r + 2.dp.toPx() - 1.dp.toPx(),
                            style = Stroke(1.5.dp.toPx()))
                    }
                }
                Spacer(Modifier.height(4.dp))
                val isToday = d.state == DotState.Today || d.state == DotState.TodayDone
                Text(
                    d.date.dayOfWeek.getDisplayName(java.time.format.TextStyle.NARROW, java.util.Locale.getDefault()),
                    color = if (isToday) NeonMV.Lime else NeonMV.Muted,
                    fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    fontFamily = NeonNumberFamily,
                )
            }
        }
    }
}

/** Loading shape of the hero, so the page does not jump when it lands. */
@Composable
private fun HeroSkeleton() {
    NeonHeroCard(accent = NeonMV.Lime) {
        Row(verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            ShimmerBlock(width = 120.dp, height = 120.dp, cornerRadius = 60.dp, accent = NeonMV.Lime)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ShimmerBlock(width = 110.dp, height = 11.dp, accent = NeonMV.Lime)
                ShimmerBlock(Modifier.fillMaxWidth(0.8f), height = 26.dp, accent = NeonMV.Lime)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    ShimmerBlock(width = 54.dp, height = 18.dp, cornerRadius = 10.dp, accent = NeonMV.Lime)
                    ShimmerBlock(width = 64.dp, height = 18.dp, cornerRadius = 10.dp, accent = NeonMV.Lime)
                }
            }
        }
        Spacer(Modifier.height(14.dp))
        ShimmerBlock(Modifier.fillMaxWidth(), height = 48.dp, cornerRadius = 14.dp, accent = NeonMV.Lime)
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            repeat(7) { ShimmerBlock(width = 14.dp, height = 14.dp, cornerRadius = 7.dp, accent = NeonMV.Lime) }
        }
    }
}

// ── Weekly volume chart ──────────────────────────────────────────────────

@Composable
private fun WeekVolumeCard(
    w: StrengthWeekVolume,
    sessions: Int?,
    zone: ZoneId,
    onClick: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .clickable(onClick = onClick)
            .padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            NeonNumber("%,.0f".format(w.totalLb), size = 26)
            Spacer(Modifier.width(4.dp))
            Text("lb", color = NeonMV.Muted, fontSize = 12.sp, modifier = Modifier.padding(bottom = 4.dp))
            Spacer(Modifier.weight(1f))
            DeltaChip(w)
        }
        Text(
            buildString {
                append("vs %,.0f lb the week before".format(w.prevTotalLb))
                if (sessions != null) append(" · $sessions session${if (sessions == 1) "" else "s"}")
            },
            color = NeonMV.Muted, fontSize = 12.sp,
        )
        Spacer(Modifier.height(12.dp))
        val maxV = w.days.maxOfOrNull { maxOf(it.volumeLb, it.prevVolumeLb) }?.takeIf { it > 0 } ?: 1.0
        val desc = w.days.joinToString("; ") { d ->
            "${dayLabel(d.date, java.time.format.TextStyle.FULL)} %,.0f lb, last week %,.0f".format(d.volumeLb, d.prevVolumeLb)
        }
        Canvas(
            Modifier
                .fillMaxWidth()
                .height(96.dp)
                .semantics { contentDescription = "Daily volume this week against last week: $desc" },
        ) {
            val n = w.days.size.coerceAtLeast(1)
            val slot = size.width / n
            val ghostW = slot * 0.62f
            val barW = slot * 0.36f
            val cr = CornerRadius(4.dp.toPx(), 4.dp.toPx())
            // Baseline.
            drawLine(NeonMV.Line, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
            w.days.forEachIndexed { i, d ->
                val cx = slot * i + slot / 2
                val ph = (d.prevVolumeLb / maxV).toFloat() * size.height
                if (ph > 0f) drawRoundRect(
                    NeonMV.Track, Offset(cx - ghostW / 2, size.height - ph), Size(ghostW, ph), cr,
                )
                val h = (d.volumeLb / maxV).toFloat() * size.height
                if (h > 0f) {
                    drawRoundRect(NeonMV.Lime.copy(alpha = 0.22f),
                        Offset(cx - barW / 2 - 2.dp.toPx(), size.height - h - 2.dp.toPx()),
                        Size(barW + 4.dp.toPx(), h + 2.dp.toPx()), cr)
                    drawRoundRect(NeonMV.Lime, Offset(cx - barW / 2, size.height - h), Size(barW, h), cr)
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(Modifier.fillMaxWidth()) {
            w.days.forEach { d ->
                Text(
                    dayLabel(d.date, java.time.format.TextStyle.NARROW),
                    color = if (d.date == w.end) NeonMV.Lime else NeonMV.Muted,
                    fontSize = 10.sp, fontWeight = FontWeight.Bold, fontFamily = NeonNumberFamily,
                    textAlign = TextAlign.Center, modifier = Modifier.weight(1f),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(NeonMV.Lime))
            Text(" This week   ", color = NeonMV.Muted, fontSize = 11.sp)
            Box(Modifier.size(8.dp).clip(CircleShape).background(NeonMV.Track))
            Text(" Same day last week", color = NeonMV.Muted, fontSize = 11.sp)
        }
        // OG2-A3: the pounds figure cannot speak for bodyweight work.
        if (w.unweightedSets > 0) {
            Spacer(Modifier.height(4.dp))
            Text(
                "+ ${w.unweightedSets} bodyweight set${if (w.unweightedSets == 1) "" else "s"} not counted in lb",
                color = NeonMV.Muted, fontSize = 11.sp,
            )
        }
    }
}

/** Server-decided direction → colour. Never rose: a lighter week is a
 *  caution at most, and often a planned deload. */
@Composable
private fun DeltaChip(w: StrengthWeekVolume) {
    val pct = w.deltaPct
    val (text, color) = when {
        pct == null -> "no lifting last week" to NeonMV.Muted
        w.direction == "improved" -> "▲ %.0f%%".format(kotlin.math.abs(pct)) to NeonMV.Lime
        w.direction == "worse" -> "▼ %.0f%%".format(kotlin.math.abs(pct)) to NeonMV.Amber
        else -> "≈ same" to NeonMV.Muted
    }
    Text(
        text, color = color, fontSize = 12.sp, fontWeight = FontWeight.Bold,
        fontFamily = NeonNumberFamily,
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(color.copy(alpha = 0.12f))
            .border(1.dp, color.copy(alpha = 0.3f), RoundedCornerShape(10.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

private fun dayLabel(iso: String, style: java.time.format.TextStyle): String =
    runCatching {
        LocalDate.parse(iso).dayOfWeek.getDisplayName(style, java.util.Locale.getDefault())
    }.getOrDefault("")

// ── Muscle volume vs MEV–MAV ─────────────────────────────────────────────

/** Status → dot colour. `status` is the server's `volume_status`; this only
 *  maps it. Over MAV is amber, not rose. */
private fun statusColor(status: String): Color = when (status) {
    "in_range" -> NeonMV.Lime
    "under" -> NeonMV.Periwinkle
    "over" -> NeonMV.Amber
    else -> NeonMV.Muted
}

@Composable
private fun MuscleRangeCard(rows: Map<String, MuscleVolumeRow>, onClick: () -> Unit) {
    val trained = rows.entries.filter { it.value.sets > 0 }.sortedByDescending { it.value.sets }
    val untrained = rows.entries.filter { it.value.sets <= 0 }.map { it.key }
    // One shared scale so bands are comparable row to row.
    val scale = (rows.values.maxOfOrNull { maxOf(it.mav, it.sets) } ?: 1).coerceAtLeast(1) * 1.1f
    Column(
        Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .clickable(onClick = onClick)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        if (trained.isEmpty()) {
            Text("No working sets logged in this window.", color = NeonMV.Muted, fontSize = 12.sp)
        }
        trained.forEach { (m, r) ->
            val c = statusColor(r.status)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.semantics(mergeDescendants = true) {
                    contentDescription = "${titleCase(m)}: ${r.sets} sets, range ${r.mev} to ${r.mav}, " +
                        r.status.replace('_', ' ')
                },
            ) {
                Text(titleCase(m), color = NeonMV.Ink, fontSize = 12.sp, maxLines = 1,
                    overflow = TextOverflow.Ellipsis, modifier = Modifier.width(86.dp))
                Canvas(Modifier.weight(1f).height(14.dp)) {
                    val y = size.height / 2
                    val th = 6.dp.toPx()
                    drawRoundRect(NeonMV.Track, Offset(0f, y - th / 2), Size(size.width, th),
                        CornerRadius(th / 2, th / 2))
                    val x0 = (r.mev / scale) * size.width
                    val x1 = (r.mav / scale) * size.width
                    drawRoundRect(NeonMV.Lime.copy(alpha = 0.28f), Offset(x0, y - th / 2),
                        Size((x1 - x0).coerceAtLeast(1f), th), CornerRadius(th / 2, th / 2))
                    val xv = (r.sets / scale).coerceIn(0f, 1f) * size.width
                    drawCircle(c.copy(alpha = 0.3f), 7.dp.toPx(), Offset(xv, y))
                    drawCircle(c, 4.5.dp.toPx(), Offset(xv, y))
                }
                Spacer(Modifier.width(8.dp))
                NeonNumber("${r.sets}", color = c, size = 13, modifier = Modifier.width(22.dp))
                Text("/${r.mev}–${r.mav}", color = NeonMV.Muted, fontSize = 10.sp,
                    fontFamily = NeonNumberFamily, modifier = Modifier.width(40.dp))
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            LegendDot(NeonMV.Periwinkle, "under")
            LegendDot(NeonMV.Lime, "in range")
            LegendDot(NeonMV.Amber, "over")
            Box(Modifier.width(14.dp).height(6.dp).clip(RoundedCornerShape(3.dp))
                .background(NeonMV.Lime.copy(alpha = 0.28f)))
            Text("MEV–MAV", color = NeonMV.Muted, fontSize = 10.sp)
        }
        if (untrained.isNotEmpty()) {
            Text(
                "Not trained: " + untrained.joinToString(", ") { titleCase(it) },
                color = NeonMV.Muted, fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun LegendDot(c: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(c))
        Text(" $label", color = NeonMV.Muted, fontSize = 10.sp)
    }
}

// ── Tile grid ────────────────────────────────────────────────────────────

private data class Tile(val label: String, val icon: ImageVector, val tone: Color, val route: String)

@Composable
private fun TileGrid(tiles: List<Tile>, onOpen: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        tiles.chunked(3).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { t ->
                    Column(
                        Modifier
                            .weight(1f)
                            .heightIn(min = 76.dp)
                            .clip(NeonCardShape)
                            .background(NeonMV.Card)
                            .border(1.dp, NeonMV.Line, NeonCardShape)
                            .clickable { onOpen(t.route) }
                            .semantics(mergeDescendants = true) {
                                role = Role.Button
                                contentDescription = "Open ${t.label}"
                            }
                            .padding(vertical = 12.dp, horizontal = 6.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Box(
                            Modifier.size(34.dp).clip(CircleShape).background(t.tone.copy(alpha = 0.14f)),
                            contentAlignment = Alignment.Center,
                        ) { Icon(t.icon, contentDescription = null, tint = t.tone, modifier = Modifier.size(18.dp)) }
                        Spacer(Modifier.height(6.dp))
                        Text(t.label, color = NeonMV.Ink, fontSize = 12.sp, fontWeight = FontWeight.Bold,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

// ── Header week chip ─────────────────────────────────────────────────────
/** Jan 1 of LAST year — the YTD pair compares against the same span a year
 *  ago, so the fetch has to reach back that far. */
private fun ytdSinceIso(): String =
    LocalDate.of(LocalDate.now().year - 1, 1, 1)
        .atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toString()

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
        Text("This week · ", color = NeonMV.Lime, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        NeonNumber("$count", color = NeonMV.Lime, size = 13, weight = FontWeight.Bold)
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
        Text("See all", color = NeonMV.Cyan, fontSize = 11.sp, fontWeight = FontWeight.Bold,
            letterSpacing = 0.6.sp)
        Icon(Icons.AutoMirrored.Outlined.ArrowForwardIos, contentDescription = null,
            tint = NeonMV.Cyan, modifier = Modifier.size(9.dp))
    }
}

// ── Activity filter categories (web Activities parity) ───────────────────
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

@Composable
private fun FilterBar(
    available: List<ActivityFilter>,
    selected: ActivityFilter?,
    neon: Boolean,
    onSelect: (ActivityFilter?) -> Unit,
) {
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FilterChip(label = "All", active = selected == null, accent = accent) { onSelect(null) }
        available.forEach { f ->
            FilterChip(label = f.label, active = selected == f, accent = accent) {
                onSelect(if (selected == f) null else f)
            }
        }
    }
}

@Composable
private fun FilterChip(label: String, active: Boolean, accent: Color, onClick: () -> Unit) {
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
        Text(label, color = ink, fontSize = 13.sp, fontWeight = FontWeight.Bold,
            letterSpacing = 0.3.sp, maxLines = 1)
    }
}

// ── Recent-activity pill row ─────────────────────────────────────────────
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
            modifier = Modifier.size(40.dp).clip(CircleShape).background(tone.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = tone, modifier = Modifier.size(20.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, color = NeonMV.Ink, fontSize = 16.sp, fontWeight = FontWeight.Bold,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(2.dp))
            Text(sub, color = NeonMV.Muted, fontSize = 12.sp, fontWeight = FontWeight.Medium, maxLines = 1)
        }
        if (value != null) {
            NeonNumber(value, color = tone, size = 14, weight = FontWeight.Bold)
            Spacer(Modifier.width(4.dp))
        }
        Icon(Icons.AutoMirrored.Outlined.ArrowForwardIos, contentDescription = null,
            tint = NeonMV.Muted, modifier = Modifier.size(12.dp))
    }
}

// ── Activity classification (mirrors web `classifyType`) ─────────────────
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

private fun activitySub(a: ActivityRow, today: LocalDate, zone: ZoneId): String {
    val at = parseInstant(a.startAt)
    val parts = mutableListOf(if (at != null) relDay(at, today, zone) else "—")
    val mi = milesOrNull(a.distanceM)
    if (mi != null) parts.add(mi) else parts.add(titleCase(a.type))
    return parts.filter { it.isNotBlank() }.joinToString(" · ")
}

private fun activityValue(a: ActivityRow, cls: ActivityClass): String {
    if (cls.isTrail) {
        val m = a.elevationGainM?.takeIf { it > 0 }
        if (m != null) return Units.fmtElevation(m)
    }
    return hms(a.durationS)
}

private fun milesOrNull(distanceM: Double?): String? {
    if (distanceM == null || distanceM <= 0) return null
    return Units.fmtDistance(distanceM, 1)
}

private fun hms(durationS: Int?): String {
    if (durationS == null || durationS <= 0) return "—"
    val h = durationS / 3600
    val m = (durationS % 3600) / 60
    return if (h > 0) "%d:%02d".format(h, m) else "%d:%02d".format(m, durationS % 60)
}

/** A server timestamp as an instant. A string with no offset is UTC, which
 *  is how every timestamp column in this schema is written. */
private fun parseInstant(iso: String?): Instant? {
    if (iso.isNullOrBlank()) return null
    return runCatching { Instant.parse(iso) }.getOrNull()
        ?: runCatching { java.time.OffsetDateTime.parse(iso).toInstant() }.getOrNull()
        ?: runCatching {
            java.time.LocalDateTime.parse(iso).atZone(java.time.ZoneOffset.UTC).toInstant()
        }.getOrNull()
}

/** "Today" / "Yesterday" / "Tue" / "Sep 3" for an instant, on the user's
 *  LOCAL calendar. The old version took the first ten characters of the UTC
 *  timestamp, so an evening ride in Central was dated tomorrow. */
private fun relDay(at: Instant, today: LocalDate, zone: ZoneId): String {
    val date = at.atZone(zone).toLocalDate()
    val diff = today.toEpochDay() - date.toEpochDay()
    return when {
        diff <= 0L -> "Today"
        diff == 1L -> "Yesterday"
        diff < 7L -> date.dayOfWeek.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.getDefault())
        else -> "%s %d".format(
            date.month.getDisplayName(java.time.format.TextStyle.SHORT, java.util.Locale.getDefault()),
            date.dayOfMonth,
        )
    }
}

private fun titleCase(s: String): String =
    s.replace(Regex("[_-]+"), " ")
        .split(" ")
        .filter { it.isNotBlank() }
        .joinToString(" ") { it.replaceFirstChar { c -> c.uppercase() } }
