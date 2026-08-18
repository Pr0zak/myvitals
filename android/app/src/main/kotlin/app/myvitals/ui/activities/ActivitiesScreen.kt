package app.myvitals.ui.activities

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.CloudDownload
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Rowing
import androidx.compose.material.icons.outlined.SelfImprovement
import androidx.compose.material.icons.outlined.SportsEsports
import androidx.compose.material.icons.outlined.Warning
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
import app.myvitals.ui.neon.NeonMV
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

// ── Feed filters (client-side, on the already-loaded wide range) ──────

/** Date-range chips. Filters feed items by sortKey against a cutoff. */
private enum class RangeFilter(val label: String) {
    D7("7d"), D30("30d"), D90("90d"), YTD("YTD");

    /** Inclusive lower-bound epoch millis for the range; YTD = Jan 1 this year. */
    fun cutoffMs(nowMs: Long): Long = when (this) {
        D7 -> nowMs - 7L * 86_400_000L
        D30 -> nowMs - 30L * 86_400_000L
        D90 -> nowMs - 90L * 86_400_000L
        YTD -> java.time.LocalDate.of(java.time.LocalDate.now().year, 1, 1)
            .atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toEpochMilli()
    }
}

/** Type chips. "Strength" keeps the interleaved strength-workout items;
 *  the rest match ActivityRow.type via case-insensitive substring. */
private enum class TypeFilter(val label: String, val match: String?) {
    ALL("All", null),
    RIDE("Ride", "Ride"),
    RUN("Run", "Run"),
    WALK("Walk", "Walk"),
    HIKE("Hike", "Hike"),
    STRENGTH("Strength", null);
}

/** Parse an ISO sortKey to epoch millis; unparseable rows sort as "now"
 *  (kept visible) so a malformed timestamp never silently hides an item. */
