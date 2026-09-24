package app.myvitals.ui.trails

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowRight
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Navigation
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material.icons.outlined.UnfoldLess
import androidx.compose.material.icons.outlined.UnfoldMore
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.data.Units
import app.myvitals.sync.ActivityLinkTrailBody
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.sync.Trail
import app.myvitals.sync.TrailLocationBody
import app.myvitals.sync.TrailStatusCounts
import app.myvitals.sync.TrailSubscribeBody
import app.myvitals.sync.TrailsResponse
import app.myvitals.ui.MV
import app.myvitals.ui.activities.NeonIconButton
import app.myvitals.ui.activities.NeonPill
import app.myvitals.ui.activities.StaleBanner
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonNumberFamily
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

/*
 * Trails (UI-5).
 *
 *  - One long list with open/closed only as 12sp grey text in the header.
 *    It leads with a status hero now: "11 of 14 open" (the open count big,
 *    in Lime), a segmented bar (open Lime / delayed Amber / closed Bad —
 *    Bad here is literally the trail's status, "closed", not an alarm), a
 *    "synced 4m" pill, and a mini map of status-coloured pins that opens
 *    the full map. The counts come from the server (`status_counts`).
 *  - Starred trails — the ones you ride — sit in a carousel at the top
 *    with how long since you rode each.
 *  - A failed refresh replaced the whole list, cached trails and all. It
 *    is an amber banner ABOVE the cached trails now.
 *  - The visit link was a 12dp icon and 11sp text; it is a ≥32dp chip.
 *    The map arrow was a 12dp icon; it is a 48dp button.
 */

