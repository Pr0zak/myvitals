package app.myvitals.ui.activities

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.automirrored.outlined.DirectionsWalk
import androidx.compose.material.icons.outlined.DownhillSkiing
import androidx.compose.material.icons.outlined.Hiking
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Rowing
import androidx.compose.material.icons.outlined.SelfImprovement
import androidx.compose.ui.graphics.Color
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

// Combined feed entry — either a Strava-style activity or a strength
// workout. Displayed sorted by most-recent date, with different rows.
sealed class FeedEntry {
    abstract val sortKey: String  // ISO datetime string, descending sort
    data class Activity(val a: ActivityRow) : FeedEntry() {
        override val sortKey = a.startAt
    }
    data class Strength(val w: app.myvitals.sync.StrengthWorkoutSummary) : FeedEntry() {
        override val sortKey = w.startedAt ?: w.completedAt ?: (w.date + "T00:00:00Z")
    }
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun ActivitiesScreen(
    settings: SettingsRepository,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
    onOpenStrengthDay: (dateIso: String) -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var workouts by remember {
        mutableStateOf<List<app.myvitals.sync.StrengthWorkoutSummary>>(emptyList())
    }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val context = androidx.compose.ui.platform.LocalContext.current

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."; loading = false; return
        }
        // Stale-while-revalidate cache for instant render.
        val cachedRows = app.myvitals.data.JsonCache.read<List<ActivityRow>>(
            context, "activities_feed",
            app.myvitals.data.JsonCache.listType(ActivityRow::class.java),
        )
        val cachedWorkouts = app.myvitals.data.JsonCache.read<List<app.myvitals.sync.StrengthWorkoutSummary>>(
            context, "activities_workouts",
            app.myvitals.data.JsonCache.listType(app.myvitals.sync.StrengthWorkoutSummary::class.java),
        )
        if (cachedRows != null) {
            rows = cachedRows.value
            workouts = cachedWorkouts?.value ?: emptyList()
            loading = false
            refreshing = true
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                // Pull from Jan 1 last year so the YTD + YoY card can
                // compute "this year vs same period last year" without
                // a second round-trip. ~18 months covers any user.
                val ytdSince = java.time.LocalDate.of(
                    java.time.LocalDate.now().year - 1, 1, 1,
                ).atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toString()
                val actsD = async(Dispatchers.IO) {
                    api.activities(limit = 2000, since = ytdSince)
                }
                val woD = async(Dispatchers.IO) {
                    runCatching {
                        api.strengthWorkouts().workouts.filter { it.status != "regenerated" }
                    }.getOrDefault(emptyList())
                }
                rows = actsD.await()
                workouts = woD.await()

                app.myvitals.data.JsonCache.write(
                    context, "activities_feed",
                    app.myvitals.data.JsonCache.listType(ActivityRow::class.java), rows,
                )
                app.myvitals.data.JsonCache.write(
                    context, "activities_workouts",
                    app.myvitals.data.JsonCache.listType(
                        app.myvitals.sync.StrengthWorkoutSummary::class.java),
                    workouts,
                )
            }
            error = null
            Timber.i("activities loaded: %d strava + %d strength workouts",
                rows.size, workouts.size)
        } catch (e: Exception) {
            Timber.w(e, "activities load failed")
            error = e.message?.take(160)
        } finally { loading = false; refreshing = false }
    }

    val feed = remember(rows, workouts) {
        (rows.map(FeedEntry::Activity) + workouts.map(FeedEntry::Strength))
            .sortedByDescending { it.sortKey }
    }

    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    Column(Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 16.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("ACTIVITIES",
                        color = MV.OnSurfaceVariant,
                        fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                    if (refreshing) {
                        Spacer(Modifier.width(8.dp))
                        Text("refreshing…",
                            color = MV.OnSurfaceVariant, fontSize = 10.sp)
                    }
                }
                Text(
                    if (feed.isEmpty() && !loading) "—"
                    else "${feed.size} recent",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            IconButton(onClick = { scope.launch { loading = true; load() } }, enabled = !loading) {
                Icon(Icons.Outlined.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
            }
        }

        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = loading,
            onRefresh = { scope.launch { loading = true; load() } },
            modifier = Modifier.weight(1f),
        ) {
        when {
            loading && feed.isEmpty() -> Text("Loading…", color = MV.OnSurfaceVariant)
            error != null -> Text(error!!, color = MV.Red)
            feed.isEmpty() -> Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "No activities yet. Connect Strava in Settings or log a strength workout.",
                    Modifier.padding(14.dp), color = MV.OnSurfaceVariant,
                )
            }
            else -> LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                item {
                    YtdYoyCard(rows, workouts)
                    Spacer(Modifier.height(8.dp))
                    ActivityCalendarStrip(rows, workouts)
                    Spacer(Modifier.height(8.dp))
                }
                items(
                    feed,
                    key = { entry ->
                        when (entry) {
                            is FeedEntry.Activity -> "act-${entry.a.source}-${entry.a.sourceId}"
                            is FeedEntry.Strength -> "str-${entry.w.id}"
                        }
                    },
                ) { entry ->
                    when (entry) {
                        is FeedEntry.Activity -> ActivityListRow(entry.a, nowMs) {
                            onOpenActivity(entry.a.source, entry.a.sourceId)
                        }
                        is FeedEntry.Strength -> StrengthListRow(entry.w, nowMs) {
                            onOpenStrengthDay(entry.w.date)
                        }
                    }
                }
            }
        }
        }  // end PullToRefreshBox
    }
}