private fun sortKeyMs(iso: String, nowMs: Long): Long = runCatching {
    java.time.OffsetDateTime.parse(iso).toInstant().toEpochMilli()
}.recoverCatching {
    java.time.LocalDate.parse(iso.take(10))
        .atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toEpochMilli()
}.getOrDefault(nowMs)

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun ActivitiesScreen(
    settings: SettingsRepository,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
    onOpenStrengthDay: (dateIso: String) -> Unit = {},
    onOpenMap: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    val neon = settings.neonShellEnabled
    // Client-side feed filters — default 90d / All.
    var rangeFilter by remember { mutableStateOf(RangeFilter.D90) }
    var typeFilter by remember { mutableStateOf(TypeFilter.ALL) }
    var rows by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var workouts by remember {
        mutableStateOf<List<app.myvitals.sync.StrengthWorkoutSummary>>(emptyList())
    }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    // SCS-4 Strava cookie-mode manual sync state.
    var stravaSyncing by remember { mutableStateOf(false) }
    var syncToast by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(syncToast) {
        if (syncToast != null) { delay(4000); syncToast = null }
    }
    // Cookie-session health — drives the reconnect banner. A dead cookie
    // syncs silently (0 rides, no error), so a stale ride count looks
    // identical to "no new rides". needsReconnect surfaces the outage.
    var stravaNeedsReconnect by remember { mutableStateOf(false) }
    var stravaCookieError by remember { mutableStateOf<String?>(null) }
    val context = androidx.compose.ui.platform.LocalContext.current

    suspend fun refreshCookieStatus() {
        if (!settings.isConfigured()) return
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) { api.stravaCookieStatus() }
        }.getOrNull()?.let {
            stravaNeedsReconnect = it.needsReconnect
            stravaCookieError = it.lastError
        }
    }

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
                        api.strengthWorkouts().workouts
                            .filter { it.status != "regenerated" && it.status != "planned" && it.status != "skipped" }
                            // Drop cardio days auto-completed by an Activity
                            // (Concept2 row, Strava bike). The underlying
                            // activity is already in the feed — would dupe.
                            .filter {
                                !(it.splitFocus == "cardio"
                                    && it.completedByActivitySource != null)
                            }
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

    // Only surface the Hike chip when there's actually a hike in range —
    // keeps the type row tight for users who never hike.
    val hasHike = remember(rows) {
        rows.any { it.type.contains("Hike", ignoreCase = true) }
    }

    // Apply the two filters client-side over the already-loaded wide range.
    val filteredFeed = remember(feed, rangeFilter, typeFilter, nowMs) {
        val cutoff = rangeFilter.cutoffMs(nowMs)
        feed.filter { entry ->
            if (sortKeyMs(entry.sortKey, nowMs) < cutoff) return@filter false
            when (typeFilter) {
                TypeFilter.ALL -> true
                TypeFilter.STRENGTH -> entry is FeedEntry.Strength
                else -> entry is FeedEntry.Activity &&
                    entry.a.type.contains(typeFilter.match!!, ignoreCase = true)
            }
        }
    }

    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) { refreshCookieStatus() }
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
                    else "${filteredFeed.size} shown",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onOpenMap) {
                    Icon(
                        Icons.Outlined.Map,
                        contentDescription = "Activity map",
                        tint = MV.OnSurface,
                    )
                }
                IconButton(
                    onClick = {
                        scope.launch {
                            stravaSyncing = true
                            try {
                                val api = app.myvitals.sync.BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                val r = withContext(kotlinx.coroutines.Dispatchers.IO) {
                                    api.stravaCookieSync()
                                }
                                syncToast = when {
                                    r.error != null -> "Strava: ${r.error}"
                                    r.upserted == 0 -> "Strava: up to date"
                                    else -> "Strava: synced ${r.upserted}"
                                }
                                if (r.upserted > 0) { loading = true; load() }
                                // A successful sync clears the banner; a dead
                                // cookie raises it. Re-read either way.
                                refreshCookieStatus()
                            } catch (e: Exception) {
                                syncToast = "Strava sync failed: ${e.message?.take(60)}"
                            } finally { stravaSyncing = false }
                        }
                    },
                    enabled = !stravaSyncing,
                ) {
                    if (stravaSyncing) {
                        androidx.compose.material3.CircularProgressIndicator(
                            modifier = Modifier.size(18.dp), strokeWidth = 2.dp,
                            color = MV.OnSurface,
                        )
                    } else {
                        Icon(Icons.Outlined.CloudDownload,
                            contentDescription = "Sync Strava",
                            tint = MV.OnSurface)
                    }
                }
                IconButton(onClick = { scope.launch { loading = true; load() } }, enabled = !loading) {
                    Icon(Icons.Outlined.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
                }
            }
        }
        // Strava sync toast — fades after 4s.
        syncToast?.let {
            Text(
                it,
                color = MV.OnSurfaceVariant, fontSize = 12.sp,
                modifier = Modifier.padding(bottom = 6.dp),
            )
        }

        // Reconnect banner — cookie session is dead, no new rides coming
        // in until the user re-establishes it in Settings → Strava.
        if (stravaNeedsReconnect) {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MV.Red.copy(alpha = 0.12f)),
                modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
            ) {
                Row(
                    Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Outlined.Warning, contentDescription = null,
                        tint = MV.Red, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text("Strava sync is disconnected",
                            color = MV.OnSurface, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold)
                        Text(
                            stravaCookieError
                                ?: "Reconnect Strava in Settings to resume pulling activities.",
                            color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    }
                }
            }
        }

        // Filter bar — two rows of compact chips (date range + type). Sits
        // above the list (and the YTD/heatmap cards, which stay unfiltered).
        // Hidden on a cold empty/loading state to avoid filtering nothing.
        if (feed.isNotEmpty()) {
            FilterBar(
                neon = neon,
                range = rangeFilter,
                onRange = { rangeFilter = it },
                type = typeFilter,
                onType = { typeFilter = it },
                hasHike = hasHike,
            )
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
                colors = CardDefaults.cardColors(containerColor = if (neon) NeonMV.Card else MV.SurfaceContainer),
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
                    YtdYoyCard(rows, workouts, neon)
                    Spacer(Modifier.height(8.dp))
                    // Shared with the Refined Train screen — see
                    // ui/common/ActivityCalendar.kt. Stays here because the
                    // classic and Vitality Neon shells have no Train hub
                    // that shows it.
                    app.myvitals.ui.common.ActivityCalendarCard(
                        rows = rows, workouts = workouts, neon = neon,
                        title = "${java.time.LocalDate.now().year} ACTIVITY CALENDAR",
                    )
                    Spacer(Modifier.height(8.dp))
                }
                if (filteredFeed.isEmpty()) {
                    item {
                        Card(
                            colors = CardDefaults.cardColors(containerColor = if (neon) NeonMV.Card else MV.SurfaceContainer),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                "No activities match these filters.",
                                Modifier.padding(14.dp), color = MV.OnSurfaceVariant,
                            )
                        }
                    }
                }
                items(
                    filteredFeed,
                    key = { entry ->
                        when (entry) {
                            is FeedEntry.Activity -> "act-${entry.a.source}-${entry.a.sourceId}"
                            is FeedEntry.Strength -> "str-${entry.w.id}"
                        }
                    },
                ) { entry ->
                    when (entry) {
                        is FeedEntry.Activity -> ActivityListRow(entry.a, nowMs, neon) {
                            onOpenActivity(entry.a.source, entry.a.sourceId)
                        }
                        is FeedEntry.Strength -> StrengthListRow(entry.w, nowMs, neon) {
                            onOpenStrengthDay(entry.w.date)
                        }
                    }
                }
            }
        }
        }  // end PullToRefreshBox
    }
}