/** Everything the Trails page renders, for the fetching wrapper and tests. */
data class TrailsUi(
    val trails: List<Trail> = emptyList(),
    val counts: TrailStatusCounts? = null,
    val syncedAt: String? = null,
    val dnisUrl: String? = null,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TrailsScreen(
    settings: SettingsRepository,
    onOpenTrailVisits: (trailId: Long) -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    // Density is a per-user preference, persisted so it survives a relaunch.
    var dense by remember { mutableStateOf(settings.trailsDense) }
    var ui by remember { mutableStateOf(TrailsUi()) }
    var showOverviewMap by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val expandedTrail = remember { mutableStateOf<Long?>(null) }

    var linking by remember { mutableStateOf(false) }
    var fetchingOsm by remember { mutableStateOf(false) }
    var actionResult by remember { mutableStateOf<String?>(null) }
    // Bumped after a fetch-all-osm-paths run so expanded rows refetch.
    var osmCacheEpoch by remember { mutableStateOf(0) }

    var recentRides by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var linkTarget by remember { mutableStateOf<ActivityRow?>(null) }
    var linkSaving by remember { mutableStateOf(false) }

    var editTrail by remember { mutableStateOf<Trail?>(null) }
    var editLat by remember { mutableStateOf("") }
    var editLon by remember { mutableStateOf("") }
    var editCity by remember { mutableStateOf("") }
    var editState by remember { mutableStateOf("") }
    var editSaving by remember { mutableStateOf(false) }
    var editError by remember { mutableStateOf<String?>(null) }

    fun openEdit(t: Trail) {
        editTrail = t
        editLat = t.latitude?.toString() ?: ""
        editLon = t.longitude?.toString() ?: ""
        editCity = t.city ?: ""
        editState = t.state ?: ""
        editError = null
    }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."
            loading = false
            return
        }
        // SWR: the whole last response, so the hero's server counts render
        // from cache too rather than being recounted here.
        if (ui.trails.isEmpty()) {
            app.myvitals.data.JsonCache.read<TrailsResponse>(
                context, "trails_response", TrailsResponse::class.java,
            )?.let { c ->
                ui = TrailsUi(c.value.trails.sortedBy { it.name }, c.value.statusCounts,
                    c.value.syncedAt, c.value.dnisUrl)
                loading = false
            }
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.trails() }
            ui = TrailsUi(r.trails.sortedBy { it.name }, r.statusCounts, r.syncedAt, r.dnisUrl)
            app.myvitals.data.JsonCache.write(context, "trails_response", TrailsResponse::class.java, r)
            error = null
            Timber.i("trails loaded: %d total, counts=%s", r.trails.size, r.statusCounts)
        } catch (e: Exception) {
            Timber.w(e, "trails load failed")
            error = e.message?.take(160) ?: "Couldn't reach the backend."
        } finally {
            loading = false
        }
    }

    suspend fun refreshNow() {
        if (!settings.isConfigured()) return
        refreshing = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.refreshTrails() }
            Timber.i("trails refresh: fetched=%d snapshots=%d alerts=%d", r.fetched, r.snapshots, r.alerts)
            load()
        } catch (e: Exception) {
            Timber.w(e, "trails refresh failed")
            error = e.message?.take(160)
        } finally {
            refreshing = false
        }
    }

    suspend fun loadRecentRides() {
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val rows = withContext(Dispatchers.IO) { api.activitiesNoRoute(limit = 30) }
            // Unlinked rides only — this section is for manually linking the
            // ones the auto-linker could not match.
            recentRides = rows.filter { r ->
                if (r.trailId != null) return@filter false
                val t = r.type
                t.contains("Ride", ignoreCase = true) || t.contains("Run", ignoreCase = true) ||
                    t.contains("Hike", ignoreCase = true) || t.contains("Walk", ignoreCase = true)
            }
        } catch (e: Exception) {
            Timber.w(e, "loadRecentRides failed")
        }
    }

    suspend fun setRideTrail(ride: ActivityRow, trailId: Long?) {
        if (!settings.isConfigured()) return
        linkSaving = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) {
                api.linkActivityTrail(ride.source, ride.sourceId, ActivityLinkTrailBody(trailId))
            }
            if (resp.isSuccessful) {
                linkTarget = null
                loadRecentRides()
                load()
            } else {
                actionResult = "link failed: HTTP ${resp.code()}"
            }
        } catch (e: Exception) {
            Timber.w(e, "setRideTrail failed")
            actionResult = e.message?.take(160)
        } finally { linkSaving = false }
    }

    suspend fun linkActivities() {
        if (!settings.isConfigured()) return
        linking = true; actionResult = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.linkAllActivitiesToTrails() }
            actionResult = "Linked ${r.linked} new · ${r.alreadyLinkedSkipped} already · ${r.noMatchWithinKm} no match"
            load()
        } catch (e: Exception) {
            Timber.w(e, "linkActivities failed")
            actionResult = e.message?.take(160)
        } finally { linking = false }
    }

    suspend fun fetchOsmRoutes() {
        if (!settings.isConfigured()) return
        fetchingOsm = true; actionResult = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.fetchAllTrailOsmPaths() }
            actionResult = if (r.fetched == 0 && r.skipped > 0)
                "All ${r.skipped} routes already cached. Tap a trail to view."
                else "OSM: ${r.fetched} fetched · ${r.skipped} cached · ${r.failed} failed"
            osmCacheEpoch++
        } catch (e: Exception) {
            Timber.w(e, "fetchOsmRoutes failed")
            actionResult = e.message?.take(160)
        } finally { fetchingOsm = false }
    }

    suspend fun toggleSubscribe(t: Trail) {
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                if (t.subscribed) api.unsubscribeTrail(t.id)
                else api.subscribeTrail(t.id, TrailSubscribeBody("any"))
            }
            load()
        } catch (e: Exception) {
            Timber.w(e, "subscribe toggle failed")
            // An action failure is a message, not a reason to drop the list.
            actionResult = "Couldn't change the subscription: ${e.message?.take(100)}"
        }
    }

    LaunchedEffect(Unit) { load() }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }
    LaunchedEffect(Unit) { loadRecentRides() }
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    TrailsContent(
        ui = ui, loading = loading, refreshing = refreshing, error = error, nowMs = nowMs,
        dense = dense, expandedId = expandedTrail.value,
        actionResult = actionResult, recentRides = recentRides,
        linking = linking, fetchingOsm = fetchingOsm,
        contentPadding = PaddingValues(0.dp),
        onRefresh = { scope.launch { refreshNow(); loadRecentRides() } },
        onToggleDense = { dense = !dense; settings.trailsDense = dense },
        onOpenMap = { showOverviewMap = true },
        onOpenBoard = ui.dnisUrl?.let { url ->
            { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
        },
        onLinkActivities = { scope.launch { linkActivities() } },
        onFetchOsm = { scope.launch { fetchOsmRoutes() } },
        onDismissAction = { actionResult = null },
        onTapTrail = { t -> expandedTrail.value = if (expandedTrail.value == t.id) null else t.id },
        onSubscribeToggle = { t -> scope.launch { toggleSubscribe(t) } },
        onEditPin = { t -> openEdit(t) },
        onOpenTrailVisits = onOpenTrailVisits,
        onLinkRide = { linkTarget = it },
        miniMap = { m -> TrailsOverviewMap(ui.trails, nowMs, modifier = m, interactive = false) },
        expandedMap = { t -> ExpandedTrailMap(t, osmCacheEpoch, onEditPin = { openEdit(t) }) },
    )

    // Link-trail bottom sheet
    if (linkTarget != null) {
        val ride = linkTarget!!
        ModalBottomSheet(onDismissRequest = { if (!linkSaving) linkTarget = null }, containerColor = NeonMV.Card) {
            Column(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text("Link to trail", color = NeonMV.Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Text(rideSubtitle(ride), color = NeonMV.Muted, fontSize = 12.sp)
                if (ride.trailName != null) {
                    Text("Currently linked: ${ride.trailName}", color = NeonMV.Muted, fontSize = 12.sp)
                }
                Spacer(Modifier.height(6.dp))
                val pickable = remember(ui.trails) {
                    ui.trails.filter { it.latitude != null && it.longitude != null }.sortedBy { it.name }
                }
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().height(360.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    items(pickable, key = { it.id }) { t ->
                        val isCurrent = t.id == ride.trailId
                        Card(
                            colors = CardDefaults.cardColors(
                                containerColor = if (isCurrent) NeonMV.Cyan.copy(alpha = 0.15f) else NeonMV.Bg,
                            ),
                            modifier = Modifier.fillMaxWidth().clickable(enabled = !linkSaving) {
                                scope.launch { setRideTrail(ride, t.id) }
                            },
                        ) {
                            Row(
                                Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(t.name, modifier = Modifier.weight(1f), color = NeonMV.Ink, fontSize = 14.sp)
                                val cityStr = listOfNotNull(t.city, t.state).joinToString(", ")
                                if (cityStr.isNotEmpty()) Text(cityStr, color = NeonMV.Muted, fontSize = 11.sp)
                            }
                        }
                    }
                }
                Row(
                    Modifier.fillMaxWidth().padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (ride.trailId != null) {
                        OutlinedButton(
                            onClick = { scope.launch { setRideTrail(ride, null) } },
                            enabled = !linkSaving, modifier = Modifier.weight(1f),
                        ) { Text("Clear link") }
                    }
                    TextButton(
                        onClick = { if (!linkSaving) linkTarget = null },
                        modifier = Modifier.weight(1f),
                    ) { Text("Cancel") }
                }
            }
        }
    }

    // Edit-pin bottom sheet
    if (editTrail != null) {
        val t = editTrail!!
        ModalBottomSheet(onDismissRequest = { editTrail = null }, containerColor = NeonMV.Card) {
            Column(
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("Edit pin · ${t.name}", color = NeonMV.Ink, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Text("Decimal degrees. Tip: tap & hold a spot in Google Maps and the lat/lon pair appears at the top.",
                    color = NeonMV.Muted, fontSize = 11.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = editLat, onValueChange = { editLat = it },
                        label = { Text("Latitude") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true, modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = editLon, onValueChange = { editLon = it },
                        label = { Text("Longitude") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true, modifier = Modifier.weight(1f),
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = editCity, onValueChange = { editCity = it },
                        label = { Text("City (optional)") }, singleLine = true,
                        modifier = Modifier.weight(2f),
                    )
                    OutlinedTextField(
                        value = editState, onValueChange = { editState = it },
                        label = { Text("State") }, singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                OutlinedButton(
                    onClick = {
                        val uri = if (t.latitude != null && t.longitude != null) {
                            Uri.parse("geo:${t.latitude},${t.longitude}?q=${t.latitude},${t.longitude}(${Uri.encode(t.name)})")
                        } else {
                            Uri.parse("geo:0,0?q=${Uri.encode(t.name)}")
                        }
                        try {
                            context.startActivity(Intent(Intent.ACTION_VIEW, uri).apply {
                                flags = Intent.FLAG_ACTIVITY_NEW_TASK
                            })
                        } catch (_: Exception) { /* no map app */ }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Open in Maps to find coords") }
                if (editError != null) Text(editError!!, color = NeonMV.Amber, fontSize = 12.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = {
                            val lat = editLat.toDoubleOrNull()
                            val lon = editLon.toDoubleOrNull()
                            if (editLat.isNotBlank() && (lat == null || lat < -90 || lat > 90)) {
                                editError = "Latitude out of range"; return@Button
                            }
                            if (editLon.isNotBlank() && (lon == null || lon < -180 || lon > 180)) {
                                editError = "Longitude out of range"; return@Button
                            }
                            scope.launch {
                                editSaving = true; editError = null
                                try {
                                    val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                                    withContext(Dispatchers.IO) {
                                        api.editTrailLocation(t.id, TrailLocationBody(
                                            latitude = if (editLat.isBlank()) null else lat,
                                            longitude = if (editLon.isBlank()) null else lon,
                                            city = editCity.ifBlank { null },
                                            state = editState.ifBlank { null },
                                        ))
                                    }
                                    load()
                                    editTrail = null
                                } catch (e: Exception) {
                                    editError = e.message?.take(160)
                                } finally { editSaving = false }
                            }
                        },
                        enabled = !editSaving,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = NeonMV.Cyan, contentColor = NeonMV.OnAccent,
                        ),
                        modifier = Modifier.weight(1f),
                    ) { Text(if (editSaving) "Saving…" else "Save") }
                    OutlinedButton(onClick = { editTrail = null }, modifier = Modifier.weight(1f)) { Text("Cancel") }
                }
                Spacer(Modifier.height(16.dp))
            }
        }
    }

    // Fullscreen status map — same UX as web /trails/map.
    if (showOverviewMap) {
        androidx.compose.ui.window.Dialog(
            onDismissRequest = { showOverviewMap = false },
            properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false),
        ) {
            Box(modifier = Modifier.fillMaxSize().background(NeonMV.Bg)) {
                TrailsOverviewMap(ui.trails, nowMs)
                IconButton(
                    onClick = { showOverviewMap = false },
                    modifier = Modifier.align(Alignment.TopEnd).padding(8.dp)
                        .background(Color(0xCC181B27), CircleShape),
                ) {
                    Icon(Icons.Outlined.Close, contentDescription = "Close map", tint = NeonMV.Ink)
                }
            }
        }
    }
}

/**
 * Stateless Trails page. [miniMap] draws the status-pin map in the hero
 * (a WebView in the app, a placeholder in screenshot tests); [expandedMap]
 * is a tapped trail's inline preview.
 */
@Composable
fun TrailsContent(
    ui: TrailsUi,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    nowMs: Long,
    dense: Boolean,
    expandedId: Long?,
    actionResult: String?,
    recentRides: List<ActivityRow>,
    linking: Boolean,
    fetchingOsm: Boolean,
    contentPadding: PaddingValues,
    onRefresh: () -> Unit,
    onToggleDense: () -> Unit,
    onOpenMap: () -> Unit,
    onOpenBoard: (() -> Unit)?,
    onLinkActivities: () -> Unit,
    onFetchOsm: () -> Unit,
    onDismissAction: () -> Unit,
    onTapTrail: (Trail) -> Unit,
    onSubscribeToggle: (Trail) -> Unit,
    onEditPin: (Trail) -> Unit,
    onOpenTrailVisits: (Long) -> Unit,
    onLinkRide: (ActivityRow) -> Unit,
    miniMap: @Composable (Modifier) -> Unit,
    expandedMap: @Composable (Trail) -> Unit,
) {
    val trails = ui.trails
    val grouped = remember(trails) { groupTrails(trails) }
    var menuOpen by remember { mutableStateOf(false) }

    NeonScreen(
        title = "Trails",
        contentPadding = contentPadding,
        refreshing = refreshing,
        onRefresh = onRefresh,
        headerTrailing = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                NeonIconButton(
                    if (dense) Icons.Outlined.UnfoldMore else Icons.Outlined.UnfoldLess,
                    if (dense) "Switch to expanded rows" else "Switch to condensed rows",
                    onClick = onToggleDense,
                )
                NeonIconButton(Icons.Outlined.Refresh, "Refresh trail status",
                    spinning = refreshing, enabled = !refreshing, onClick = onRefresh)
                Box {
                    NeonIconButton(Icons.Outlined.MoreVert, "More") { menuOpen = true }
                    DropdownMenu(
                        expanded = menuOpen, onDismissRequest = { menuOpen = false },
                        modifier = Modifier.background(NeonMV.Card),
                    ) {
                        DropdownMenuItem(
                            text = { Text("Trail status map", color = NeonMV.Ink) },
                            onClick = { menuOpen = false; onOpenMap() },
                        )
                        if (onOpenBoard != null) {
                            DropdownMenuItem(
                                text = { Text("Open RainoutLine board", color = NeonMV.Ink) },
                                onClick = { menuOpen = false; onOpenBoard() },
                            )
                        }
                        DropdownMenuItem(
                            text = { Text(if (linking) "Linking rides…" else "Link rides to trails", color = NeonMV.Ink) },
                            enabled = !linking,
                            onClick = { menuOpen = false; onLinkActivities() },
                        )
                        DropdownMenuItem(
                            text = { Text(if (fetchingOsm) "Fetching OSM…" else "Fetch OSM routes", color = NeonMV.Ink) },
                            enabled = !fetchingOsm,
                            onClick = { menuOpen = false; onFetchOsm() },
                        )
                    }
                }
            }
        },
    ) {
        if (error != null) {
            StaleBanner(
                title = if (trails.isNotEmpty()) "Couldn't refresh — showing saved trail status"
                        else "Couldn't load trails",
                message = error, onRetry = onRefresh,
            )
        }
        if (actionResult != null) {
            Row(
                Modifier.fillMaxWidth().padding(bottom = 12.dp)
                    .clip(NeonCardShape).background(NeonMV.Card)
                    .border(1.dp, NeonMV.Cyan.copy(alpha = 0.30f), NeonCardShape)
                    .padding(start = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(actionResult, modifier = Modifier.weight(1f), color = NeonMV.Ink, fontSize = 12.sp)
                TextButton(onClick = onDismissAction) { Text("OK", color = NeonMV.Muted) }
            }
        }

        when {
            trails.isEmpty() && loading -> NeonHeroCard(accent = NeonMV.Lime) {
                NeonEyebrow("Trail status", Modifier.padding(top = 0.dp))
                Text("Loading trail status…", color = NeonMV.Muted, fontSize = 13.sp)
            }
            // A failed first load is not "no trails seeded": the banner says why.
            trails.isEmpty() && error != null -> Unit
            trails.isEmpty() -> Text(
                "No trails seeded yet. The backend poller runs every 15 minutes; tap Refresh to trigger an immediate poll.",
                color = NeonMV.Muted, fontSize = 14.sp,
                modifier = Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card).padding(16.dp),
            )
            else -> {
                StatusHero(ui, nowMs, onOpenMap, miniMap)
                val starred = remember(trails) { trails.filter { it.subscribed } }
                if (starred.isNotEmpty()) {
                    NeonEyebrow("Your trails")
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(bottom = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        starred.forEach { t -> StarredTile(t, nowMs) { onOpenTrailVisits(t.id) } }
                    }
                }
                for ((label, list) in listOf(
                    "Open" to grouped.open, "Delayed" to grouped.delayed,
                    "Closed" to grouped.closed, "Other" to grouped.other,
                )) {
                    if (list.isEmpty()) continue
                    NeonEyebrow("$label · ${list.size}")
                    list.forEach { t ->
                        TrailRow(
                            t, nowMs, dense = dense, expanded = expandedId == t.id,
                            onTap = { onTapTrail(t) },
                            onSubscribeToggle = { onSubscribeToggle(t) },
                            onLongPress = { onEditPin(t) },
                            onOpenTrailVisits = onOpenTrailVisits,
                            expandedMap = expandedMap,
                        )
                        Spacer(Modifier.height(8.dp))
                    }
                }
                if (recentRides.isNotEmpty()) {
                    NeonEyebrow("Recent rides · tap to link a trail")
                    recentRides.forEach { ride ->
                        RideLinkRow(ride, nowMs) { onLinkRide(ride) }
                        Spacer(Modifier.height(8.dp))
                    }
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

private data class TrailGroups(
    val open: List<Trail>,
    val closed: List<Trail>,
    val delayed: List<Trail>,
    val other: List<Trail>,
)

/** Each status bucket newest-first by when the source flipped. */
private fun groupTrails(trails: List<Trail>): TrailGroups {
    fun keyOf(t: Trail): Long {
        val v = t.sourceTs ?: t.fetchedAt ?: t.lastSeenAt
        return runCatching { java.time.OffsetDateTime.parse(v).toInstant().toEpochMilli() }.getOrDefault(0L)
    }
    val cmp = compareByDescending<Trail> { keyOf(it) }
    return TrailGroups(
        open = trails.filter { it.status == "open" }.sortedWith(cmp),
        closed = trails.filter { it.status == "closed" }.sortedWith(cmp),
        delayed = trails.filter { it.status == "delayed" }.sortedWith(cmp),
        other = trails.filter { it.status != "open" && it.status != "closed" && it.status != "delayed" }
            .sortedWith(cmp),
    )
}

/** Open Lime, delayed Amber, closed Bad — here Bad is the literal status. */
private fun statusColor(status: String?): Color = when (status) {
    "open" -> NeonMV.Lime
    "delayed" -> NeonMV.Amber
    "closed" -> NeonMV.Bad
    else -> NeonMV.Muted
}

@Composable
private fun StatusHero(
    ui: TrailsUi,
    nowMs: Long,
    onOpenMap: () -> Unit,
    miniMap: @Composable (Modifier) -> Unit,
) {
    val c = ui.counts
    val total = c?.let { it.open + it.delayed + it.closed + it.other } ?: 0
    NeonHeroCard(accent = NeonMV.Lime) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            NeonEyebrow("Trail status", Modifier.padding(top = 0.dp).weight(1f))
            val synced = fmtAge(ui.syncedAt, nowMs)
            if (synced.isNotEmpty()) {
                NeonPill("synced ${synced.removeSuffix(" ago")}", color = NeonMV.Periwinkle,
                    modifier = Modifier.padding(bottom = 8.dp))
            }
        }
        if (c == null) {
            // An older backend without server counts: say nothing rather than
            // count on the phone.
            Text("Status counts unavailable", color = NeonMV.Muted, fontSize = 13.sp)
        } else {
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber("${c.open}", color = NeonMV.Lime, size = 56)
                Spacer(Modifier.width(10.dp))
                Text("of $total open", color = NeonMV.Ink, fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(bottom = 12.dp))
            }
            if (total > 0) {
                Row(Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(5.dp))) {
                    for ((n, col) in listOf(c.open to NeonMV.Lime, c.delayed to NeonMV.Amber,
                        c.closed to NeonMV.Bad, c.other to NeonMV.Track)) {
                        if (n > 0) Box(Modifier.weight(n.toFloat()).fillMaxHeight().background(col))
                    }
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                    LegendCount(c.open, "open", NeonMV.Lime)
                    if (c.delayed > 0) LegendCount(c.delayed, "delayed", NeonMV.Amber)
                    LegendCount(c.closed, "closed", NeonMV.Bad)
                    if (c.other > 0) LegendCount(c.other, "unknown", NeonMV.Muted)
                }
            }
        }
        if (ui.trails.any { it.latitude != null && it.longitude != null }) {
            Spacer(Modifier.height(12.dp))
            // Non-interactive preview; the whole box is the button.
            Box(
                Modifier.fillMaxWidth().height(150.dp).clip(RoundedCornerShape(16.dp))
                    .border(1.dp, NeonMV.Line, RoundedCornerShape(16.dp)),
            ) {
                miniMap(Modifier.fillMaxSize())
                Box(
                    Modifier.fillMaxSize().clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null, onClickLabel = "Open trail status map",
                        onClick = onOpenMap,
                    ),
                )
                NeonPill("Open map", color = NeonMV.Cyan,
                    modifier = Modifier.align(Alignment.BottomEnd).padding(8.dp), onClick = onOpenMap)
            }
        }
    }
}

@Composable
private fun LegendCount(n: Int, label: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(5.dp))
        Text("$n $label", color = NeonMV.Muted, fontSize = 12.sp, fontFamily = NeonNumberFamily)
    }
}

