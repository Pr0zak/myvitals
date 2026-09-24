package app.myvitals.ui.activities

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.automirrored.outlined.DirectionsWalk
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.DownhillSkiing
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.Hiking
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Rowing
import androidx.compose.material.icons.outlined.SelfImprovement
import androidx.compose.material.icons.outlined.SportsEsports
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.data.Units
import app.myvitals.sync.ActivityRecord
import app.myvitals.sync.ActivityRecordsOut
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.ActivityStatsOut
import app.myvitals.sync.ActivityYtd
import app.myvitals.sync.BackendClient
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.sync.YtdMetric
import app.myvitals.ui.common.ActivityCalendarCard
import app.myvitals.ui.common.buildActivityCalendarIndex
import app.myvitals.ui.common.categoryForActivityType
import app.myvitals.ui.common.categoryForSplitFocus
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonNumberFamily
import app.myvitals.ui.neon.NeonScreen
import app.myvitals.ui.neon.NeonStatTile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/*
 * Activities feed (UI-5).
 *
 * What changed and why:
 *  - It rendered on the CLASSIC MV palette inside the neon shell; it is a
 *    NeonScreen now, like every other screen.
 *  - The year-to-date card recomputed YTD on the phone from an 18-month
 *    activity dump — a third copy of a loop that the web and Train each had
 *    their own version of, disagreeing about strength time. It comes from
 *    GET /activities/ytd, and so do the week-header totals.
 *  - "↑100%" was printed whenever last year was zero, and a shortfall was
 *    painted red. The server now sends a null percentage plus a "new" note,
 *    and a `tone` that is amber for a shortfall — never rose.
 *  - Elevation was always "m"; values sat in 11sp subtitles; two row radii.
 *    Rows are one 18dp shape with a right-aligned 16sp primary number.
 *  - A failed refresh replaced the cached list with a line of red text. It
 *    is an amber banner ABOVE the cached rows now.
 *
 * UI-F2 added a period-stats row and a personal-records card for exactly
 * the range + chip selected (GET /activities/stats?since=&category= and
 * GET /activities/records), group-by-month headers from the server's month
 * totals, and switched the type chips from substring matching to the
 * shared category mapping so a chip, the stats and the records all mean
 * the same set of activities.
 */

// Combined feed entry — either a Strava-style activity or a strength
// workout. Displayed sorted by most-recent date, with different rows.
sealed class FeedEntry {
    abstract val sortKey: String  // ISO datetime string, descending sort
    data class Activity(val a: ActivityRow) : FeedEntry() {
        override val sortKey = a.startAt
    }
    data class Strength(val w: StrengthWorkoutSummary) : FeedEntry() {
        override val sortKey = w.startedAt ?: w.completedAt ?: (w.date + "T00:00:00Z")
    }
}

// ── Feed filters (client-side, on the already-loaded wide range) ──────

/** Date-range chips. Filters feed items by their local day against a cutoff. */
private enum class RangeFilter(val label: String) {
    D7("7d"), D30("30d"), D90("90d"), YTD("YTD");

    fun cutoff(today: LocalDate): LocalDate = when (this) {
        D7 -> today.minusDays(6)
        D30 -> today.minusDays(29)
        D90 -> today.minusDays(89)
        YTD -> LocalDate.of(today.year, 1, 1)
    }
}

/** Type chips — the web's chips, keyed by the shared category mapping
 *  (`categoryForActivityType`) so the server's stats and records filter
 *  the same set. "Strength" keeps the interleaved strength-workout items.
 *  (UI-F2: these used to substring-match `type`, which disagreed with the
 *  category the row's icon tint was drawn from.) */
private enum class TypeFilter(val label: String, val key: String) {
    ALL("All", "all"),
    RIDE("Ride", "ride"),
    RUN("Run", "run"),
    WALK("Walk / hike", "walk"),
    ROW("Row", "row"),
    OTHER("Other", "other"),
    STRENGTH("Strength", "strength");
}

/** The user's local calendar day for a feed entry. Unparseable → null. */
private fun entryDay(e: FeedEntry, zone: ZoneId): LocalDate? = when (e) {
    is FeedEntry.Activity -> runCatching {
        Instant.parse(e.a.startAt).atZone(zone).toLocalDate()
    }.recoverCatching {
        java.time.OffsetDateTime.parse(e.a.startAt).atZoneSameInstant(zone).toLocalDate()
    }.getOrNull()
    is FeedEntry.Strength -> runCatching { LocalDate.parse(e.w.date) }.getOrNull()
}

/** Strava cookie-session state for the header + banner. */
data class StravaUi(
    val needsReconnect: Boolean = false,
    val cookieError: String? = null,
    val syncing: Boolean = false,
    val toast: String? = null,
)

