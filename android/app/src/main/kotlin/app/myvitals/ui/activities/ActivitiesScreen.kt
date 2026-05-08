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
                val actsD = async(Dispatchers.IO) { api.activities(limit = 80) }
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