@Composable
private fun StatusDot(color: Color, size: Int = 14) {
    Box(Modifier.size(size.dp), contentAlignment = Alignment.Center) {
        Box(Modifier.size(size.dp).clip(CircleShape).background(color.copy(alpha = 0.22f)))
        Box(Modifier.size((size * 0.6f).dp).clip(CircleShape).background(color))
    }
}

/** Carousel tile for a starred trail: status, name, when you last rode it. */
@Composable
private fun StarredTile(t: Trail, nowMs: Long, onClick: () -> Unit) {
    val col = statusColor(t.status)
    Column(
        Modifier.width(150.dp).clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, col.copy(alpha = 0.30f), NeonCardShape)
            .clickable(enabled = t.visitsTotal > 0, onClick = onClick)
            .padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            StatusDot(col, 12)
            Spacer(Modifier.width(6.dp))
            Text((t.status ?: "unknown").uppercase(), color = col, fontFamily = NeonNumberFamily,
                fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        }
        Spacer(Modifier.height(6.dp))
        Text(t.name, color = NeonMV.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.heightIn(min = 38.dp))
        Spacer(Modifier.height(4.dp))
        Text(
            t.lastVisitAt?.let { "ridden ${fmtAge(it, nowMs)}" } ?: "not ridden yet",
            color = visitAgeColor(t.lastVisitAt, nowMs, true), fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TrailRow(
    t: Trail,
    nowMs: Long,
    dense: Boolean,
    expanded: Boolean,
    onTap: () -> Unit,
    onSubscribeToggle: () -> Unit,
    onLongPress: () -> Unit,
    onOpenTrailVisits: (Long) -> Unit,
    expandedMap: @Composable (Trail) -> Unit,
) {
    val color = statusColor(t.status)
    val hasLocation = t.latitude != null && t.longitude != null
    Column(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, color.copy(alpha = 0.18f), NeonCardShape)
            .combinedClickable(onClick = { if (hasLocation) onTap() }, onLongClick = onLongPress),
    ) {
        Row(
            Modifier.padding(start = 14.dp, end = 2.dp, top = if (dense) 2.dp else 8.dp,
                bottom = if (dense) 2.dp else 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusDot(color)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(t.name, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (!dense) {
                    if (!t.comment.isNullOrBlank()) Text(t.comment, color = NeonMV.Muted, fontSize = 12.sp)
                    val meta = listOfNotNull(
                        fmtAge(t.sourceTs ?: t.fetchedAt, nowMs).takeIf { it.isNotEmpty() },
                        listOfNotNull(t.city, t.state).joinToString(", ").takeIf { it.isNotEmpty() },
                    ).joinToString(" · ")
                    if (meta.isNotEmpty()) Text(meta, color = NeonMV.Muted, fontSize = 12.sp)
                    if (t.visitsTotal > 0) {
                        Spacer(Modifier.height(6.dp))
                        VisitChip(t, nowMs) { onOpenTrailVisits(t.id) }
                    }
                } else {
                    val age = fmtAge(t.sourceTs ?: t.fetchedAt, nowMs)
                    if (age.isNotEmpty()) Text(age, color = NeonMV.Muted, fontSize = 12.sp)
                }
            }
            if (hasLocation) {
                IconButton(onClick = onTap, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.Navigation,
                        contentDescription = if (expanded) "Hide map" else "Show map",
                        tint = if (expanded) NeonMV.Cyan else NeonMV.Muted,
                        modifier = Modifier.size(20.dp))
                }
            }
            IconButton(onClick = onSubscribeToggle, modifier = Modifier.size(48.dp)) {
                Icon(
                    if (t.subscribed) Icons.Outlined.Star else Icons.Outlined.StarBorder,
                    contentDescription = if (t.subscribed) "Unsubscribe" else "Subscribe",
                    tint = if (t.subscribed) NeonMV.Amber else NeonMV.Muted,
                )
            }
        }
        if (expanded && hasLocation) expandedMap(t)
    }
}

/** The linked-rides tap target: ≥32dp tall, 16dp icon, 12sp text. */
@Composable
private fun VisitChip(t: Trail, nowMs: Long, onClick: () -> Unit) {
    val c = visitAgeColor(t.lastVisitAt, nowMs, true)
    Row(
        Modifier.heightIn(min = 32.dp).clip(RoundedCornerShape(16.dp))
            .background(c.copy(alpha = 0.10f))
            .border(1.dp, c.copy(alpha = 0.35f), RoundedCornerShape(16.dp))
            .clickable(onClickLabel = "Show linked activities", onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.AutoMirrored.Outlined.DirectionsBike, contentDescription = null, tint = c,
            modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(
            "${t.visitsTotal} ride${if (t.visitsTotal == 1) "" else "s"}" +
                (t.lastVisitAt?.let { " · ${fmtAge(it, nowMs)}" } ?: ""),
            color = c, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
        )
        Icon(Icons.AutoMirrored.Outlined.KeyboardArrowRight, contentDescription = null, tint = c,
            modifier = Modifier.size(16.dp))
    }
}

/** A tapped trail's inline map + Navigate / Edit pin. */
@Composable
private fun ExpandedTrailMap(t: Trail, osmCacheEpoch: Int, onEditPin: () -> Unit) {
    val context = LocalContext.current
    val lat = t.latitude ?: return
    val lon = t.longitude ?: return
    val settings = remember { SettingsRepository(context) }
    var osmJson by remember(t.id, osmCacheEpoch) { mutableStateOf<String?>(null) }
    LaunchedEffect(t.id, osmCacheEpoch) {
        if (!settings.isConfigured()) return@LaunchedEffect
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.trailOsmPaths(t.id) }
            if (resp.isSuccessful) {
                val raw = resp.body()?.string()
                if (!raw.isNullOrBlank()) {
                    osmJson = org.json.JSONObject(raw).optJSONObject("geojson")?.toString()
                }
            }
        } catch (e: Exception) {
            Timber.d(e, "trailOsmPaths(${t.id}) — no cache or fetch failed")
        }
    }
    MiniMap(lat, lon, t.name, osmJson, true)
    Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            onClick = { openMapsNav(context, t) },
            colors = ButtonDefaults.buttonColors(containerColor = NeonMV.Cyan, contentColor = NeonMV.OnAccent),
            modifier = Modifier.weight(1f),
        ) {
            Icon(Icons.Outlined.Navigation, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("Navigate")
        }
        OutlinedButton(onClick = onEditPin, modifier = Modifier.weight(1f)) { Text("Edit pin") }
    }
}