@Composable
private fun StrengthListRow(
    w: app.myvitals.sync.StrengthWorkoutSummary,
    nowMs: Long,
    onClick: () -> Unit,
) {
    val whenStr = remember(nowMs, w.startedAt, w.date) {
        fmtAge(w.startedAt ?: (w.date + "T00:00:00Z"), nowMs)
    }
    val statusColor = when (w.status) {
        "completed" -> androidx.compose.ui.graphics.Color(0xFF22C55E)
        "in_progress" -> androidx.compose.ui.graphics.Color(0xFFEAB308)
        "skipped" -> MV.OnSurfaceDim
        "planned" -> MV.BrandRed
        else -> MV.OnSurfaceVariant
    }
    val statusLabel = when (w.status) {
        "completed" -> "Complete"
        "in_progress" -> "In progress"
        "skipped" -> "Skipped"
        "planned" -> "Planned"
        else -> w.status
    }
    androidx.compose.material3.Card(
        colors = androidx.compose.material3.CardDefaults.cardColors(
            containerColor = MV.SurfaceContainer,
        ),
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val isYoga = w.splitFocus == "yoga"
            Box(
                Modifier.size(32.dp).clip(CircleShape)
                    .background(MV.SurfaceContainerLow),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (isYoga)
                        androidx.compose.material.icons.Icons.Outlined.SelfImprovement
                    else
                        androidx.compose.material.icons.Icons.Outlined.FitnessCenter,
                    contentDescription = if (isYoga) "Yoga" else "Strength",
                    tint = if (isYoga) Color(0xFFA78BFA) else MV.BrandRed,
                    modifier = Modifier.size(18.dp),
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    if (isYoga) "Yoga flow"
                    else "${w.splitFocus.replaceFirstChar { it.titlecase() }} day",
                    color = MV.OnSurface, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, maxLines = 1,
                )
                Text(
                    "$whenStr  ·  ${muscleGroupsForFocus(w.splitFocus)}",
                    color = MV.OnSurfaceVariant, fontSize = 11.sp, maxLines = 1,
                )
            }
            Text(
                statusLabel, color = statusColor, fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

private fun muscleGroupsForFocus(focus: String): String = when (focus.lowercase()) {
    "push" -> "Chest · Shoulders · Triceps"
    "pull" -> "Back · Biceps"
    "legs" -> "Quads · Hams · Glutes"
    "upper" -> "Chest · Back · Arms"
    "lower" -> "Quads · Hams · Glutes"
    "full_body", "fullbody", "full" -> "Full body"
    "rest" -> "Rest day"
    else -> focus.replace('_', ' ')
}

@Composable
private fun ActivityListRow(a: ActivityRow, nowMs: Long, onClick: () -> Unit) {
    val icon = iconForType(a.type)
    val title = a.name?.takeIf { it.isNotBlank() } ?: prettyType(a.type)
    val ageStr = remember(nowMs, a.startAt) { fmtAge(a.startAt, nowMs) }
    val miles = a.distanceM?.let { "%.1f mi".format(it / 1609.34) } ?: "—"
    val mins = a.durationS / 60
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(32.dp).clip(CircleShape).background(MV.SurfaceContainerLow),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = a.type,
                    tint = MV.OnSurface, modifier = Modifier.size(18.dp))
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(title, color = MV.OnSurface, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, maxLines = 1)
                Text("$ageStr  ·  $miles  ·  ${mins}m",
                    color = MV.OnSurfaceVariant, fontSize = 11.sp)
            }
            if (a.trailName != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Link, contentDescription = "Linked",
                        tint = MV.OnSurfaceVariant, modifier = Modifier.size(12.dp))
                    Spacer(Modifier.width(4.dp))
                    Text(a.trailName, color = MV.OnSurfaceVariant, fontSize = 11.sp,
                        fontWeight = FontWeight.Medium, maxLines = 1)
                }
            }
        }
    }
}