// ── Filter bar ──────────────────────────────────────────────────

@Composable
private fun FilterBar(
    neon: Boolean,
    range: RangeFilter,
    onRange: (RangeFilter) -> Unit,
    type: TypeFilter,
    onType: (TypeFilter) -> Unit,
    hasHike: Boolean,
) {
    Column(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
        // Row 1 — date range. Fixed 4 chips fit without scrolling, but the
        // horizontalScroll keeps it safe on narrow displays / large fonts.
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (r in RangeFilter.entries) {
                FilterChip(
                    label = r.label,
                    selected = r == range,
                    neon = neon,
                    onClick = { onRange(r) },
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        // Row 2 — type. Hike chip only when a hike is present in the data.
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (t in TypeFilter.entries) {
                if (t == TypeFilter.HIKE && !hasHike) continue
                FilterChip(
                    label = t.label,
                    selected = t == type,
                    neon = neon,
                    onClick = { onType(t) },
                )
            }
        }
    }
}

/**
 * Compact pill chip, theme-aware. Neon selected state is a cyan TINT with
 * a 45% border (matching the web `.chip.active` rule) — a solid cyan slab
 * was the loudest element on the screen and read as a different design
 * system from the Train tab. Classic keeps its solid MV.BrandRed fill.
 */
@Composable
private fun FilterChip(
    label: String,
    selected: Boolean,
    neon: Boolean,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(50)
    // Neon selected state is a TINT, not a solid fill. A saturated cyan
    // slab was the loudest thing on the screen and read as a different
    // design system from the Train tab; this matches the web rule
    // `html[data-theme="neon"] .activities .chip.active`.
    val bg = when {
        selected && neon -> NeonMV.Cyan.copy(alpha = 0.14f)
        selected -> MV.BrandRed
        neon -> NeonMV.Card
        else -> MV.SurfaceContainer
    }
    val borderColor = when {
        selected && neon -> NeonMV.Cyan.copy(alpha = 0.45f)
        selected -> Color.Transparent
        neon -> NeonMV.Line
        else -> MV.OnSurfaceDim.copy(alpha = 0.35f)
    }
    val textColor = when {
        selected && neon -> NeonMV.Cyan
        selected -> Color.White
        neon -> NeonMV.Muted
        else -> MV.OnSurfaceVariant
    }
    Box(
        Modifier
            .clip(shape)
            .background(bg, shape)
            .border(1.dp, borderColor, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 7.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = textColor,
            fontSize = 12.sp,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
        )
    }
}

@Composable
private fun StrengthListRow(
    w: app.myvitals.sync.StrengthWorkoutSummary,
    nowMs: Long,
    neon: Boolean,
    onClick: () -> Unit,
) {
    val whenStr = remember(nowMs, w.startedAt, w.date) {
        fmtAge(w.startedAt ?: (w.date + "T00:00:00Z"), nowMs)
    }
    val statusColor = when (w.status) {
        "completed" -> if (neon) NeonMV.Lime else androidx.compose.ui.graphics.Color(0xFF22C55E)
        "in_progress" -> if (neon) NeonMV.Amber else androidx.compose.ui.graphics.Color(0xFFEAB308)
        "skipped" -> if (neon) NeonMV.Muted else MV.OnSurfaceDim
        "planned" -> if (neon) NeonMV.Cyan else MV.BrandRed
        else -> if (neon) NeonMV.Muted else MV.OnSurfaceVariant
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
            containerColor = if (neon) NeonMV.Card else MV.SurfaceContainer,
        ),
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Distinguish the three workout types — cardio days were
            // showing the strength dumbbell, which was visually
            // misleading (they're rest-style days that auto-log via
            // Concept2 ERG / Strava, not strength sessions).
            val typeIcon = when (w.splitFocus) {
                "yoga" -> androidx.compose.material.icons.Icons.Outlined.SelfImprovement
                "cardio" -> androidx.compose.material.icons.Icons.AutoMirrored.Outlined.DirectionsBike
                else -> androidx.compose.material.icons.Icons.Outlined.FitnessCenter
            }
            // Shared palette — the same colour this workout gets on the
            // activity calendar. Brand-red strength icons inside an obsidian
            // shell were the single biggest "different app" tell.
            val typeTint = app.myvitals.ui.common
                .categoryForSplitFocus(w.splitFocus).color(neon)
            val typeDesc = when (w.splitFocus) {
                "yoga" -> "Yoga"
                "cardio" -> "Cardio"
                else -> "Strength"
            }
            Box(
                Modifier.size(32.dp).clip(CircleShape)
                    .background(
                        if (neon) typeTint.copy(alpha = 0.13f)
                        else MV.SurfaceContainerLow,
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    typeIcon, contentDescription = typeDesc, tint = typeTint,
                    modifier = Modifier.size(18.dp),
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    when (w.splitFocus) {
                        "yoga" -> "Yoga flow"
                        "cardio" -> "Cardio day"
                        else -> "${w.splitFocus.replaceFirstChar { it.titlecase() }} day"
                    },
                    color = if (neon) NeonMV.Ink else MV.OnSurface, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, maxLines = 1,
                )
                Text(
                    "$whenStr  ·  ${muscleGroupsForFocus(w.splitFocus)}",
                    color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
                    fontSize = 11.sp, maxLines = 1,
                )
                // TD-4 — what the session actually cost. Lifting used to
                // contribute nothing to the energy picture on either surface,
                // and the duration shown in feeds was gross elapsed time
                // rather than the net figure the training-load model uses.
                w.sessionSummary?.let { sm ->
                    val parts = buildList {
                        sm.netDurationS?.takeIf { it > 0 }?.let { add(fmtDurationHm(it)) }
                        if (sm.workingSets > 0) add("${sm.workingSets} sets")
                        if (sm.totalVolumeLb > 0) add("%,.0f lb".format(sm.totalVolumeLb))
                        sm.kcalEst?.let {
                            // Name the input rather than just hedging with
                            // "est" — it tells the user how much to trust it.
                            val how = if (sm.kcalMethod == "hr") "from HR" else "estimated"
                            add("~%.0f kcal (%s)".format(it, how))
                        }
                    }
                    if (parts.isNotEmpty()) {
                        Text(
                            parts.joinToString("  ·  "),
                            color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
                            fontSize = 11.sp, maxLines = 1,
                        )
                    }
                }
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
    "yoga" -> "Mobility flow"
    "cardio" -> "Z2 effort"
    "rest" -> "Rest day"
    else -> focus.replace('_', ' ')
}

@Composable
private fun ActivityListRow(
    a: ActivityRow, nowMs: Long, neon: Boolean, onClick: () -> Unit,
) {
    val icon = iconForType(a.type)
    // Same category colour the calendar paints this activity with.
    val cat = app.myvitals.ui.common.categoryForActivityType(a.type)
    val tint = cat.color(neon)
    val title = a.name?.takeIf { it.isNotBlank() } ?: prettyType(a.type)
    val ageStr = remember(nowMs, a.startAt) { fmtAge(a.startAt, nowMs) }
    val miles = a.distanceM?.let { "%.1f mi".format(it / 1609.34) } ?: "—"
    val mins = a.durationS / 60
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (neon) NeonMV.Card else MV.SurfaceContainer,
        ),
        shape = if (neon) RoundedCornerShape(15.dp) else CardDefaults.shape,
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(32.dp).clip(CircleShape).background(
                    if (neon) tint.copy(alpha = 0.13f) else MV.SurfaceContainerLow,
                ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = a.type,
                    tint = if (neon) tint else MV.OnSurface,
                    modifier = Modifier.size(18.dp))
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(title, color = if (neon) NeonMV.Ink else MV.OnSurface,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, maxLines = 1)
                Text("$ageStr  ·  $miles  ·  ${mins}m",
                    color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
                    fontSize = 11.sp)
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
    neon: Boolean,
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
            // TD-4 — the server's net duration, which subtracts accumulated
            // pause. This used to parse the two timestamps and take the gross
            // elapsed time, so a session left open on the rack inflated the
            // year-over-year comparison.
            target.duration += (w.sessionSummary?.netDurationS ?: 0).toLong()
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
        colors = CardDefaults.cardColors(containerColor = if (neon) NeonMV.Card else MV.SurfaceContainer),
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
                    neon = neon,
                    modifier = Modifier.weight(1f),
                )
                YtdCell(
                    value = "%.0f".format(ytd.distance / 1609.344) + " mi",
                    label = "distance",
                    prev = "%.0f".format(lyr.distance / 1609.344) + "mi",
                    pct = pctD(ytd.distance, lyr.distance),
                    neon = neon,
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
                    neon = neon,
                    modifier = Modifier.weight(1f),
                )
                if (ytd.elevation > 0 || lyr.elevation > 0) {
                    YtdCell(
                        value = "%.0f".format(ytd.elevation) + "m",
                        label = "climbed",
                        prev = "%.0f".format(lyr.elevation) + "m last yr",
                        pct = pctD(ytd.elevation, lyr.elevation),
                        neon = neon,
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
    neon: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
            .background(if (neon) NeonMV.Bg else Color(0x141A2332))
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        if (neon) {
            app.myvitals.ui.neon.NeonNumber(value, size = 18, color = NeonMV.Ink)
        } else {
            Text(value, color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.Light)
        }
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