@Composable
private fun RideLinkRow(ride: ActivityRow, nowMs: Long, onTap: () -> Unit) {
    val typeLabel = ride.type.replace("Ride", " ride", ignoreCase = true).trim()
    val sub = listOfNotNull(
        fmtAge(ride.startAt, nowMs).takeIf { it.isNotEmpty() },
        ride.distanceM?.let { Units.fmtDistance(it, 1) },
        typeLabel.takeIf { it.isNotEmpty() },
    ).joinToString(" · ")
    Row(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .clickable { onTap() }
            .heightIn(min = 56.dp)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(ride.name?.takeIf { it.isNotBlank() } ?: typeLabel.ifBlank { "Activity" },
                color = NeonMV.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
            Text(sub, color = NeonMV.Muted, fontSize = 12.sp)
        }
        if (ride.trailName != null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.Link, contentDescription = "Linked trail", tint = NeonMV.Muted,
                    modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(4.dp))
                Text(ride.trailName, color = NeonMV.Muted, fontSize = 12.sp)
            }
        } else {
            Text("Link…", color = NeonMV.Cyan, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

private fun rideSubtitle(ride: ActivityRow): String {
    val mi = Units.fmtDistance(ride.distanceM, 1)
    val mins = ride.durationS / 60
    return "${ride.type} · $mi · ${mins}m"
}

/** Visit-recency colour scale, matching the web's age-fresh → age-stale ramp. */
private fun visitAgeColor(iso: String?, nowMs: Long, neon: Boolean = false): Color {
    if (iso == null) return if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val days = try { (nowMs - Instant.parse(iso).toEpochMilli()) / 86_400_000L }
               catch (_: Exception) { return if (neon) NeonMV.Muted else MV.OnSurfaceVariant }
    return when {
        days < 7   -> if (neon) NeonMV.Lime else Color(0xFF22C55E)   // fresh — green
        days < 30  -> if (neon) NeonMV.Lime else Color(0xFF84CC16)   // recent — lime
        days < 90  -> if (neon) NeonMV.Amber else Color(0xFFF59E0B)  // medium — amber
        days < 180 -> if (neon) NeonMV.Amber else Color(0xFFFB923C)  // old — orange
        else       -> if (neon) NeonMV.Muted else Color(0xFF94A3B8)  // stale — slate
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun MiniMap(lat: Double, lon: Double, name: String, osmGeoJson: String? = null, neon: Boolean = false) {
    val ctx = LocalContext.current
    val leafletCss = remember { app.myvitals.ui.common.LeafletAssets.css(ctx) }
    val leafletJs = remember { app.myvitals.ui.common.LeafletAssets.js(ctx) }
    // Neon-aware web colours — byte-identical classic values when neon == false.
    val mapBgHex = if (neon) "#0F1118" else "#0F1620"
    val pinHex = if (neon) "#5DFF3B" else "#22C55E"
    val osmLineHex = if (neon) "#9B9BB0" else "#94a3b8"
    val nameEsc = name
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", " ")
        .replace("\r", "")
    val osmLiteral = osmGeoJson ?: "null"
    // Leaflet CSS + JS are inlined directly so the WebView has no
    // sub-resource fetches at all. Tiles still need network (CARTO CDN);
    // offline → pin on a dark background.
    val html = """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="initial-scale=1.0,width=device-width"/>
<style>$leafletCss
html,body{margin:0;padding:0;background:$mapBgHex;overflow:hidden;}
#m{display:block;}</style>
</head><body>
<div id="m"></div>
<script>$leafletJs</script>
<script>
window.addEventListener('error', e => console.error('JS error:', e.message));
// Some Android WebView layouts leave document.body.clientHeight at 0
// even after the viewport has measured. Drive the map div size from
// window.innerHeight/innerWidth, and re-set it on every resize.
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
try {
  window.map = L.map('m', {zoomControl:true,scrollWheelZoom:false}).setView([$lat,$lon], 14);
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19,maxNativeZoom:16,attribution:'© OSM, Tiles © Esri'}).addTo(window.map);
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19,maxNativeZoom:16,pane:'shadowPane'}).addTo(window.map);
  // CSS-only pin (avoids the broken-image fallback when Leaflet's
  // default PNG marker can't resolve under loadDataWithBaseURL(null)).
  const pinIcon = L.divIcon({
    html: '<div style="width:18px;height:18px;border-radius:50%;'
        + 'background:$pinHex;border:2px solid #FFFFFF;'
        + 'box-shadow:0 2px 6px rgba(0,0,0,0.6);"></div>',
    className: 'mvpin', iconSize: [18,18], iconAnchor: [9,9],
  });
  L.marker([$lat,$lon], {icon: pinIcon}).addTo(window.map)
    .bindPopup('$nameEsc').openPopup();
  const osm = $osmLiteral;
  let osmLayer = null;
  if (osm) {
    osmLayer = L.geoJSON(osm, {
      style: {color:'$osmLineHex', weight:3, opacity:0.9, dashArray:'6,4'}
    }).addTo(window.map);
  }
  function fix() {
    try {
      applySize();
      window.map.invalidateSize();
      if (osmLayer && window.innerHeight > 0) {
        try { window.map.fitBounds(osmLayer.getBounds().pad(0.1)); }
        catch (e) {}
      }
    } catch (e) {}
  }
  window.addEventListener('resize', fix);
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(fix).observe(document.documentElement);
  }
  setTimeout(fix, 50); setTimeout(fix, 250); setTimeout(fix, 800);
  setTimeout(() => console.log(
    'map size:', window.map.getSize().x, 'x', window.map.getSize().y,
    'innerH:', window.innerHeight, 'bodyH:', document.body.clientHeight,
  ), 900);
} catch (e) { console.error('map init failed:', e.toString()); }
</script></body></html>"""
    app.myvitals.ui.common.LeafletWebView(
        html = html,
        modifier = Modifier.fillMaxWidth().height(220.dp),
    )
}

/** Aggregate map: every pinned trail as a colored marker. Mirrors the
 *  web /trails/map view. green=open, amber=delayed, red=closed,
 *  slate=unknown. Click a pin → popup with name + status + age. */
@Composable
private fun TrailsOverviewMap(
    trails: List<Trail>,
    nowMs: Long,
    modifier: Modifier = Modifier.fillMaxSize(),
    /** False for the hero preview: no controls, no panning — the box
     *  around it is the button that opens the full map. */
    interactive: Boolean = true,
) {
    val neon = true
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val leafletCss = remember { app.myvitals.ui.common.LeafletAssets.css(ctx) }
    val leafletJs = remember { app.myvitals.ui.common.LeafletAssets.js(ctx) }
    // Neon-aware web colours — byte-identical classic values when neon == false.
    val mapBgHex = if (neon) "#0F1118" else "#0F1620"
    val popAgeHex = if (neon) "#9B9BB0" else "#64748b"
    val pinned = trails.filter { it.latitude != null && it.longitude != null }
    val markersJs = buildString {
        append("[")
        for ((i, t) in pinned.withIndex()) {
            if (i > 0) append(",")
            val color = when (t.status) {
                "open" -> if (neon) "#5DFF3B" else "#22C55E"
                "delayed" -> if (neon) "#FFB52E" else "#EAB308"
                "closed" -> if (neon) "#FF5D7A" else "#EF4444"
                else -> if (neon) "#9B9BB0" else "#94A3B8"
            }
            val nameEsc = (t.name).replace("\\", "\\\\").replace("'", "\\'")
                .replace("\n", " ").replace("\r", "")
            val statusEsc = (t.status ?: "unknown").replace("'", "\\'")
            val age = fmtAge(t.sourceTs ?: t.fetchedAt, nowMs)
                .replace("'", "\\'")
            append(
                "{lat:${t.latitude},lon:${t.longitude}," +
                "color:'$color',name:'$nameEsc',status:'$statusEsc',age:'$age'}"
            )
        }
        append("]")
    }
    val centerLat = pinned.firstOrNull()?.latitude ?: 39.0
    val centerLon = pinned.firstOrNull()?.longitude ?: -94.6
    val html = """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="initial-scale=1.0,width=device-width"/>
<style>$leafletCss
html,body{margin:0;padding:0;background:$mapBgHex;overflow:hidden;}
#m{display:block;}
.lpop{font-family:sans-serif;min-width:180px;}
.lpop .nm{font-weight:600;margin-bottom:3px;}
.lpop .st{font-size:0.78rem;text-transform:uppercase;letter-spacing:0.06em;font-weight:600;}
.lpop .ag{color:$popAgeHex;font-size:0.78rem;margin-top:2px;}
</style>
</head><body>
<div id="m"></div>
<script>$leafletJs</script>
<script>
function applySize(){const w=window.innerWidth||360,h=window.innerHeight||400;
  const m=document.getElementById('m');m.style.width=w+'px';m.style.height=h+'px';
  document.body.style.height=h+'px';document.documentElement.style.height=h+'px';}
applySize();
try{
  const map=L.map('m',{zoomControl:$interactive,scrollWheelZoom:false,dragging:$interactive,touchZoom:$interactive,doubleClickZoom:$interactive,boxZoom:$interactive,keyboard:$interactive,attributionControl:$interactive}).setView([$centerLat,$centerLon],10);
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19,maxNativeZoom:16,attribution:'© OSM, Tiles © Esri'}).addTo(map);
  L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    {maxZoom:19,maxNativeZoom:16,pane:'shadowPane'}).addTo(map);
  const pins=$markersJs;
  const bounds=L.latLngBounds([]);
  pins.forEach(p=>{
    const icon=L.divIcon({
      html:'<div style="width:16px;height:16px;border-radius:50%;background:'+p.color
          +';border:2px solid #FFFFFF;box-shadow:0 2px 4px rgba(0,0,0,0.5);"></div>',
      className:'mvpin',iconSize:[16,16],iconAnchor:[8,8]});
    L.marker([p.lat,p.lon],{icon}).addTo(map).bindPopup(
      '<div class="lpop"><div class="nm">'+p.name+'</div>'
      +'<div class="st" style="color:'+p.color+'">'+p.status+'</div>'
      +'<div class="ag">updated '+p.age+'</div></div>');
    bounds.extend([p.lat,p.lon]);
  });
  if(pins.length>0&&bounds.isValid()) map.fitBounds(bounds.pad(0.1));
  function fix(){applySize();map.invalidateSize();}
  window.addEventListener('resize',fix);
  setTimeout(fix,50);setTimeout(fix,300);setTimeout(fix,800);
}catch(e){console.error('overview map failed:',e.toString());}
</script></body></html>"""
    app.myvitals.ui.common.LeafletWebView(
        html = html, modifier = modifier,
    )
}

private fun openMapsNav(context: android.content.Context, t: Trail) {
    val lat = t.latitude ?: return
    val lon = t.longitude ?: return
    val label = Uri.encode(t.name)
    // Try in order: Google's navigation: scheme (turn-by-turn), generic geo:,
    // then a final https://maps fallback. Skip resolveActivity — on Android 12+
    // it requires a <queries> manifest declaration and silently returns null
    // otherwise, which used to make every trail tap appear to do nothing.
    // Just try startActivity directly; ActivityNotFoundException → next URI.
    val candidates = listOf(
        Uri.parse("google.navigation:q=$lat,$lon"),
        Uri.parse("geo:$lat,$lon?q=$lat,$lon($label)"),
        Uri.parse("https://www.google.com/maps/search/?api=1&query=$lat,$lon"),
    )
    for (uri in candidates) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, uri).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            })
            return
        } catch (_: Exception) { /* try next */ }
    }
    Timber.w("openMapsNav: no map app could handle the intent")
}

private fun fmtAge(iso: String?, nowMs: Long): String {
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
