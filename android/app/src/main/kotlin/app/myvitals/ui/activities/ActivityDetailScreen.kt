package app.myvitals.ui.activities

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Category
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import app.myvitals.data.SettingsRepository
import app.myvitals.data.Units
import app.myvitals.sync.ActivityLinkTrailBody
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.ActivityZones
import app.myvitals.sync.BackendClient
import app.myvitals.sync.TimePoint
import app.myvitals.sync.Trail
import app.myvitals.ui.MV
import app.myvitals.ui.common.categoryForActivityType
import app.myvitals.ui.common.userMessage
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonNumberFamily
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/*
 * Activity detail (UI-5) — map first.
 *
 *  - The route is the first thing on the screen: a 300dp map card with a
 *    scrim carrying the type, name and local start time. No route → a
 *    category-tinted gradient card in its place, not a hole.
 *  - Eight identical stat tiles became three big numbers (distance, time,
 *    and pace for foot sports or average HR otherwise) over a quiet line.
 *  - Max HR was painted in the crisis colour though nothing was wrong. It
 *    is Ink, or Amber when the session reached the top zone.
 *  - Zone colours were hex copies; they are NeonMV tokens, and the chart's
 *    bands are the server's zone boundaries (ActivityHrChart.kt).
 *  - Elevation printed "ft" and pace "/mi" whatever the unit setting; both
 *    go through Units now.
 *  - A failed edit set the same `error` that replaced the loaded view, so a
 *    typo in a duration made the whole activity disappear. Edit failures are
 *    an inline banner above the content.
 *  - The unused Vico HrChart is gone.
 */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityDetailScreen(
    settings: SettingsRepository,
    source: String,
    sourceId: String,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    var activity by remember { mutableStateOf<ActivityRow?>(null) }
    var trails by remember { mutableStateOf<List<Trail>>(emptyList()) }
    var hrPoints by remember { mutableStateOf<List<TimePoint>>(emptyList()) }
    var zones by remember { mutableStateOf<ActivityZones?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    // Failures of an ACTION on a loaded activity. Never replaces the view.
    var notice by remember { mutableStateOf<String?>(null) }
    var showPicker by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var showEdit by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf(false) }
    // Type correction — any source (migration 0069).
    var showTypeEdit by remember { mutableStateOf(false) }
    var typeChoices by remember { mutableStateOf<List<app.myvitals.sync.ActivityTypeChoice>>(emptyList()) }
    var savingType by remember { mutableStateOf(false) }
    var typeError by remember { mutableStateOf<String?>(null) }

    val cacheKey = remember(source, sourceId) { "activity_detail_${source}_${sourceId}" }

    fun saveType(body: app.myvitals.sync.ActivityEditBody) {
        val a = activity ?: return
        if (savingType) return
        savingType = true
        typeError = null
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val updated = withContext(Dispatchers.IO) {
                    api.editActivity(source = a.source, sourceId = a.sourceId, body = body)
                }
                activity = updated
                app.myvitals.data.JsonCache.write(context, cacheKey, ActivityRow::class.java, updated)
                showTypeEdit = false
            } catch (e: Exception) {
                Timber.w(e, "activity type change failed")
                typeError = e.userMessage("Could not change the type")
                // The Undo on the page has no dialog to report into.
                if (!showTypeEdit) notice = typeError
            } finally { savingType = false }
        }
    }

    suspend fun load() {
        // Serve cached activity immediately so the screen renders offline.
        app.myvitals.data.JsonCache.read<ActivityRow>(context, cacheKey, ActivityRow::class.java)
            ?.let { activity = it.value; loading = false }
        if (!settings.isConfigured()) {
            if (activity == null) error = "Backend not configured."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val (a, ts) = withContext(Dispatchers.IO) {
                Pair(api.activity(source, sourceId), api.trails())
            }
            activity = a
            app.myvitals.data.JsonCache.write(context, cacheKey, ActivityRow::class.java, a)
            // TD-2 — zones are server-computed. buckets=0 skips the time
            // series the web streamgraph needs and the phone does not.
            zones = runCatching {
                withContext(Dispatchers.IO) { api.activityZones(source, sourceId, buckets = 0) }
            }.getOrNull()
            trails = ts.trails.sortedBy { it.name }
            error = null
            hrPoints = try {
                val start = Instant.parse(a.startAt)
                val end = start.plusSeconds(a.durationS.toLong())
                withContext(Dispatchers.IO) {
                    api.heartRateSeries(since = start.toString(), until = end.toString())
                }.points
            } catch (e: Exception) {
                Timber.w(e, "activity HR fetch failed"); emptyList()
            }
        } catch (e: Exception) {
            Timber.w(e, "activity load failed for %s/%s", source, sourceId)
            // With a cached copy on screen this is a stale-data caution, not
            // a replacement for the view.
            error = e.userMessage("Couldn't reach the backend.")
        } finally { loading = false }
    }

    suspend fun setTrail(trailId: Long?) {
        saving = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) {
                api.linkActivityTrail(source, sourceId, ActivityLinkTrailBody(trailId))
            }
            if (resp.isSuccessful) { showPicker = false; load() }
            else notice = "Couldn't change the trail link (HTTP ${resp.code()})."
        } catch (e: Exception) {
            Timber.w(e, "link failed")
            notice = e.userMessage("Couldn't change the trail link")
        } finally { saving = false }
    }

    LaunchedEffect(source, sourceId) { load() }

    ActivityDetailContent(
        activity = activity, trails = trails, hrPoints = hrPoints, zones = zones,
        loading = loading, error = error, notice = notice,
        zone = ZoneId.systemDefault(), savingType = savingType,
        onBack = onBack,
        onRetry = { scope.launch { load() } },
        onDismissNotice = { notice = null },
        onChangeType = {
            typeError = null
            showTypeEdit = true
            if (typeChoices.isEmpty()) scope.launch {
                try {
                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                    typeChoices = withContext(Dispatchers.IO) { api.activityTypeChoices() }
                } catch (e: Exception) {
                    typeError = e.userMessage("Could not load activity types")
                }
            }
        },
        onUndoType = { saveType(app.myvitals.sync.ActivityEditBody(resetType = true)) },
        onEdit = { showEdit = true },
        onPickTrail = { showPicker = true },
        map = { a, m -> ActivityMap(a, trails, m) },
        routeMissing = { a ->
            RouteMissingCard(a = a, neon = true, settings = settings,
                onRefreshed = { scope.launch { load() } })
        },
    )

    if (showPicker && activity != null) {
        val a = activity!!
        ModalBottomSheet(
            onDismissRequest = { if (!saving) showPicker = false },
            containerColor = NeonMV.Card,
        ) {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text("Link to trail", color = NeonMV.Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                val pickable = remember(trails) {
                    trails.filter { it.latitude != null && it.longitude != null }.sortedBy { it.name }
                }
                LazyColumn(
                    Modifier.fillMaxWidth().height(360.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    items(pickable, key = { it.id }) { t ->
                        val isCurrent = t.id == a.trailId
                        Card(
                            colors = CardDefaults.cardColors(
                                containerColor = if (isCurrent) NeonMV.Cyan.copy(alpha = 0.15f)
                                                 else NeonMV.BgElevated,
                            ),
                            modifier = Modifier.fillMaxWidth().clickable(enabled = !saving) {
                                scope.launch { setTrail(t.id) }
                            },
                        ) {
                            Row(Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically) {
                                Text(t.name, modifier = Modifier.weight(1f), color = NeonMV.Ink, fontSize = 14.sp)
                                val cs = listOfNotNull(t.city, t.state).joinToString(", ")
                                if (cs.isNotEmpty()) Text(cs, color = NeonMV.Muted, fontSize = 11.sp)
                            }
                        }
                    }
                }
                Row(Modifier.fillMaxWidth().padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (a.trailId != null) {
                        OutlinedButton(
                            onClick = { scope.launch { setTrail(null) } },
                            enabled = !saving, modifier = Modifier.weight(1f),
                        ) { Text("Clear link") }
                    }
                    TextButton(
                        onClick = { if (!saving) showPicker = false },
                        modifier = Modifier.weight(1f),
                    ) { Text("Cancel") }
                }
            }
        }
    }

    if (showTypeEdit && activity != null) {
        val current = activity!!.type
        var picked by remember(current) { mutableStateOf(current) }
        AlertDialog(
            onDismissRequest = { if (!savingType) showTypeEdit = false },
            title = { Text("What was this?") },
            text = {
                Column {
                    Text(
                        "Watches guess the activity type. Pick what it really was — " +
                            "stats, icons and training load follow, and a re-sync " +
                            "won't change it back.",
                        fontSize = 13.sp, color = NeonMV.Muted,
                    )
                    typeError?.let {
                        Spacer(Modifier.height(6.dp))
                        Text(it, color = NeonMV.Amber, fontSize = 12.sp)
                    }
                    Spacer(Modifier.height(8.dp))
                    if (typeChoices.isEmpty() && typeError == null) {
                        Text("Loading…", color = NeonMV.Muted, fontSize = 13.sp)
                    }
                    Column(Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState())) {
                        typeChoices.forEach { c ->
                            Row(
                                Modifier.fillMaxWidth().heightIn(min = 48.dp).selectable(
                                    selected = picked == c.type,
                                    role = androidx.compose.ui.semantics.Role.RadioButton,
                                    onClick = { picked = c.type },
                                ),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                RadioButton(selected = picked == c.type, onClick = null)
                                Spacer(Modifier.width(8.dp))
                                Text(c.label)
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(
                    enabled = !savingType && picked != current,
                    onClick = { saveType(app.myvitals.sync.ActivityEditBody(type = picked)) },
                ) { Text(if (savingType) "Saving…" else "Save") }
            },
            dismissButton = {
                TextButton(enabled = !savingType, onClick = { showTypeEdit = false }) { Text("Cancel") }
            },
        )
    }

    if (showEdit && activity != null) {
        val a = activity!!
        ActivityEditDialog(
            neon = true,
            initialName = a.name.orEmpty(),
            initialDurationMin = (a.durationS / 60).coerceAtLeast(1),
            initialStartAtIso = a.startAt,
            submitting = editing,
            onDismiss = { if (!editing) showEdit = false },
            onSubmit = { name, durationMin, startAtIso ->
                scope.launch {
                    editing = true
                    try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        val updated = withContext(Dispatchers.IO) {
                            api.editActivity(
                                source = a.source, sourceId = a.sourceId,
                                body = app.myvitals.sync.ActivityEditBody(
                                    name = name,
                                    durationMinutes = durationMin.toDouble(),
                                    startAt = startAtIso,
                                ),
                            )
                        }
                        activity = updated
                        app.myvitals.data.JsonCache.write(context, cacheKey, ActivityRow::class.java, updated)
                        showEdit = false
                        notice = null
                        load()
                    } catch (e: Exception) {
                        Timber.w(e, "editActivity failed")
                        // Inline, above the loaded activity — this used to set
                        // the load `error` and replace the whole view.
                        notice = "Edit failed: " + e.userMessage("could not save")
                        showEdit = false
                    } finally { editing = false }
                }
            },
        )
    }
}

private val HERO_TIME_FMT = DateTimeFormatter.ofPattern("EEE, MMM d · h:mm a")

/**
 * Stateless detail view. [map] draws the route into the hero box (a WebView
 * in the app, a placeholder in screenshot tests); [routeMissing] is the
 * Health Connect "fetch the route" card.
 */
@Composable
fun ActivityDetailContent(
    activity: ActivityRow?,
    trails: List<Trail>,
    hrPoints: List<TimePoint>,
    zones: ActivityZones?,
    loading: Boolean,
    error: String?,
    notice: String?,
    zone: ZoneId,
    savingType: Boolean,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onDismissNotice: () -> Unit,
    onChangeType: () -> Unit,
    onUndoType: () -> Unit,
    onEdit: () -> Unit,
    onPickTrail: () -> Unit,
    map: @Composable (ActivityRow, Modifier) -> Unit,
    routeMissing: @Composable (ActivityRow) -> Unit = {},
) {
    NeonScreen(
        title = "Activity",
        contentPadding = PaddingValues(0.dp),
        onBack = onBack,
        headerTrailing = if (activity == null) null else {
            {
                Row {
                    NeonIconButton(Icons.Outlined.Category, "Change activity type", onClick = onChangeType)
                    // Manual activities are user-authored; imported rows are
                    // read-only because their source is authoritative.
                    if (activity.source == "manual") {
                        NeonIconButton(Icons.Outlined.Edit, "Edit", onClick = onEdit)
                    }
                }
            }
        },
    ) {
        if (notice != null) {
            StaleBanner(title = notice, message = null, onRetry = null,
                modifier = Modifier.clickable(onClick = onDismissNotice))
        }
        if (activity == null) {
            when {
                loading -> Box(
                    Modifier.fillMaxWidth().height(300.dp).clip(RoundedCornerShape(24.dp))
                        .background(NeonMV.Card),
                    contentAlignment = Alignment.Center,
                ) { Text("Loading activity…", color = NeonMV.Muted, fontSize = 13.sp) }
                error != null -> StaleBanner("Couldn't load this activity", error, onRetry = onRetry)
                else -> Text("Not found", color = NeonMV.Muted, modifier = Modifier.padding(vertical = 16.dp))
            }
            return@NeonScreen
        }
        val a = activity
        if (error != null) {
            StaleBanner("Couldn't refresh — showing the saved copy", error, onRetry = onRetry)
        }

        val hasRoute = !a.polyline.isNullOrBlank() ||
            (a.trailId != null && trails.any { it.id == a.trailId && it.latitude != null })
        DetailHero(a, zone, hasRoute, map)

        a.recordedType?.let { rec ->
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 4.dp)) {
                Text("Recorded as ${prettyType(rec)}", color = NeonMV.Muted,
                    fontSize = 12.sp, modifier = Modifier.weight(1f))
                TextButton(enabled = !savingType, onClick = onUndoType) { Text("Undo", color = NeonMV.Cyan) }
            }
        }

        BigNumbers(a)
        QuietStats(a, zones)

        // SA-P3: deliberately NOT an `else` of the map — a trail link gives
        // the activity a PIN, not a track, and the fetch affordance must stay
        // reachable when only the pin is drawn.
        if (a.polyline.isNullOrBlank() && a.source == "healthconnect") {
            Box(Modifier.padding(bottom = 12.dp)) { routeMissing(a) }
        }
        if (hrPoints.isNotEmpty()) ActivityHrChart(hrPoints, zones, a.avgHr)
        zones?.takeIf { it.totalSeconds > 0 }?.let { HrZonesSummary(it) }
        TrailLinkRow(a, trails, onPickTrail)
        if (!a.notes.isNullOrBlank()) {
            Column(
                Modifier.fillMaxWidth().padding(bottom = 12.dp)
                    .clip(NeonCardShape).background(NeonMV.Card)
                    .border(1.dp, NeonMV.Line, NeonCardShape).padding(16.dp),
            ) {
                NeonEyebrow("Notes", Modifier.padding(top = 0.dp))
                Text(a.notes, color = NeonMV.Ink, fontSize = 14.sp)
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun DetailHero(
    a: ActivityRow,
    zone: ZoneId,
    hasRoute: Boolean,
    map: @Composable (ActivityRow, Modifier) -> Unit,
) {
    val tint = categoryForActivityType(a.type).color(true)
    val shape = RoundedCornerShape(24.dp)
    val whenStr = remember(a.startAt, zone) {
        runCatching { Instant.parse(a.startAt).atZone(zone).format(HERO_TIME_FMT) }.getOrDefault("")
    }
    val caption: @Composable BoxScope.() -> Unit = {
        Column(Modifier.align(Alignment.BottomStart).padding(16.dp)) {
            Text(prettyType(a.type).uppercase(), color = NeonMV.Cyan, fontFamily = NeonNumberFamily,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp)
            Text(
                a.name?.takeIf { it.isNotBlank() } ?: prettyType(a.type),
                color = NeonMV.Ink, fontSize = 24.sp, fontWeight = FontWeight.ExtraBold,
                maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 28.sp,
            )
            if (whenStr.isNotEmpty()) Text(whenStr, color = NeonMV.Ink.copy(alpha = 0.8f), fontSize = 13.sp)
        }
    }
    if (hasRoute) {
        Box(
            Modifier.fillMaxWidth().padding(bottom = 16.dp).height(300.dp)
                .clip(shape).border(1.dp, NeonMV.Cyan.copy(alpha = 0.22f), shape),
        ) {
            map(a, Modifier.fillMaxSize())
            // Bottom scrim so the caption reads over any tile colour.
            Box(
                Modifier.fillMaxWidth().height(140.dp).align(Alignment.BottomCenter)
                    .background(Brush.verticalGradient(listOf(Color.Transparent, NeonMV.Bg.copy(alpha = 0.92f)))),
            )
            caption()
        }
    } else {
        // No route: a category-tinted card in the same place, so the page
        // keeps its shape instead of opening on a stats grid.
        Box(
            Modifier.fillMaxWidth().padding(bottom = 16.dp).height(190.dp)
                .clip(shape)
                .background(Brush.linearGradient(listOf(tint.copy(alpha = 0.38f), NeonMV.CardHigh, NeonMV.Card)))
                .border(1.dp, tint.copy(alpha = 0.30f), shape),
        ) {
            Icon(iconForType(a.type), contentDescription = null, tint = tint.copy(alpha = 0.55f),
                modifier = Modifier.align(Alignment.TopEnd).padding(18.dp).size(56.dp))
            caption()
        }
    }
}

private data class Big(val label: String, val value: String, val unit: String?)

private fun isFootSport(type: String): Boolean {
    val t = type.lowercase()
    return t.contains("run") || t.contains("walk") || t.contains("hike")
}

/** m/s from the activity's own distance and time — a unit conversion of
 *  two server numbers, rendered through Units like every other pace. */
private fun speedMs(a: ActivityRow): Double? {
    val d = a.distanceM ?: return null
    if (d <= 0.0 || a.durationS <= 0) return null
    return d / a.durationS
}

private fun bigsFor(a: ActivityRow): List<Big> = buildList {
    a.distanceM?.takeIf { it > 0 }?.let {
        add(Big("Distance", "%.2f".format(Units.distance(it) ?: 0.0), Units.distanceUnit))
    }
    add(Big("Time", fmtDurationHm(a.durationS), null))
    val pace = if (isFootSport(a.type)) speedMs(a) else null
    if (pace != null) {
        val (v, u) = Units.fmtPace(pace).split(" ").let { it[0] to it.getOrNull(1) }
        add(Big("Pace", v, u))
    } else a.avgHr?.let { add(Big("Avg HR", "%.0f".format(it), "bpm")) }
    if (size < 3) a.kcal?.let { add(Big("Energy", "%.0f".format(it), "kcal")) }
}

@Composable
private fun BigNumbers(a: ActivityRow) {
    val bigs = bigsFor(a)
    Row(Modifier.fillMaxWidth().padding(bottom = 14.dp)) {
        bigs.take(3).forEach { b ->
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.Bottom) {
                    NeonNumber(b.value, size = 30)
                    if (b.unit != null) {
                        Spacer(Modifier.width(3.dp))
                        Text(b.unit, color = NeonMV.Muted, fontSize = 12.sp,
                            modifier = Modifier.padding(bottom = 5.dp))
                    }
                }
                Text(b.label.uppercase(), color = NeonMV.Muted, fontFamily = NeonNumberFamily,
                    fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
            }
        }
    }
}

@Composable
private fun QuietStats(a: ActivityRow, zones: ActivityZones?) {
    val bigLabels = bigsFor(a).take(3).map { it.label }.toSet()
    // Max HR is not a warning. Ink, or Amber when the session reached the
    // top zone by the server's boundaries — never the crisis colour.
    val topLo = zones?.zones?.lastOrNull()?.loBpm
    val items = buildList<Triple<String, String, Color>> {
        a.elevationGainM?.let { add(Triple("Climb", Units.fmtElevation(it), NeonMV.Ink)) }
        if ("Avg HR" !in bigLabels) a.avgHr?.let { add(Triple("Avg HR", "%.0f bpm".format(it), NeonMV.Ink)) }
        a.maxHr?.let {
            val hot = topLo != null && it >= topLo
            add(Triple("Max HR", "%.0f bpm".format(it), if (hot) NeonMV.Amber else NeonMV.Ink))
        }
        if ("Pace" !in bigLabels && !isFootSport(a.type)) {
            speedMs(a)?.let { ms ->
                val perHour = (Units.distance(ms * 3600.0) ?: 0.0)
                add(Triple("Speed", "%.1f %s/h".format(perHour, Units.distanceUnit), NeonMV.Ink))
            }
        }
        a.avgPowerW?.let { add(Triple("Power", "%.0f W".format(it), NeonMV.Ink)) }
        if ("Energy" !in bigLabels) a.kcal?.let { add(Triple("Energy", "%.0f kcal".format(it), NeonMV.Ink)) }
    }
    if (items.isEmpty()) return
    Column(
        Modifier.fillMaxWidth().padding(bottom = 14.dp)
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items.chunked(3).take(2).forEach { row ->
            Row(Modifier.fillMaxWidth()) {
                row.forEach { (l, v, c) -> QuietStat(l, v, Modifier.weight(1f), color = c) }
                repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun TrailLinkRow(a: ActivityRow, trails: List<Trail>, onPick: () -> Unit) {
    val linked = a.trailId?.let { id -> trails.firstOrNull { it.id == id } }
    Row(
        Modifier.fillMaxWidth().padding(bottom = 12.dp)
            .clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .clickable { onPick() }
            .heightIn(min = 56.dp)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.Link, contentDescription = null, tint = NeonMV.Cyan, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(if (linked != null) "LINKED TRAIL" else "NOT LINKED", color = NeonMV.Muted,
                fontFamily = NeonNumberFamily, fontSize = 10.sp, fontWeight = FontWeight.Bold,
                letterSpacing = 1.2.sp)
            Text(linked?.name ?: (a.trailName ?: "Tap to link a trail"), color = NeonMV.Ink,
                fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
            if (linked != null && linked.visitsTotal > 0) {
                Text("${linked.visitsTotal} all-time visit${if (linked.visitsTotal == 1) "" else "s"}",
                    color = NeonMV.Muted, fontSize = 12.sp)
            }
        }
    }
}

/** "1h 59m" past the hour, "47m" below it. */
internal fun fmtDurationHm(seconds: Int): String {
    if (seconds <= 0) return "—"
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}

@Composable
private fun ActivityEditDialog(
    neon: Boolean,
    initialName: String,
    initialDurationMin: Int,
    initialStartAtIso: String,
    submitting: Boolean,
    onDismiss: () -> Unit,
    onSubmit: (name: String, durationMin: Int, startAtIso: String) -> Unit,
) {
    // Derive initial ended-at + anchor date from the activity's real
    // start_at + duration. Editing a 3-day-old entry keeps it on that
    // day; only the picked HH:MM changes.
    val zone = remember { java.time.ZoneId.systemDefault() }
    val initialEndedLocal = remember(initialStartAtIso, initialDurationMin) {
        runCatching {
            val startInstant = java.time.Instant.parse(initialStartAtIso)
            val endInstant = startInstant.plusSeconds(initialDurationMin * 60L)
            endInstant.atZone(zone).toLocalDateTime()
        }.getOrNull() ?: java.time.LocalDateTime.now()
    }
    val anchorDate = remember(initialStartAtIso) {
        runCatching {
            java.time.Instant.parse(initialStartAtIso).atZone(zone).toLocalDate()
        }.getOrNull() ?: java.time.LocalDate.now()
    }
    var name by remember { mutableStateOf(initialName) }
    var durationStr by remember { mutableStateOf(initialDurationMin.toString()) }
    var endedHour by remember { mutableStateOf(initialEndedLocal.hour) }
    var endedMinute by remember { mutableStateOf(initialEndedLocal.minute) }
    var showTimePicker by remember { mutableStateOf(false) }
    val duration = durationStr.toIntOrNull()
    val canSubmit = name.isNotBlank() && duration != null && duration in 1..1440 && !submitting

    if (showTimePicker) {
        app.myvitals.ui.common.EndedTimePickerDialog(
            initialHour = endedHour,
            initialMinute = endedMinute,
            onConfirm = { h, m ->
                endedHour = h; endedMinute = m; showTimePicker = false
            },
            onDismiss = { showTimePicker = false },
        )
    }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit activity") },
        text = {
            Column {
                androidx.compose.material3.OutlinedTextField(
                    value = name,
                    onValueChange = { name = it.take(120) },
                    label = { Text("Name") },
                    singleLine = true,
                    enabled = !submitting,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                androidx.compose.material3.OutlinedTextField(
                    value = durationStr,
                    onValueChange = { durationStr = it.take(4).filter(Char::isDigit) },
                    label = { Text("Duration (minutes)") },
                    singleLine = true,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                    ),
                    enabled = !submitting,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Ended at",
                    color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant, fontSize = 12.sp,
                )
                Spacer(Modifier.height(2.dp))
                androidx.compose.material3.OutlinedButton(
                    onClick = { if (!submitting) showTimePicker = true },
                    enabled = !submitting,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        "%02d:%02d".format(endedHour, endedMinute) +
                        "  ·  " + anchorDate.toString(),
                        color = if (neon) NeonMV.Ink else MV.OnSurface, fontSize = 16.sp,
                    )
                }
                Text(
                    "Anchored to the activity's original date. " +
                    "HR is re-scanned for the new window.",
                    color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        },
        confirmButton = {
            androidx.compose.material3.TextButton(
                enabled = canSubmit,
                onClick = {
                    val dur = duration ?: initialDurationMin
                    val endAt = app.myvitals.ui.common.composeEndedInstant(
                        endedHour, endedMinute, anchorDate = anchorDate,
                    )
                    val startAt = endAt.minusSeconds(dur * 60L)
                    onSubmit(name.trim(), dur, startAt.toString())
                },
            ) { Text(if (submitting) "Saving…" else "Save",
                color = if (neon) NeonMV.Lime else MV.Green) }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(
                onClick = onDismiss, enabled = !submitting,
            ) { Text("Cancel") }
        },
    )
}

/**
 * SA-P3 — the Route card when there is no route to draw.
 *
 * Three states, and telling them apart is the whole point. Before this,
 * all three rendered as the card not being there:
 *
 *  - `route_state == "consent_required"` — Health Connect HAS a track for
 *    this session and is withholding it. Actionable, and the only one of
 *    the three that is. This is the state the SA-P2 probe found on the
 *    2026-09-19 walk from both writers.
 *  - `route_state == "none"` — Health Connect was asked and there is no
 *    track. An indoor dumbbell session, and nothing to fix.
 *  - `route_state == null` — nobody has asked. Every session ingested
 *    before this shipped. Not the same as "none", and rendering it as
 *    "no GPS" would be a claim about data that was never read.
 *
 * The button is deliberately here, on the activity, rather than only in
 * Settings: Google asks that routes be requested "upon deliberate user
 * interaction with your app, when the user is actively engaged with your
 * app's UI", and a tap on the specific walk you are looking at is exactly
 * that. It is also the only place the read can work at all — a route
 * written by another app is refused to a background worker whatever is
 * granted, so the 15-minute sync cannot be the answer.
 *
 * What the button launches is the per-session route request, NOT a
 * permission sheet. See [routeRequest] below: the all-routes permission is
 * unrequestable by design and API 35+ besides, so a permission button
 * would have done nothing on this device and would not have existed on an
 * older one.
 */
@Composable
private fun RouteMissingCard(
    a: ActivityRow,
    neon: Boolean,
    settings: SettingsRepository,
    onRefreshed: () -> Unit,
) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    // A route Health Connect would not release is a caution, not a crisis.
    val errColor = if (neon) NeonMV.Amber else MV.Red

    val gateway = remember { app.myvitals.health.HealthConnectGateway(ctx) }
    // True once the user has turned on all-routes access in Health Connect
    // settings. Not requestable from here — see below — but worth knowing,
    // because when it IS on a plain read works and no dialog is needed.
    var granted by remember { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(Unit) {
        granted = runCatching { gateway.hasRoutePermission() }.getOrDefault(false)
    }

    var busy by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var failed by remember { mutableStateOf(false) }
    // Resolved just before the per-session dialog is launched, and kept so
    // the result callback can build the sample from the same record.
    var pending by remember {
        mutableStateOf<androidx.health.connect.client.records.ExerciseSessionRecord?>(null)
    }

    /**
     * The per-session route request — `ACTION_REQUEST_EXERCISE_ROUTE`,
     * which `ExerciseRouteRequestContract` wraps.
     *
     * This, not a permission request, is the primary path, and that is not
     * a fallback choice. The platform javadoc for `READ_EXERCISE_ROUTES`
     * says plainly that "attempts to request the permission by
     * applications will be ignored" — it is grantable only from Health
     * Connect's own settings or from this very dialog — and it is API 35+
     * besides, where this app's minSdk is 28. A button wired to the
     * ordinary permission sheet would have opened a sheet that did
     * nothing and reported failure the user could not act on.
     *
     * The contract hands back the `ExerciseRoute` itself on approval, so
     * nothing has to be re-read afterwards.
     */
    val routeRequest = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.health.connect.client.contracts.ExerciseRouteRequestContract()
    ) { route ->
        val session = pending
        pending = null
        if (route == null || session == null) {
            busy = false
            failed = true
            note = "Health Connect did not release the route. You can also " +
                "turn on Health Connect \u2192 App permissions \u2192 myvitals " +
                "\u2192 Exercise routes to allow all of them at once."
            return@rememberLauncherForActivityResult
        }
        scope.launch {
            val result = app.myvitals.health.RouteBackfill.deliverOne(
                ctx, settings, session, route,
            )
            busy = false
            failed = result.error != null || result.tracks == 0
            note = when {
                result.error != null -> result.error
                result.tracks > 0 -> "Route saved \u2014 reloading\u2026"
                else -> "Health Connect released a route with too few points to draw."
            }
            if (result.tracks > 0) onRefreshed()
        }
    }

    fun fetch() {
        if (busy) return
        busy = true
        note = null
        failed = false
        scope.launch {
            val start = runCatching { java.time.Instant.parse(a.startAt) }.getOrNull()
            if (start == null) {
                busy = false
                failed = true
                note = "Could not read this activity\u2019s start time."
                return@launch
            }
            // With all-routes access already on, a plain foreground read
            // gets the track with no dialog at all. A narrow window around
            // this one session, not the whole 30 days: the user tapped one
            // activity, and reading a month of sessions to answer about one
            // of them is a binder round-trip each for nothing.
            if (granted == true) {
                val result = app.myvitals.health.RouteBackfill.run(
                    ctx, settings,
                    since = start.minusSeconds(3600),
                    until = start.plusSeconds(a.durationS.toLong() + 3600),
                )
                if (result.tracks > 0 || result.error != null || result.noData > 0) {
                    busy = false
                    failed = result.error != null || result.tracks == 0
                    note = when {
                        result.error != null -> result.error
                        result.tracks > 0 -> "Route found \u2014 reloading\u2026"
                        else -> "Health Connect has no GPS track for this session."
                    }
                    if (result.tracks > 0) onRefreshed()
                    return@launch
                }
                // Fell through on CONSENT_REQUIRED even with the grant
                // held. Ask for this one session explicitly rather than
                // telling the user something they cannot act on.
            }
            val session = runCatching { gateway.sessionStartingAt(start) }.getOrNull()
            if (session == null) {
                busy = false
                failed = true
                note = "Health Connect no longer has an exercise session at this time."
                return@launch
            }
            pending = session
            runCatching { routeRequest.launch(session.metadata.id) }.onFailure {
                busy = false
                pending = null
                failed = true
                note = "This device has no Health Connect route request screen."
            }
        }
    }

    val body: String = when {
        a.routeState == "consent_required" ->
            "Health Connect has a GPS track for this session and is holding it " +
                "back until you allow route access."
        a.routeState == "none" ->
            "Health Connect was asked and has no GPS track for this session."
        else ->
            "No route has been requested for this session yet. It was recorded " +
                "before this app read exercise routes."
    }
    // "none" is settled: the provider answered, and there is nothing to
    // go and get. Offering a button there would invite a tap that can
    // only ever fail.
    val actionable = a.routeState != "none"

    Column(
        Modifier.fillMaxWidth()
            .clip(if (neon) NeonCardShape else RoundedCornerShape(12.dp))
            .background(card)
            .padding(16.dp),
    ) {
        Text(
            "ROUTE", color = muted,
            fontFamily = if (neon) NeonNumberFamily else null,
            fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp,
        )
        Spacer(Modifier.height(8.dp))
        Text(body, color = ink, fontSize = 14.sp)
        if (actionable) {
            Spacer(Modifier.height(12.dp))
            if (granted == false) {
                Text(
                    "Health Connect will ask about this one session. To stop " +
                        "being asked per walk, turn on Exercise routes for " +
                        "myvitals in Health Connect \u2192 App permissions. " +
                        "Routes are separate from the rest of your health data, " +
                        "and leaving them off never affects syncing.",
                    color = muted, fontSize = 12.sp,
                )
                Spacer(Modifier.height(8.dp))
            }
            OutlinedButton(onClick = { fetch() }, enabled = !busy) {
                Text(if (busy) "Reading\u2026" else "Fetch route from Health Connect")
            }
        }
        note?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = if (failed) errColor else muted, fontSize = 12.sp)
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun ActivityMap(a: ActivityRow, trails: List<Trail>, modifier: Modifier = Modifier) {
    val neon = true
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val leafletCss = remember { app.myvitals.ui.common.LeafletAssets.css(ctx) }
    val leafletJs = remember { app.myvitals.ui.common.LeafletAssets.js(ctx) }
    // Map chrome colors: neon route = Cyan, open-trail marker = Lime, page
    // bg = obsidian. Classic keeps the original brand-red / green / #0F1620.
    val pageBgHex = if (neon) "#0F1118" else "#0F1620"
    val routeHex = if (neon) "#28E6FF" else "#ef4444"
    val markerHex = if (neon) "#5DFF3B" else "#22C55E"
    // Escape order matters: backslash FIRST, then quotes / control chars.
    // Google's polyline encoding uses backslash heavily, and a raw '\u'
    // in a JS string literal triggers a SyntaxError that aborts the page.
    fun jsEsc(s: String?): String = s
        ?.replace("\\", "\\\\")
        ?.replace("'", "\\'")
        ?.replace("\n", " ")
        ?.replace("\r", "") ?: ""
    val polylineEsc = jsEsc(a.polyline)
    val trail = a.trailId?.let { id -> trails.firstOrNull { it.id == id } }
    val trailLat = trail?.latitude
    val trailLon = trail?.longitude
    val nameEsc = jsEsc(trail?.name)
    val html = """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="initial-scale=1.0,width=device-width"/>
<style>$leafletCss
html,body{margin:0;padding:0;background:$pageBgHex;overflow:hidden;}
#m{display:block;}</style>
</head><body>
<div id="m"></div>
<script>$leafletJs</script>
<script>
function applySize() {
  const w = window.innerWidth || document.documentElement.clientWidth || 360;
  const h = window.innerHeight || document.documentElement.clientHeight || 200;
  const m = document.getElementById('m');
  m.style.width = w + 'px';
  m.style.height = h + 'px';
  document.body.style.width = w + 'px';
  document.body.style.height = h + 'px';
  document.documentElement.style.width = w + 'px';
  document.documentElement.style.height = h + 'px';
}
applySize();
window.addEventListener('error', e => console.error('JS error:', e.message));
function decodePolyline(str) {
  let idx = 0, lat = 0, lon = 0, points = [];
  while (idx < str.length) {
    let b, sh = 0, r = 0;
    do { b = str.charCodeAt(idx++) - 63; r |= (b & 0x1f) << sh; sh += 5; } while (b >= 0x20);
    lat += ((r & 1) ? ~(r >> 1) : (r >> 1));
    sh = 0; r = 0;
    do { b = str.charCodeAt(idx++) - 63; r |= (b & 0x1f) << sh; sh += 5; } while (b >= 0x20);
    lon += ((r & 1) ? ~(r >> 1) : (r >> 1));
    points.push([lat * 1e-5, lon * 1e-5]);
  }
  return points;
}
try {
  window.map = L.map('m', {zoomControl:true,scrollWheelZoom:false}).setView([39, -94], 13);
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19,maxNativeZoom:16,attribution:'© OSM, Tiles © Esri'}).addTo(window.map);
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19,maxNativeZoom:16,pane:'shadowPane'}).addTo(window.map);
  const enc = '$polylineEsc';
  let bounds = null;
  if (enc.length > 0) {
    const pts = decodePolyline(enc);
    if (pts.length > 1) {
      const line = L.polyline(pts, {color:'$routeHex', weight:3, opacity:0.9}).addTo(window.map);
      bounds = line.getBounds();
    }
  }
  ${if (trailLat != null && trailLon != null) """
  const pinIcon = L.divIcon({
    html: '<div style="width:16px;height:16px;border-radius:50%;'
        + 'background:$markerHex;border:2px solid #FFFFFF;'
        + 'box-shadow:0 2px 6px rgba(0,0,0,0.6);"></div>',
    className: 'mvpin', iconSize: [16,16], iconAnchor: [8,8],
  });
  L.marker([$trailLat,$trailLon], {icon: pinIcon}).addTo(window.map)
    .bindPopup('$nameEsc');
  if (bounds) bounds.extend([$trailLat,$trailLon]);
  else bounds = L.latLngBounds([$trailLat,$trailLon], [$trailLat,$trailLon]);
  """ else ""}
  function fix() {
    try {
      applySize();
      window.map.invalidateSize();
      if (bounds && window.innerHeight > 0) {
        try { window.map.fitBounds(bounds.pad(0.1)); } catch (e) {}
      }
    } catch (e) {}
  }
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(fix).observe(document.documentElement);
  }
  window.addEventListener('resize', fix);
  setTimeout(fix, 50); setTimeout(fix, 250); setTimeout(fix, 800);
  setTimeout(() => console.log(
    'map size:', window.map.getSize().x, 'x', window.map.getSize().y,
    'innerH:', window.innerHeight, 'bodyH:', document.body.clientHeight,
  ), 900);
} catch (e) { console.error('map init failed:', e.toString()); }
</script></body></html>"""
    AndroidView(
        factory = { ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.loadsImagesAutomatically = true
                settings.mixedContentMode =
                    android.webkit.WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                settings.allowFileAccess = true
                webViewClient = WebViewClient()
                webChromeClient = object : android.webkit.WebChromeClient() {
                    override fun onConsoleMessage(
                        m: android.webkit.ConsoleMessage,
                    ): Boolean {
                        Timber.tag("ActivityMap").i(
                            "[${m.messageLevel()}] ${m.message()}",
                        )
                        return true
                    }
                }
                setBackgroundColor(android.graphics.Color.parseColor(pageBgHex))
                loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
                tag = html
            }
        },
        update = { webview ->
            if (webview.tag != html) {
                webview.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
                webview.tag = html
            }
        },
        modifier = modifier,
    )
}