@Composable
fun ActivitiesScreen(
    settings: SettingsRepository,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
    onOpenStrengthDay: (dateIso: String) -> Unit = {},
    onOpenMap: () -> Unit = {},
    onBack: (() -> Unit)? = null,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    var rows by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var workouts by remember { mutableStateOf<List<StrengthWorkoutSummary>>(emptyList()) }
    var ytd by remember { mutableStateOf<ActivityYtd?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var strava by remember { mutableStateOf(StravaUi()) }
    var periodStats by remember { mutableStateOf<ActivityStatsOut?>(null) }
    var records by remember { mutableStateOf<ActivityRecordsOut?>(null) }
    var summaryFailed by remember { mutableStateOf(false) }
    var summaryJob by remember { mutableStateOf<Job?>(null) }
    LaunchedEffect(strava.toast) {
        if (strava.toast != null) { delay(4000); strava = strava.copy(toast = null) }
    }

    suspend fun refreshCookieStatus() {
        if (!settings.isConfigured()) return
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) { api.stravaCookieStatus() }
        }.getOrNull()?.let {
            strava = strava.copy(needsReconnect = it.needsReconnect, cookieError = it.lastError)
        }
    }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."; loading = false; return
        }
        // Stale-while-revalidate: render the cached feed, then refresh it.
        val listT = app.myvitals.data.JsonCache.listType(ActivityRow::class.java)
        val woT = app.myvitals.data.JsonCache.listType(StrengthWorkoutSummary::class.java)
        if (rows.isEmpty()) {
            app.myvitals.data.JsonCache.read<List<ActivityRow>>(context, "activities_feed", listT)
                ?.let { cached ->
                    rows = cached.value
                    workouts = app.myvitals.data.JsonCache.read<List<StrengthWorkoutSummary>>(
                        context, "activities_workouts", woT,
                    )?.value ?: emptyList()
                    loading = false
                }
            app.myvitals.data.JsonCache.read<ActivityYtd>(
                context, "activities_ytd", ActivityYtd::class.java,
            )?.let { ytd = it.value }
        }
        refreshing = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                // Jan 1 last year: the feed's widest filter is YTD, and the
                // calendar strip can reach back three months across New Year.
                val since = LocalDate.of(LocalDate.now().year - 1, 1, 1)
                    .atStartOfDay(ZoneId.systemDefault()).toInstant().toString()
                // No routes: the phone feed never draws one (UX-X2).
                val actsD = async(Dispatchers.IO) { api.activitiesNoRoute(limit = 2000, since = since) }
                val woD = async(Dispatchers.IO) {
                    runCatching {
                        api.strengthWorkouts().workouts
                            .filter { it.status != "regenerated" && it.status != "planned" && it.status != "skipped" }
                            // A cardio day auto-completed by an activity: the
                            // activity is already in the feed.
                            .filter { !(it.splitFocus == "cardio" && it.completedByActivitySource != null) }
                    }.getOrNull()
                }
                val ytdD = async(Dispatchers.IO) { runCatching { api.activitiesYtd() }.getOrNull() }
                rows = actsD.await()
                woD.await()?.let { workouts = it }
                ytdD.await()?.let {
                    ytd = it
                    app.myvitals.data.JsonCache.write(context, "activities_ytd", ActivityYtd::class.java, it)
                }
                app.myvitals.data.JsonCache.write(context, "activities_feed", listT, rows)
                app.myvitals.data.JsonCache.write(context, "activities_workouts", woT, workouts)
            }
            error = null
            Timber.i("activities loaded: %d activities + %d strength", rows.size, workouts.size)
        } catch (e: Exception) {
            Timber.w(e, "activities load failed")
            error = e.message?.take(160) ?: "Couldn't reach the backend."
        } finally { loading = false; refreshing = false }
    }

    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) { refreshCookieStatus() }
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    // UI-F2 — the period row and records card for the selection on screen.
    // A newer selection cancels the older request; a failure keeps the last
    // figures and says so rather than rendering an empty period.
    fun loadSummary(since: LocalDate, category: String) {
        if (!settings.isConfigured()) return
        summaryJob?.cancel()
        summaryJob = scope.launch {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val cat = category.takeIf { it != "all" }
            val st = runCatching {
                withContext(Dispatchers.IO) { api.activitiesStatsFor(since = since.toString(), category = cat) }
            }
            val rec = if (category == "strength") Result.success(null) else runCatching {
                withContext(Dispatchers.IO) { api.activitiesRecords(category = cat, since = since.toString()) }
            }
            st.getOrNull()?.let { periodStats = it }
            if (rec.isSuccess) records = rec.getOrNull()
            summaryFailed = st.isFailure || rec.isFailure
            if (summaryFailed) Timber.w("activities period summary failed")
        }
    }

    ActivitiesContent(
        rows = rows, workouts = workouts, ytd = ytd,
        periodStats = periodStats, records = records, summaryFailed = summaryFailed,
        onSelection = { since, category -> loadSummary(since, category) },
        loading = loading, refreshing = refreshing, error = error,
        nowMs = nowMs, today = LocalDate.now(), zone = ZoneId.systemDefault(),
        contentPadding = PaddingValues(0.dp),
        strava = strava,
        onRefresh = { scope.launch { load() } },
        onSyncStrava = {
            scope.launch {
                strava = strava.copy(syncing = true)
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    val r = withContext(Dispatchers.IO) { api.stravaCookieSync() }
                    strava = strava.copy(toast = when {
                        r.error != null -> "Strava: ${r.error}"
                        r.upserted == 0 -> "Strava: up to date"
                        else -> "Strava: synced ${r.upserted}"
                    })
                    if (r.upserted > 0) load()
                    refreshCookieStatus()
                } catch (e: Exception) {
                    strava = strava.copy(toast = "Strava sync failed: ${e.message?.take(60)}")
                } finally { strava = strava.copy(syncing = false) }
            }
        },
        onOpenMap = onOpenMap,
        onOpenActivity = onOpenActivity,
        onOpenStrengthDay = onOpenStrengthDay,
        onBack = onBack,
    )
}