internal fun iconForType(type: String): ImageVector = when {
    type.contains("Ride", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsBike
    type.contains("Run", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsRun
    type.contains("Hike", ignoreCase = true) -> Icons.Outlined.Hiking
    type.contains("Walk", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsWalk
    type.contains("Row", ignoreCase = true) -> Icons.Outlined.Rowing
    type.contains("Ski", ignoreCase = true) -> Icons.Outlined.DownhillSkiing
    else -> Icons.AutoMirrored.Outlined.DirectionsBike
}

internal fun prettyType(type: String): String =
    type.replace(Regex("([a-z])([A-Z])"), "$1 $2")

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

// ── YTD / YoY ─────────────────────────────────────────────────

private data class YtdBucket(
    var n: Int = 0,
    var distance: Double = 0.0,
    var duration: Long = 0L,
    var elevation: Double = 0.0,
)

@Composable
private fun YtdYoyCard(
    rows: List<ActivityRow>,
    workouts: List<app.myvitals.sync.StrengthWorkoutSummary>,
) {
    val now = remember { java.time.LocalDate.now() }
    val thisYear = now.year
    val lastYear = thisYear - 1
    val endOfLastYear = remember { java.time.LocalDate.of(lastYear, now.monthValue, now.dayOfMonth) }

    val (ytd, lyr) = remember(rows, workouts) {
        val a = YtdBucket(); val b = YtdBucket()
        // Strava + import activities
        for (r in rows) {
            val d = runCatching {
                java.time.OffsetDateTime.parse(r.startAt).toLocalDate()
            }.getOrNull() ?: continue
            val target = when {
                d.year == thisYear && !d.isAfter(now) -> a
                d.year == lastYear && !d.isAfter(endOfLastYear) -> b
                else -> null
            } ?: continue
            target.n += 1
            target.distance += r.distanceM ?: 0.0
            target.duration += r.durationS
            target.elevation += r.elevationGainM ?: 0.0
        }
        // Strength workouts
        for (w in workouts) {
            if (w.status != "completed") continue
            val d = runCatching { java.time.LocalDate.parse(w.date) }.getOrNull() ?: continue
            val target = when {
                d.year == thisYear && !d.isAfter(now) -> a
                d.year == lastYear && !d.isAfter(endOfLastYear) -> b
                else -> null
            } ?: continue
            target.n += 1
            // started_at + completed_at gives a duration; fall back to 0
            val started = w.startedAt
            val completed = w.completedAt
            if (started != null && completed != null) {
                target.duration += runCatching {
                    java.time.Duration.between(
                        java.time.OffsetDateTime.parse(started).toInstant(),
                        java.time.OffsetDateTime.parse(completed).toInstant(),
                    ).seconds
                }.getOrDefault(0L)
            }
        }
        a to b
    }

    fun pct(now: Int, prev: Int): Double {
        if (prev == 0) return if (now == 0) 0.0 else 100.0
        return ((now - prev).toDouble() / prev) * 100.0
    }
    fun pctD(now: Double, prev: Double): Double {
        if (prev == 0.0) return if (now == 0.0) 0.0 else 100.0
        return ((now - prev) / prev) * 100.0
    }
    fun pctL(now: Long, prev: Long): Double {
        if (prev == 0L) return if (now == 0L) 0.0 else 100.0
        return ((now - prev).toDouble() / prev) * 100.0
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                "${thisYear} YEAR-TO-DATE · vs ${lastYear}",
                color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
                modifier = Modifier.padding(bottom = 8.dp),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                YtdCell(
                    value = "${ytd.n}",
                    label = "activities",
                    prev = "${lyr.n} last yr",
                    pct = pct(ytd.n, lyr.n),
                    modifier = Modifier.weight(1f),
                )
                YtdCell(
                    value = "%.0f".format(ytd.distance / 1609.344) + " mi",
                    label = "distance",
                    prev = "%.0f".format(lyr.distance / 1609.344) + "mi",
                    pct = pctD(ytd.distance, lyr.distance),
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                YtdCell(
                    value = "${ytd.duration / 3600}h",
                    label = "moving time",
                    prev = "${lyr.duration / 3600}h last yr",
                    pct = pctL(ytd.duration, lyr.duration),
                    modifier = Modifier.weight(1f),
                )
                if (ytd.elevation > 0 || lyr.elevation > 0) {
                    YtdCell(
                        value = "%.0f".format(ytd.elevation) + "m",
                        label = "climbed",
                        prev = "%.0f".format(lyr.elevation) + "m last yr",
                        pct = pctD(ytd.elevation, lyr.elevation),
                        modifier = Modifier.weight(1f),
                    )
                } else {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun YtdCell(
    value: String, label: String, prev: String, pct: Double,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
            .background(Color(0x141A2332))
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Text(value, color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.Light)
        Text(
            label, color = MV.OnSurfaceVariant, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
            modifier = Modifier.padding(top = 2.dp),
        )
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(prev, color = MV.OnSurfaceDim, fontSize = 10.sp, modifier = Modifier.weight(1f))
            val arrow = if (pct >= 0) "↑" else "↓"
            Text(
                "$arrow ${"%.0f".format(kotlin.math.abs(pct))}%",
                color = if (pct >= 0) MV.Green else MV.Red,
                fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

// ── Calendar strip ──────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ActivityCalendarStrip(
    rows: List<ActivityRow>,
    workouts: List<app.myvitals.sync.StrengthWorkoutSummary>,
) {
    val year = java.time.LocalDate.now().year
    // Bucket: ISO date → category. Activity types map to a color band.
    val byDate = remember(rows, workouts) {
        val m = mutableMapOf<String, String>()
        for (r in rows) {
            val d = runCatching {
                java.time.OffsetDateTime.parse(r.startAt).toLocalDate()
            }.getOrNull() ?: continue
            if (d.year != year) continue
            // Cycling-ish > running > walking > other; first match wins per day
            val cat = when (r.type.lowercase()) {
                "ride", "ebikeride", "mountain_biking", "cycling" -> "ride"
                "run", "trailrun", "running" -> "run"
                "hike", "walk", "walking" -> "walk"
                "rower", "rowing", "row" -> "row"
                else -> "other"
            }
            m.putIfAbsent(d.toString(), cat)
        }
        for (w in workouts) {
            if (w.status != "completed") continue
            val d = runCatching { java.time.LocalDate.parse(w.date) }.getOrNull() ?: continue
            if (d.year != year) continue
            val cat = if (w.splitFocus.lowercase() == "yoga") "yoga" else "strength"
            // Activities take precedence visually if both happened that day
            m.putIfAbsent(d.toString(), cat)
        }
        m.toMap()
    }
    if (byDate.isEmpty()) return
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                "${year} ACTIVITY CALENDAR",
                color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
            )
            Spacer(Modifier.height(8.dp))
            CalendarYearStrip(year, byDate)
            Spacer(Modifier.height(8.dp))
            // Legend
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                LegendChip(Color(0xFFEF4444), "Strength")
                LegendChip(Color(0xFFA78BFA), "Yoga")
                LegendChip(Color(0xFF38BDF8), "Ride")
                LegendChip(Color(0xFF22C55E), "Run")
                LegendChip(Color(0xFFF59E0B), "Walk")
            }
        }
    }
}

@Composable
private fun LegendChip(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        androidx.compose.foundation.layout.Box(
            Modifier
                .size(8.dp)
                .background(color, androidx.compose.foundation.shape.CircleShape),
        )
        Spacer(Modifier.width(3.dp))
        Text(label, color = MV.OnSurfaceVariant, fontSize = 9.sp)
    }
}

@Composable
private fun CalendarYearStrip(year: Int, byDate: Map<String, String>) {
    val firstDay = remember(year) { java.time.LocalDate.of(year, 1, 1) }
    val daysInYear = remember(year) { firstDay.lengthOfYear() }
    val cellSize = 10.dp
    val cellGap = 2.dp
    Canvas(
        modifier = Modifier
            .height((cellSize.value * 7 + cellGap.value * 6).dp)
            .fillMaxWidth(),
    ) {
        val cellPx = cellSize.toPx()
        val gapPx = cellGap.toPx()
        val totalCols = 53
        val startDow = firstDay.dayOfWeek.value % 7  // ISO Mon=1..Sun=7 → Sun=0
        for (i in 0 until daysInYear) {
            val date = firstDay.plusDays(i.toLong())
            val col = (i + startDow) / 7
            val row = (i + startDow) % 7
            if (col >= totalCols) break
            val isoDate = date.toString()
            val cat = byDate[isoDate]
            val color = when (cat) {
                "strength" -> Color(0xFFEF4444)
                "yoga" -> Color(0xFFA78BFA)
                "ride" -> Color(0xFF38BDF8)
                "run" -> Color(0xFF22C55E)
                "walk" -> Color(0xFFF59E0B)
                "row" -> Color(0xFF06B6D4)
                "other" -> Color(0xFF94A3B8)
                else -> Color(0x141A2332)
            }
            val x = col * (cellPx + gapPx)
            val y = row * (cellPx + gapPx)
            drawRect(
                color = color,
                topLeft = androidx.compose.ui.geometry.Offset(x, y),
                size = androidx.compose.ui.geometry.Size(cellPx, cellPx),
            )
        }
    }
}