/**
 * Stateless feed. Everything a number on it says comes from the server:
 * the YTD hero and week headers from /activities/ytd, row values from the
 * activity or the strength session summary.
 */
@Composable
fun ActivitiesContent(
    rows: List<ActivityRow>,
    workouts: List<StrengthWorkoutSummary>,
    ytd: ActivityYtd?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    nowMs: Long,
    today: LocalDate,
    zone: ZoneId,
    contentPadding: PaddingValues,
    onRefresh: () -> Unit,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
    onOpenStrengthDay: (dateIso: String) -> Unit,
    onOpenMap: () -> Unit,
    strava: StravaUi = StravaUi(),
    onSyncStrava: () -> Unit = {},
    onBack: (() -> Unit)? = null,
    periodStats: ActivityStatsOut? = null,
    records: ActivityRecordsOut? = null,
    summaryFailed: Boolean = false,
    onSelection: (since: LocalDate, category: String) -> Unit = { _, _ -> },
    initialGroupByMonth: Boolean = false,
) {
    var rangeFilter by remember { mutableStateOf(RangeFilter.D90) }
    var typeFilter by remember { mutableStateOf(TypeFilter.ALL) }
    var groupByMonth by remember { mutableStateOf(initialGroupByMonth) }
    var shown by remember { mutableIntStateOf(PAGE) }
    LaunchedEffect(rangeFilter, typeFilter, today) {
        onSelection(rangeFilter.cutoff(today), typeFilter.key)
    }

    val feed = remember(rows, workouts) {
        (rows.map(FeedEntry::Activity) + workouts.map(FeedEntry::Strength))
            .sortedByDescending { it.sortKey }
    }
    val presentCategories = remember(rows) { rows.map { categoryForActivityType(it.type).key }.toSet() }
    val filtered = remember(feed, rangeFilter, typeFilter, today, zone) {
        val cutoff = rangeFilter.cutoff(today)
        feed.filter { e ->
            // Unparseable dates stay visible — a malformed timestamp must
            // never silently hide an item.
            val d = entryDay(e, zone)
            if (d != null && d.isBefore(cutoff)) return@filter false
            when (typeFilter) {
                TypeFilter.ALL -> true
                TypeFilter.STRENGTH -> e is FeedEntry.Strength
                else -> e is FeedEntry.Activity &&
                    categoryForActivityType(e.a.type).key == typeFilter.key
            }
        }
    }
    val weekTotals = remember(ytd) { ytd?.weeks?.associateBy { it.weekStart } ?: emptyMap() }
    val monthTotals = remember(ytd) { ytd?.months?.associateBy { it.monthStart } ?: emptyMap() }

    NeonScreen(
        title = "Activities",
        contentPadding = contentPadding,
        refreshing = refreshing && !loading,
        onRefresh = onRefresh,
        onBack = onBack,
        headerTrailing = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                NeonIconButton(Icons.Outlined.Map, "Activity map", onClick = onOpenMap)
                NeonIconButton(
                    Icons.Outlined.CloudDownload, "Sync Strava",
                    spinning = strava.syncing, enabled = !strava.syncing,
                    onClick = onSyncStrava,
                )
            }
        },
    ) {
        if (error != null) {
            StaleBanner(
                title = if (feed.isNotEmpty()) "Couldn't refresh — showing saved activities"
                        else "Couldn't load activities",
                message = error,
                onRetry = onRefresh,
            )
        }
        if (strava.needsReconnect) {
            StaleBanner(
                title = "Strava sync is disconnected",
                message = strava.cookieError
                    ?: "Reconnect Strava in Settings to resume pulling activities.",
            )
        }
        strava.toast?.let {
            Text(it, color = NeonMV.Muted, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp))
        }
        ytd?.thisWeek?.let { w ->
            Row(Modifier.padding(bottom = 12.dp)) {
                NeonPill("This week · ${w.sessions}")
                if (w.durationS > 0) {
                    Spacer(Modifier.width(8.dp))
                    NeonPill(fmtDurationHm(w.durationS), color = NeonMV.Periwinkle)
                }
            }
        }

        when {
            ytd != null -> YtdHero(ytd)
            loading -> NeonHeroCard(accent = NeonMV.Cyan) {
                NeonEyebrow("${today.year} year to date", Modifier.padding(top = 0.dp))
                Text("Loading the year…", color = NeonMV.Muted, fontSize = 13.sp)
            }
        }

        if (feed.isNotEmpty()) {
            CalendarStrip(rows, workouts, today)
            FilterBar(
                range = rangeFilter, onRange = { rangeFilter = it; shown = PAGE },
                type = typeFilter, onType = { typeFilter = it; shown = PAGE },
                present = presentCategories, hasWorkouts = workouts.isNotEmpty(),
                groupByMonth = groupByMonth, onGroupByMonth = { groupByMonth = it },
            )
            if (summaryFailed) {
                Text(
                    "Couldn't refresh the period totals" +
                        if (periodStats != null || records != null) " — showing the last ones loaded." else ".",
                    color = NeonMV.Amber, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp),
                )
            }
            periodStats?.let { PeriodStatsRow(it) }
            if (typeFilter != TypeFilter.STRENGTH) {
                records?.let { RecordsCard(it, periodStats?.periodLabel, onOpenActivity) }
            }
        }

        when {
            feed.isEmpty() && loading -> Text(
                "Loading activities…", color = NeonMV.Muted, fontSize = 13.sp,
                modifier = Modifier.padding(vertical = 12.dp),
            )
            // A failed load with nothing cached is NOT "no activities yet":
            // the banner above already says what happened.
            feed.isEmpty() && error != null -> Unit
            feed.isEmpty() -> QuietCard(
                "No activities yet. Connect Strava in Settings or log a strength workout.",
            )
            filtered.isEmpty() -> QuietCard("No activities match these filters.")
            else -> {
                val page = filtered.take(shown)
                var lastGroup: LocalDate? = null
                val thisWeek = today.minusDays((today.dayOfWeek.value - 1).toLong())
                val thisMonth = today.withDayOfMonth(1)
                page.forEach { e ->
                    val day = entryDay(e, zone)
                    val group = if (groupByMonth) day?.withDayOfMonth(1)
                        else day?.minusDays((day.dayOfWeek.value - 1).toLong())
                    if (group != null && group != lastGroup) {
                        lastGroup = group
                        if (groupByMonth) {
                            val t = monthTotals[group.toString()]
                            GroupHeader(
                                if (group == thisMonth) "This month" else group.format(MONTH_FMT),
                                t?.sessions, t?.durationS,
                            )
                        } else {
                            val t = weekTotals[group.toString()]
                            GroupHeader(
                                if (group == thisWeek) "This week" else "Week of ${group.format(WEEK_FMT)}",
                                t?.sessions, t?.durationS,
                            )
                        }
                    }
                    when (e) {
                        is FeedEntry.Activity -> ActivityFeedRow(e.a, zone) {
                            onOpenActivity(e.a.source, e.a.sourceId)
                        }
                        is FeedEntry.Strength -> StrengthFeedRow(e.w) {
                            onOpenStrengthDay(e.w.date)
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                }
                if (filtered.size > shown) {
                    Box(Modifier.fillMaxWidth().padding(vertical = 6.dp), contentAlignment = Alignment.Center) {
                        NeonPill(
                            "Show ${minOf(PAGE, filtered.size - shown)} more",
                            onClick = { shown += PAGE },
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

private const val PAGE = 40

@Composable
private fun QuietCard(text: String) {
    Text(
        text, color = NeonMV.Muted, fontSize = 14.sp,
        modifier = Modifier.fillMaxWidth()
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(16.dp),
    )
}

// ── YTD hero ─────────────────────────────────────────────────────────

private fun metricOf(y: ActivityYtd, key: String): YtdMetric? = y.metrics.firstOrNull { it.key == key }

/** "↓ 12%", "new", "level" — never an invented percentage. */
private fun deltaText(m: YtdMetric): String = when {
    m.note == "new" -> "new"
    m.pctChange == null || m.direction == "flat" -> "level"
    else -> (if (m.pctChange >= 0) "↑ " else "↓ ") + "%.0f%%".format(kotlin.math.abs(m.pctChange))
}

private fun fmtMetric(m: YtdMetric, v: Double): String = when (m.key) {
    "distance_m" -> "%,.0f".format(Units.distance(v) ?: 0.0)
    "elevation_m" -> "%,.0f".format(Units.elevation(v) ?: 0.0)
    "duration_s" -> "%,.0f".format(v / 3600.0)
    else -> "%,.0f".format(v)
}

private fun metricUnit(m: YtdMetric): String = when (m.key) {
    "distance_m" -> Units.distanceUnit
    "elevation_m" -> Units.elevationUnit
    "duration_s" -> "h"
    else -> ""
}

@Composable
private fun YtdHero(y: ActivityYtd) {
    val dist = metricOf(y, "distance_m")
    NeonHeroCard(accent = NeonMV.Cyan) {
        NeonEyebrow("${y.year} year to date", Modifier.padding(top = 0.dp))
        if (dist != null) {
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(fmtMetric(dist, dist.current), color = NeonMV.Cyan, size = 40)
                Spacer(Modifier.width(6.dp))
                Text(Units.distanceUnit, color = NeonMV.Muted, fontSize = 15.sp,
                    modifier = Modifier.padding(bottom = 6.dp))
                Spacer(Modifier.weight(1f))
                Text(deltaText(dist), color = toneColor(dist.tone), fontFamily = NeonNumberFamily,
                    fontSize = 15.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
            Text(
                "vs ${fmtMetric(dist, dist.prior)} ${Units.distanceUnit} by this day in ${y.priorYear}",
                color = NeonMV.Muted, fontSize = 12.sp,
            )
        }
        Spacer(Modifier.height(10.dp))
        CumulativeChart(y.cumulative.thisYear, y.cumulative.lastYear)
        Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
            LegendSwatch(NeonMV.Cyan, "${y.year}", dashed = false)
            Spacer(Modifier.width(14.dp))
            LegendSwatch(NeonMV.Periwinkle, "${y.priorYear}", dashed = true)
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            for (key in listOf("sessions", "duration_s", "elevation_m")) {
                val m = metricOf(y, key) ?: continue
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.Bottom) {
                        NeonNumber(fmtMetric(m, m.current), size = 20)
                        val u = metricUnit(m)
                        if (u.isNotEmpty()) {
                            Spacer(Modifier.width(3.dp))
                            Text(u, color = NeonMV.Muted, fontSize = 11.sp,
                                modifier = Modifier.padding(bottom = 3.dp))
                        }
                    }
                    Text(m.label, color = NeonMV.Muted, fontSize = 11.sp)
                    Text(deltaText(m), color = toneColor(m.tone), fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun LegendSwatch(color: Color, label: String, dashed: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Canvas(Modifier.width(18.dp).height(8.dp)) {
            drawLine(color, Offset(0f, size.height / 2), Offset(size.width, size.height / 2),
                strokeWidth = 2.dp.toPx(),
                pathEffect = if (dashed) PathEffect.dashPathEffect(floatArrayOf(6f, 5f)) else null)
        }
        Spacer(Modifier.width(5.dp))
        Text(label, color = NeonMV.Muted, fontSize = 11.sp)
    }
}

/** Cumulative distance this year (solid Cyan, to today) over last year
 *  (dashed Periwinkle, the whole year). Both series are server-computed. */
@Composable
private fun CumulativeChart(thisYear: List<Int>, lastYear: List<Int>) {
    val maxV = maxOf(thisYear.maxOrNull() ?: 0, lastYear.maxOrNull() ?: 0).coerceAtLeast(1)
    Canvas(Modifier.fillMaxWidth().height(96.dp)) {
        val w = size.width
        val h = size.height
        val days = 365f
        fun path(series: List<Int>): Path = Path().apply {
            series.forEachIndexed { i, v ->
                val x = w * (i / (days - 1))
                val y = h - h * (v.toFloat() / maxV)
                if (i == 0) moveTo(x, y) else lineTo(x, y)
            }
        }
        // Quarter gridlines so the slope reads against something.
        for (q in 1..3) {
            val x = w * q / 4f
            drawLine(NeonMV.Track, Offset(x, 0f), Offset(x, h), strokeWidth = 1f)
        }
        drawLine(NeonMV.Track, Offset(0f, h), Offset(w, h), strokeWidth = 1f)
        if (lastYear.size > 1) {
            drawPath(path(lastYear), NeonMV.Periwinkle.copy(alpha = 0.85f),
                style = Stroke(1.5.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
        }
        if (thisYear.size > 1) {
            drawPath(path(thisYear), NeonMV.Cyan.copy(alpha = 0.25f),
                style = Stroke(6.dp.toPx(), cap = StrokeCap.Round))
            drawPath(path(thisYear), NeonMV.Cyan,
                style = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round))
            val lastX = w * ((thisYear.size - 1) / (days - 1))
            val lastY = h - h * (thisYear.last().toFloat() / maxV)
            drawCircle(NeonMV.Cyan, 4.dp.toPx(), Offset(lastX, lastY))
        }
    }
    Row(Modifier.fillMaxWidth()) {
        for (m in listOf("Jan", "Apr", "Jul", "Oct")) {
            Text(m, color = NeonMV.Muted, fontSize = 10.sp, modifier = Modifier.weight(1f))
        }
    }
}

// ── Calendar: a 3-month strip that expands to the year ───────────────

@Composable
private fun CalendarStrip(
    rows: List<ActivityRow>,
    workouts: List<StrengthWorkoutSummary>,
    today: LocalDate,
) {
    var expanded by remember { mutableStateOf(false) }
    val index = remember(rows, workouts, today) {
        buildActivityCalendarIndex(rows, workouts, today.year - 1) +
            buildActivityCalendarIndex(rows, workouts, today.year)
    }
    Column(
        Modifier.fillMaxWidth().padding(bottom = 12.dp)
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (expanded) "${today.year} CALENDAR" else "LAST 3 MONTHS",
                color = NeonMV.Muted, fontFamily = NeonNumberFamily, fontSize = 11.sp,
                fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp,
                modifier = Modifier.weight(1f),
            )
            Text(
                if (expanded) "Show less" else "Show year",
                color = NeonMV.Cyan, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(8.dp))
                    .clickable { expanded = !expanded }
                    .heightIn(min = 32.dp)
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        if (expanded) {
            ActivityCalendarCard(rows = rows, workouts = workouts, neon = true,
                year = today.year, showCard = false)
        } else {
            val weeks = 13
            val lastMonday = today.minusDays((today.dayOfWeek.value - 1).toLong())
            val firstMonday = lastMonday.minusWeeks((weeks - 1).toLong())
            val empty = NeonMV.Track
            BoxWithConstraints(Modifier.fillMaxWidth()) {
                val gap = 3.dp
                // Capped so three months stays a strip, not a wall.
                val cell = ((maxWidth - gap * (weeks - 1)) / weeks).coerceAtMost(14.dp)
                val stripH = cell * 7 + gap * 6
                val stripW = cell * weeks + gap * (weeks - 1)
                Canvas(Modifier.width(stripW).height(stripH)) {
                    val c = cell.toPx(); val g = gap.toPx()
                    for (col in 0 until weeks) for (row in 0 until 7) {
                        val d = firstMonday.plusDays((col * 7 + row).toLong())
                        if (d.isAfter(today)) continue
                        val color = index[d.toString()]?.color(true) ?: empty
                        drawRoundRect(color, Offset(col * (c + g), row * (c + g)), Size(c, c),
                            cornerRadius = androidx.compose.ui.geometry.CornerRadius(3.dp.toPx()))
                    }
                }
            }
        }
    }
}

// ── Filter bar ──────────────────────────────────────────────────

@Composable
private fun FilterBar(
    range: RangeFilter,
    onRange: (RangeFilter) -> Unit,
    type: TypeFilter,
    onType: (TypeFilter) -> Unit,
    present: Set<String>,
    hasWorkouts: Boolean,
    groupByMonth: Boolean,
    onGroupByMonth: (Boolean) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(bottom = 6.dp)) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (r in RangeFilter.entries) FilterChip(r.label, r == range) { onRange(r) }
        }
        Spacer(Modifier.height(6.dp))
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (t in TypeFilter.entries) {
                // The web's rule: a chip only for a kind that is present.
                val show = when (t) {
                    TypeFilter.ALL -> true
                    TypeFilter.STRENGTH -> hasWorkouts
                    else -> t.key in present
                }
                if (show || t == type) FilterChip(t.label, t == type) { onType(t) }
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip("By week", !groupByMonth) { onGroupByMonth(false) }
            FilterChip("By month", groupByMonth) { onGroupByMonth(true) }
        }
    }
}

// ── UI-F2: period stats + personal records ────────────────────────────

/** Totals for the selected range + chip, straight from /activities/stats.
 *  A total no row in the window carried prints "—", never 0. */
@Composable
private fun PeriodStatsRow(st: ActivityStatsOut) {
    Column(Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 12.dp)) {
        NeonEyebrow(st.periodLabel)
        val dist = if (st.nWithDistance == 0) "—" else Units.fmtDistance(st.totalDistanceM, 0)
        val elev = if (st.nWithElevation == 0) "—" else Units.fmtElevation(st.totalElevationM)
        val kcal = if (st.nWithKcal == 0) "—" else "%,.0f".format(st.totalKcal)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NeonStatTile("%,d".format(st.nActivities),
                if (st.nActivities == 1) "session" else "sessions", Modifier.weight(1f))
            NeonStatTile(dist, "distance", Modifier.weight(1f))
            NeonStatTile(fmtDurationHm(st.totalDurationS.toInt()), "time", Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NeonStatTile(elev, "climbed", Modifier.weight(1f))
            NeonStatTile(kcal, "kcal", Modifier.weight(1f))
        }
    }
}

private val RECORD_DAY_FMT = DateTimeFormatter.ofPattern("MMM d, yyyy")

internal fun fmtRecordValue(r: ActivityRecord): String {
    val v = r.value ?: return "—"
    return when (r.key) {
        "longest_distance" -> Units.fmtDistance(v, 1)
        "longest_duration" -> fmtDurationHm(v.toInt())
        "most_elevation" -> Units.fmtElevation(v)
        "highest_suffer" -> "%.0f".format(v)
        "fastest" -> if (r.display == "pace") Units.fmtPace(v)
            else "%.1f %s/h".format(Units.distance(v * 3600.0) ?: 0.0, Units.distanceUnit)
        else -> "%.0f".format(v)
    }
}

/** Personal records over the selection. Each tile opens its activity; a
 *  record nothing qualifies for is left out (the server sends null, and
 *  a "0 km" record would read as a measured result). */
@Composable
private fun RecordsCard(
    rec: ActivityRecordsOut,
    periodLabel: String?,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
) {
    val shown = rec.records.filter { it.value != null && it.activity != null }
    Column(
        Modifier.fillMaxWidth().padding(bottom = 12.dp)
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(14.dp),
    ) {
        Text(
            "PERSONAL RECORDS" + (periodLabel?.let { " · ${it.uppercase()}" } ?: ""),
            color = NeonMV.Muted, fontFamily = NeonNumberFamily, fontSize = 11.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp,
        )
        Spacer(Modifier.height(10.dp))
        if (shown.isEmpty()) {
            Text("No records in this range yet.", color = NeonMV.Muted, fontSize = 13.sp)
        }
        shown.chunked(2).forEachIndexed { i, pair ->
            if (i > 0) Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (r in pair) {
                    val a = r.activity!!
                    val day = runCatching { LocalDate.parse(a.date).format(RECORD_DAY_FMT) }.getOrDefault(a.date)
                    Column(
                        Modifier.weight(1f).clip(NeonCardShape)
                            .clickable { onOpenActivity(a.source, a.sourceId) },
                    ) {
                        NeonStatTile(fmtRecordValue(r), r.label, Modifier.fillMaxWidth(), accent = NeonMV.Cyan)
                        Text(
                            a.name?.takeIf { it.isNotBlank() } ?: prettyType(a.type),
                            color = NeonMV.Ink, fontSize = 12.sp, maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().padding(top = 4.dp, start = 4.dp, end = 4.dp),
                        )
                        Text(
                            day, color = NeonMV.Muted, fontSize = 11.sp, maxLines = 1,
                            modifier = Modifier.padding(horizontal = 4.dp),
                        )
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

/** Cyan-tinted selected chip (the web `.chip.active` rule), 36dp tall. */
@Composable
private fun FilterChip(label: String, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(50)
    Box(
        Modifier
            .heightIn(min = 36.dp)
            .clip(shape)
            .background(if (selected) NeonMV.Cyan.copy(alpha = 0.14f) else NeonMV.Card, shape)
            .border(1.dp, if (selected) NeonMV.Cyan.copy(alpha = 0.45f) else NeonMV.Line, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (selected) NeonMV.Cyan else NeonMV.Muted, fontSize = 12.sp,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium)
    }
}

// ── Rows ────────────────────────────────────────────────────────

private val WEEK_FMT = DateTimeFormatter.ofPattern("MMM d")
private val MONTH_FMT = DateTimeFormatter.ofPattern("MMMM yyyy")
private val ROW_DAY_FMT = DateTimeFormatter.ofPattern("EEE MMM d")
private val ROW_TIME_FMT = DateTimeFormatter.ofPattern("EEE MMM d · h:mm a")

/** Week or month header. Totals are the server's (/activities/ytd weeks /
 *  months); null when the server has none for that group. */
@Composable
private fun GroupHeader(label: String, sessions: Int?, durationS: Int?) {
    Row(
        Modifier.fillMaxWidth().padding(top = 10.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label.uppercase(),
            color = NeonMV.Muted, fontFamily = NeonNumberFamily, fontSize = 11.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp, modifier = Modifier.weight(1f),
        )
        if (sessions != null && durationS != null) {
            Text(
                "$sessions session${if (sessions == 1) "" else "s"} · " +
                    fmtDurationHm(durationS),
                color = NeonMV.Muted, fontFamily = NeonNumberFamily, fontSize = 11.sp,
            )
        }
    }
}

/** One feed row: tinted icon, title + quiet subtitle, primary number on the
 *  right in the category tint. One radius (18dp) for every kind of row. */
@Composable
private fun FeedRow(
    icon: ImageVector,
    iconDesc: String,
    tint: Color,
    title: String,
    subtitle: String,
    primary: String,
    status: Pair<String, Color>? = null,
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth()
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(38.dp).clip(CircleShape).background(tint.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) { Icon(icon, contentDescription = iconDesc, tint = tint, modifier = Modifier.size(20.dp)) }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, color = NeonMV.Muted, fontSize = 12.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(10.dp))
        Column(horizontalAlignment = Alignment.End) {
            if (primary.isNotEmpty()) NeonNumber(primary, color = tint, size = 16)
            if (status != null) {
                Text(status.first, color = status.second, fontSize = 11.sp,
                    fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun ActivityFeedRow(a: ActivityRow, zone: ZoneId, onClick: () -> Unit) {
    val tint = categoryForActivityType(a.type).color(true)
    val whenStr = remember(a.startAt, zone) {
        runCatching { Instant.parse(a.startAt).atZone(zone).format(ROW_TIME_FMT) }.getOrDefault("")
    }
    val parts = buildList {
        if (whenStr.isNotEmpty()) add(whenStr)
        a.distanceM?.takeIf { it > 0 }?.let { add(Units.fmtDistance(it, 1)) }
        a.trailName?.let { add(it) }
    }
    FeedRow(
        icon = iconForType(a.type), iconDesc = prettyType(a.type), tint = tint,
        title = a.name?.takeIf { it.isNotBlank() } ?: prettyType(a.type),
        subtitle = parts.joinToString(" · "),
        primary = fmtDurationHm(a.durationS),
        onClick = onClick,
    )
}

private const val KG_PER_LB = 0.45359237

@Composable
private fun StrengthFeedRow(w: StrengthWorkoutSummary, onClick: () -> Unit) {
    val cat = categoryForSplitFocus(w.splitFocus)
    val icon = when (w.splitFocus) {
        "yoga" -> Icons.Outlined.SelfImprovement
        "cardio" -> Icons.AutoMirrored.Outlined.DirectionsBike
        else -> Icons.Outlined.FitnessCenter
    }
    val sm = w.sessionSummary
    // Tonnage is the number a lifting session is about; a yoga or cardio
    // day has none, so its time leads instead.
    val primary = when {
        sm != null && sm.totalVolumeLb > 0 ->
            "%,.0f".format(Units.weight(sm.totalVolumeLb * KG_PER_LB) ?: 0.0) + " " + Units.weightUnit
        sm?.netDurationS != null && sm.netDurationS > 0 -> fmtDurationHm(sm.netDurationS)
        // Unfinished: nothing to total yet, and a dash would read as "zero".
        else -> ""
    }
    val day = runCatching { LocalDate.parse(w.date).format(ROW_DAY_FMT) }.getOrDefault(w.date)
    val parts = buildList {
        add(day)
        add(muscleGroupsForFocus(w.splitFocus))
        sm?.takeIf { it.workingSets > 0 }?.let { add("${it.workingSets} sets") }
    }
    // Status only when it is not the ordinary "Complete".
    val status = when (w.status) {
        "completed" -> null
        "in_progress" -> "In progress" to NeonMV.Amber
        "paused" -> "Paused" to NeonMV.Amber
        else -> w.status.replace('_', ' ').replaceFirstChar { it.uppercase() } to NeonMV.Muted
    }
    FeedRow(
        icon = icon,
        iconDesc = when (w.splitFocus) { "yoga" -> "Yoga"; "cardio" -> "Cardio"; else -> "Strength" },
        tint = cat.color(true),
        title = when (w.splitFocus) {
            "yoga" -> "Yoga flow"
            "cardio" -> "Cardio day"
            else -> "${w.splitFocus.replace('_', ' ').replaceFirstChar { it.titlecase() }} day"
        },
        subtitle = parts.joinToString(" · "),
        primary = primary, status = status, onClick = onClick,
    )
}

private fun muscleGroupsForFocus(focus: String): String = when (focus.lowercase()) {
    "push" -> "Chest · Shoulders · Triceps"
    "pull" -> "Back · Biceps"
    "legs" -> "Quads · Hams · Glutes"
    "upper" -> "Chest · Back · Arms"
    "lower" -> "Quads · Hams · Glutes"
    "full_body", "fullbody", "full" -> "Full body"
    "yoga" -> "Mobility flow"
    "cardio" -> "Z2 effort"
    "rest" -> "Rest day"
    else -> focus.replace('_', ' ')
}

internal fun iconForType(type: String): ImageVector = when {
    // VR fitness (Les Mills VR, Supernatural, …) — check first so "vr"
    // isn't swallowed by a broader match.
    type.contains("vr", ignoreCase = true) -> Icons.Outlined.SportsEsports
    type.contains("Ride", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsBike
    type.contains("cycl", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsBike
    type.contains("Run", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsRun
    type.contains("Hike", ignoreCase = true) -> Icons.Outlined.Hiking
    type.contains("Walk", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsWalk
    type.contains("Row", ignoreCase = true) -> Icons.Outlined.Rowing
    type.contains("Ski", ignoreCase = true) -> Icons.Outlined.DownhillSkiing
    // Generic cardio (manual_cardio, elliptical, …) — a heart-rate glyph
    // beats defaulting every unknown to a bike (the Les Mills bug).
    else -> Icons.Outlined.MonitorHeart
}

internal fun prettyType(type: String): String =
    // "VirtualRide" → "Virtual Ride", and "yard_work" (the corrected-type
    // keys, migration 0069) → "Yard work".
    type.replace(Regex("([a-z])([A-Z])"), "$1 $2")
        .replace('_', ' ')
        .replaceFirstChar { it.uppercase() }

internal fun fmtAge(iso: String?, nowMs: Long): String {
    if (iso.isNullOrBlank()) return ""
    return try {
        val ms = nowMs - Instant.parse(iso).toEpochMilli()
        val m = ms / 60_000
        when {
            m < 1 -> "just now"
            m < 60 -> "${m}m ago"
            m < 60 * 24 -> "${m / 60}h ago"
            else -> "${m / (60 * 24)}d ago"
        }
    } catch (_: Exception) { "" }
}
