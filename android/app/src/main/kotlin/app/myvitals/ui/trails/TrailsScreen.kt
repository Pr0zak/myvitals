package app.myvitals.ui.trails

import android.content.Intent
import android.net.Uri
import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
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
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material.icons.outlined.Navigation
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.runtime.derivedStateOf
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.input.KeyboardType
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityLinkTrailBody
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.sync.Trail
import app.myvitals.sync.TrailLocationBody
import app.myvitals.sync.TrailSubscribeBody
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TrailsScreen(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var trails by remember { mutableStateOf<List<Trail>>(emptyList()) }
    var dnisUrl by remember { mutableStateOf<String?>(null) }
    var showOverviewMap by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    // Mini-map preview state
    val expandedTrail = remember { mutableStateOf<Long?>(null) }
    fun togglePreview(t: Trail) {
        expandedTrail.value = if (expandedTrail.value == t.id) null else t.id
    }

    // Header action state
    var linking by remember { mutableStateOf(false) }
    var fetchingOsm by remember { mutableStateOf(false) }
    var actionResult by remember { mutableStateOf<String?>(null) }
    // Bumped after a fetch-all-osm-paths run so expanded TrailRows refetch
    // their geometry from the (possibly newly-cached) backend.
    var osmCacheEpoch by remember { mutableStateOf(0) }

    // Recent rides + link-to-trail picker
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
        // SWR: render last cached trails immediately.
        val cached = app.myvitals.data.JsonCache.read<List<Trail>>(
            context, "trails_list",
            app.myvitals.data.JsonCache.listType(Trail::class.java),
        )
        if (cached != null) {
            trails = cached.value.sortedBy { it.name }
            loading = false
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.trails() }
            trails = r.trails.sortedBy { it.name }
            dnisUrl = r.dnisUrl
            app.myvitals.data.JsonCache.write(
                context, "trails_list",
                app.myvitals.data.JsonCache.listType(Trail::class.java),
                trails,
            )
            error = null
            val o = trails.count { it.status == "open" }
            val d = trails.count { it.status == "delayed" }
            val c = trails.count { it.status == "closed" }
            Timber.i("trails loaded: %d total — %d open, %d delayed, %d closed",
                trails.size, o, d, c)
        } catch (e: Exception) {
            Timber.w(e, "trails load failed")
            error = e.message?.take(160)
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
            Timber.i("trails refresh: fetched=%d snapshots=%d alerts=%d",
                r.fetched, r.snapshots, r.alerts)
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
            val rows = withContext(Dispatchers.IO) { api.activities(limit = 30) }
            // Keep types most likely to match a trail visit
            recentRides = rows.filter { r ->
                val t = r.type
                t.contains("Ride", ignoreCase = true) ||
                    t.contains("Run", ignoreCase = true) ||
                    t.contains("Hike", ignoreCase = true) ||
                    t.contains("Walk", ignoreCase = true)
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
                load()  // refresh trail visit counts
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
            Timber.i("OSM fetch: fetched=%d skipped=%d failed=%d total=%d",
                r.fetched, r.skipped, r.failed, r.totalWithPins)
            actionResult = if (r.fetched == 0 && r.skipped > 0)
                "All ${r.skipped} routes already cached. Tap a trail to view."
                else "OSM: ${r.fetched} fetched · ${r.skipped} cached · ${r.failed} failed"
            // Bump the cache epoch so any expanded trail's WebView refetches.
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
            error = e.message?.take(160)
        }
    }

    LaunchedEffect(Unit) { load() }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }
    LaunchedEffect(Unit) { loadRecentRides() }
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    data class TrailGroups(
        val open: List<Trail>,
        val closed: List<Trail>,
        val delayed: List<Trail>,
        val other: List<Trail>,
    )

    val grouped by remember(trails) {
        derivedStateOf {
            // Sort each status bucket newest-first by source_ts (when the
            // source flipped), falling back to fetched_at then
            // last_seen_at. Mirrors the web Trails view.
            fun keyOf(t: Trail): Long {
                val v = t.sourceTs ?: t.fetchedAt ?: t.lastSeenAt
                return runCatching {
                    java.time.OffsetDateTime.parse(v).toInstant().toEpochMilli()
                }.getOrDefault(0L)
            }
            val cmp = compareByDescending<Trail> { keyOf(it) }
            TrailGroups(
                open = trails.filter { it.status == "open" }.sortedWith(cmp),
                closed = trails.filter { it.status == "closed" }.sortedWith(cmp),
                delayed = trails.filter { it.status == "delayed" }.sortedWith(cmp),
                other = trails.filter {
                    it.status != "open" && it.status != "closed" && it.status != "delayed"
                }.sortedWith(cmp),
            )
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text(
                    "TRAILS",
                    color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp,
                )
                Text(
                    if (trails.isEmpty()) "—"
                    else listOfNotNull(
                        "${grouped.open.size} open",
                        if (grouped.delayed.isNotEmpty()) "${grouped.delayed.size} delayed" else null,
                        "${grouped.closed.size} closed",
                    ).joinToString(" · "),
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
                val mostRecentFetch = remember(trails) {
                    trails.mapNotNull { it.fetchedAt }.maxOrNull()
                }
                if (mostRecentFetch != null) {
                    Text(
                        "synced ${fmtAge(mostRecentFetch, nowMs)}",
                        color = MV.OnSurfaceDim, fontSize = 10.sp,
                    )
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                // Aggregate-map overlay — every pinned trail with status colour.
                IconButton(onClick = { showOverviewMap = true }) {
                    Icon(
                        Icons.Outlined.Map,
                        contentDescription = "Trail status map",
                        tint = MV.OnSurfaceVariant,
                    )
                }
                // RainoutLine status board shortcut — same as web header.
                if (dnisUrl != null) {
                    val ctxLink = androidx.compose.ui.platform.LocalContext.current
                    IconButton(
                        onClick = {
                            val intent = android.content.Intent(
                                android.content.Intent.ACTION_VIEW,
                                android.net.Uri.parse(dnisUrl),
                            )
                            ctxLink.startActivity(intent)
                        },
                    ) {
                        Icon(
                            Icons.AutoMirrored.Outlined.OpenInNew,
                            contentDescription = "Open RainoutLine status board",
                            tint = MV.OnSurfaceVariant,
                        )
                    }
                }
                IconButton(onClick = { scope.launch { refreshNow() } }, enabled = !refreshing) {
                    Icon(Icons.Outlined.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
                }
                var menuOpen by remember { mutableStateOf(false) }
                Box {
                    IconButton(onClick = { menuOpen = true }) {
                        Icon(Icons.Outlined.MoreVert, contentDescription = "More",
                            tint = MV.OnSurface)
                    }
                    DropdownMenu(
                        expanded = menuOpen, onDismissRequest = { menuOpen = false },
                    ) {
                        DropdownMenuItem(
                            text = { Text(if (linking) "Linking rides…" else "Link rides to trails") },
                            enabled = !linking,
                            onClick = { menuOpen = false; scope.launch { linkActivities() } },
                        )
                        DropdownMenuItem(
                            text = { Text(if (fetchingOsm) "Fetching OSM…" else "Fetch OSM routes") },
                            enabled = !fetchingOsm,
                            onClick = { menuOpen = false; scope.launch { fetchOsmRoutes() } },
                        )
                    }
                }
            }
        }
        if (actionResult != null) {
            Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
            ) {
                Row(
                    Modifier.padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(actionResult!!,
                        modifier = Modifier.weight(1f),
                        color = MV.OnSurface, fontSize = 12.sp)
                    TextButton(onClick = { actionResult = null }) {
                        Text("OK", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    }
                }
            }
        }

        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = loading || refreshing,
            onRefresh = { scope.launch { refreshNow(); load(); loadRecentRides() } },
            modifier = Modifier.weight(1f),
        ) {
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant)
            error != null -> Text(error!!, color = MV.Red)
            trails.isEmpty() -> Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "No trails seeded yet. The backend poller runs every 15 minutes; tap Refresh to trigger an immediate poll.",
                    modifier = Modifier.padding(14.dp),
                    color = MV.OnSurfaceVariant,
                )
            }
            else -> LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (grouped.open.isNotEmpty()) {
                    item { GroupHeader("Open · ${grouped.open.size}") }
                    items(grouped.open, key = { it.id }) { t ->
                        TrailRow(t, nowMs, osmCacheEpoch = osmCacheEpoch,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
                    }
                }
                if (grouped.delayed.isNotEmpty()) {
                    item { GroupHeader("Delayed · ${grouped.delayed.size}") }
                    items(grouped.delayed, key = { it.id }) { t ->
                        TrailRow(t, nowMs, osmCacheEpoch = osmCacheEpoch,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
                    }
                }
                if (grouped.closed.isNotEmpty()) {
                    item { GroupHeader("Closed · ${grouped.closed.size}") }
                    items(grouped.closed, key = { it.id }) { t ->
                        TrailRow(t, nowMs, osmCacheEpoch = osmCacheEpoch,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
                    }
                }
                if (grouped.other.isNotEmpty()) {
                    item { GroupHeader("Other · ${grouped.other.size}") }
                    items(grouped.other, key = { it.id }) { t ->
                        TrailRow(t, nowMs, osmCacheEpoch = osmCacheEpoch,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
                    }
                }

                if (recentRides.isNotEmpty()) {
                    item { GroupHeader("Recent rides · tap to link a trail") }
                    items(recentRides, key = { "${it.source}-${it.sourceId}" }) { ride ->
                        RideLinkRow(ride, nowMs, onTap = { linkTarget = ride })
                    }
                }
            }
        }
        }  // end PullToRefreshBox

        // Link-trail bottom sheet
        if (linkTarget != null) {
            val ride = linkTarget!!
            ModalBottomSheet(
                onDismissRequest = { if (!linkSaving) linkTarget = null },
                containerColor = MV.SurfaceContainer,
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("Link to trail", color = MV.OnSurface,
                        fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                    Text(rideSubtitle(ride), color = MV.OnSurfaceVariant, fontSize = 12.sp)
                    if (ride.trailName != null) {
                        Text("Currently linked: ${ride.trailName}",
                            color = MV.OnSurfaceVariant, fontSize = 12.sp)
                    }
                    Spacer(Modifier.height(6.dp))

                    val pickable = remember(trails) {
                        trails.filter { it.latitude != null && it.longitude != null }
                            .sortedBy { it.name }
                    }
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().height(360.dp),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        items(pickable, key = { it.id }) { t ->
                            val isCurrent = t.id == ride.trailId
                            Card(
                                colors = CardDefaults.cardColors(
                                    containerColor =
                                        if (isCurrent) MV.BrandRed.copy(alpha = 0.15f)
                                        else MV.SurfaceContainerLow,
                                ),
                                modifier = Modifier.fillMaxWidth().clickable(enabled = !linkSaving) {
                                    scope.launch { setRideTrail(ride, t.id) }
                                },
                            ) {
                                Row(
                                    Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(t.name, modifier = Modifier.weight(1f),
                                        color = MV.OnSurface, fontSize = 14.sp)
                                    val cityStr = listOfNotNull(t.city, t.state).joinToString(", ")
                                    if (cityStr.isNotEmpty()) {
                                        Text(cityStr, color = MV.OnSurfaceDim, fontSize = 11.sp)
                                    }
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
                                enabled = !linkSaving,
                                modifier = Modifier.weight(1f),
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
            ModalBottomSheet(
                onDismissRequest = { editTrail = null },
                containerColor = MV.SurfaceContainer,
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Edit pin · ${t.name}",
                        color = MV.OnSurface, fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold)
                    Text("Decimal degrees. Tip: tap & hold a spot in Google Maps and the lat/lon pair appears at the top.",
                        color = MV.OnSurfaceVariant, fontSize = 11.sp)

                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = editLat, onValueChange = { editLat = it },
                            label = { Text("Latitude") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = editLon, onValueChange = { editLon = it },
                            label = { Text("Longitude") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = editCity, onValueChange = { editCity = it },
                            label = { Text("City (optional)") },
                            singleLine = true,
                            modifier = Modifier.weight(2f),
                        )
                        OutlinedTextField(
                            value = editState, onValueChange = { editState = it },
                            label = { Text("State") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }

                    OutlinedButton(
                        onClick = {
                            // Open Maps centered on existing pin (or search by name)
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
                    ) { Text("🗺  Open in Maps to find coords") }

                    if (editError != null) {
                        Text(editError!!, color = MV.Red, fontSize = 12.sp)
                    }
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
                                containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                            ),
                            modifier = Modifier.weight(1f),
                        ) { Text(if (editSaving) "Saving…" else "Save") }
                        OutlinedButton(
                            onClick = { editTrail = null },
                            modifier = Modifier.weight(1f),
                        ) { Text("Cancel") }
                    }
                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }

    // Fullscreen aggregate-map overlay — same UX as web /trails/map.
    if (showOverviewMap) {
        androidx.compose.ui.window.Dialog(
            onDismissRequest = { showOverviewMap = false },
            properties = androidx.compose.ui.window.DialogProperties(
                usePlatformDefaultWidth = false,
            ),
        ) {
            Box(modifier = Modifier.fillMaxSize().background(MV.Bg)) {
                TrailsOverviewMap(trails, nowMs)
                IconButton(
                    onClick = { showOverviewMap = false },
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(8.dp)
                        .background(
                            color = androidx.compose.ui.graphics.Color(0xCC0F1620),
                            shape = androidx.compose.foundation.shape.CircleShape,
                        ),
                ) {
                    Icon(
                        Icons.Outlined.Close,
                        contentDescription = "Close map",
                        tint = MV.OnSurface,
                    )
                }
            }
        }
    }
}

@Composable
private fun GroupHeader(text: String) {
    Text(
        text, color = MV.OnSurfaceVariant,
        fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
        modifier = Modifier.padding(top = 10.dp, bottom = 2.dp),
    )
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TrailRow(
    t: Trail, nowMs: Long,
    expanded: Boolean = false,
    osmCacheEpoch: Int = 0,
    onTap: () -> Unit,
    onSubscribeToggle: () -> Unit,
    onLongPress: () -> Unit,
) {
    val context = LocalContext.current
    val color = when (t.status) {
        "open" -> Color(0xFF22C55E)
        "closed" -> Color(0xFFEF4444)
        "delayed" -> Color(0xFFEAB308)  // amber — RainoutLine "Delayed"
        else -> MV.OnSurfaceVariant
    }
    val hasLocation = t.latitude != null && t.longitude != null
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().combinedClickable(
            onClick = { if (hasLocation) onTap() },
            onLongClick = onLongPress,
        ),
    ) {
        Column {
            Row(
                modifier = Modifier.padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(modifier = Modifier.size(10.dp).clip(CircleShape).background(color))
                Spacer(Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(t.name, color = MV.OnSurface, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                    if (!t.comment.isNullOrBlank()) {
                        Text(t.comment, color = MV.OnSurfaceVariant, fontSize = 12.sp)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        val ageStr = remember(nowMs, t.sourceTs, t.fetchedAt) {
                            fmtAge(t.sourceTs ?: t.fetchedAt, nowMs)
                        }
                        if (ageStr.isNotEmpty()) {
                            Text(ageStr, color = MV.OnSurfaceDim, fontSize = 11.sp)
                        }
                        val cityStr = listOfNotNull(t.city, t.state).joinToString(", ")
                        if (cityStr.isNotEmpty()) {
                            Text(
                                "  ·  $cityStr",
                                color = MV.OnSurfaceDim, fontSize = 11.sp,
                            )
                        }
                        if (t.visitsTotal > 0) {
                            val visitColor = visitAgeColor(t.lastVisitAt, nowMs)
                            Text("  ·  ", color = MV.OnSurfaceDim, fontSize = 11.sp)
                            Icon(
                                Icons.AutoMirrored.Outlined.DirectionsBike,
                                contentDescription = "Visits",
                                tint = visitColor,
                                modifier = Modifier.size(12.dp),
                            )
                            Text(
                                " ${t.visitsTotal}",
                                color = visitColor, fontSize = 11.sp,
                                fontWeight = FontWeight.Medium,
                            )
                            if (t.lastVisitAt != null) {
                                Text(
                                    " · ${fmtAge(t.lastVisitAt, nowMs)}",
                                    color = MV.OnSurfaceDim, fontSize = 10.sp,
                                )
                            }
                        }
                        if (hasLocation) {
                            Spacer(Modifier.width(6.dp))
                            Icon(
                                Icons.Outlined.Navigation,
                                contentDescription = "Open mini map",
                                tint = MV.OnSurfaceDim,
                                modifier = Modifier.size(12.dp),
                            )
                        }
                    }
                }
                IconButton(onClick = onSubscribeToggle) {
                    Icon(
                        if (t.subscribed) Icons.Outlined.Star else Icons.Outlined.StarBorder,
                        contentDescription = if (t.subscribed) "Unsubscribe" else "Subscribe",
                        tint = if (t.subscribed) MV.Amber else MV.OnSurfaceVariant,
                    )
                }
            }

            // Mini-map preview when expanded
            if (expanded && t.latitude != null && t.longitude != null) {
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
                                osmJson = org.json.JSONObject(raw)
                                    .optJSONObject("geojson")?.toString()
                            }
                        }
                    } catch (e: Exception) {
                        Timber.d(e, "trailOsmPaths(${t.id}) — no cache or fetch failed")
                    }
                }
                MiniMap(t.latitude, t.longitude, t.name, osmJson)
                Row(
                    Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Button(
                        onClick = { openMapsNav(context, t) },
                        colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                            containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                        ),
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(Icons.Outlined.Navigation, contentDescription = null,
                            modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Navigate")
                    }
                    androidx.compose.material3.OutlinedButton(
                        onClick = onLongPress,
                        modifier = Modifier.weight(1f),
                    ) { Text("Edit pin") }
                }
            }
        }
    }
}

@Composable
private fun RideLinkRow(ride: ActivityRow, nowMs: Long, onTap: () -> Unit) {
    val context = LocalContext.current
    val typeLabel = ride.type.replace("Ride", " ride", ignoreCase = true).trim()
    val ageStr = remember(nowMs, ride.startAt) { fmtAge(ride.startAt, nowMs) }
    val distStr = ride.distanceM?.let { "${"%.1f".format(it / 1609.34)} mi" } ?: "—"
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().clickable { onTap() },
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    ride.name?.takeIf { it.isNotBlank() } ?: typeLabel.ifBlank { "Activity" },
                    color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Row {
                    Text("$ageStr  ·  $distStr", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    if (typeLabel.isNotEmpty()) {
                        Text("  ·  $typeLabel", color = MV.OnSurfaceDim, fontSize = 11.sp)
                    }
                }
            }
            if (ride.trailName != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Link, contentDescription = "Linked trail",
                        tint = MV.OnSurfaceVariant,
                        modifier = Modifier.size(12.dp))
                    Spacer(Modifier.width(4.dp))
                    Text(
                        ride.trailName,
                        color = MV.OnSurfaceVariant, fontSize = 11.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }
            } else {
                Text("Link…", color = MV.BrandRed, fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold)
            }
        }
    }
    // Suppress unused-import warning for context (kept in case we open a detail later)
    @Suppress("UNUSED_EXPRESSION") context
}

private fun rideSubtitle(ride: ActivityRow): String {
    val mi = ride.distanceM?.let { "%.1f mi".format(it / 1609.34) } ?: "—"
    val mins = ride.durationS / 60
    return "${ride.type} · $mi · ${mins}m"
}

/** Visit-recency colour scale, matching the web's age-fresh → age-stale ramp. */
private fun visitAgeColor(iso: String?, nowMs: Long): Color {
    if (iso == null) return MV.OnSurfaceVariant
    val days = try { (nowMs - Instant.parse(iso).toEpochMilli()) / 86_400_000L }
               catch (_: Exception) { return MV.OnSurfaceVariant }
    return when {
        days < 7   -> Color(0xFF22C55E)   // fresh — green
        days < 30  -> Color(0xFF84CC16)   // recent — lime
        days < 90  -> Color(0xFFF59E0B)   // medium — amber
        days < 180 -> Color(0xFFFB923C)   // old — orange
        else       -> Color(0xFF94A3B8)   // stale — slate
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun MiniMap(lat: Double, lon: Double, name: String, osmGeoJson: String? = null) {
    val ctx = LocalContext.current
    val leafletCss = remember { app.myvitals.ui.common.LeafletAssets.css(ctx) }
    val leafletJs = remember { app.myvitals.ui.common.LeafletAssets.js(ctx) }
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
html,body{margin:0;padding:0;background:#0F1620;overflow:hidden;}
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
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {subdomains:'abcd',maxZoom:19,attribution:'© OSM, © CARTO'}).addTo(window.map);
  // CSS-only pin (avoids the broken-image fallback when Leaflet's
  // default PNG marker can't resolve under loadDataWithBaseURL(null)).
  const pinIcon = L.divIcon({
    html: '<div style="width:18px;height:18px;border-radius:50%;'
        + 'background:#22C55E;border:2px solid #FFFFFF;'
        + 'box-shadow:0 2px 6px rgba(0,0,0,0.6);"></div>',
    className: 'mvpin', iconSize: [18,18], iconAnchor: [9,9],
  });
  L.marker([$lat,$lon], {icon: pinIcon}).addTo(window.map)
    .bindPopup('$nameEsc').openPopup();
  const osm = $osmLiteral;
  let osmLayer = null;
  if (osm) {
    osmLayer = L.geoJSON(osm, {
      style: {color:'#94a3b8', weight:3, opacity:0.9, dashArray:'6,4'}
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
private fun TrailsOverviewMap(trails: List<Trail>, nowMs: Long) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val leafletCss = remember { app.myvitals.ui.common.LeafletAssets.css(ctx) }
    val leafletJs = remember { app.myvitals.ui.common.LeafletAssets.js(ctx) }
    val pinned = trails.filter { it.latitude != null && it.longitude != null }
    val markersJs = buildString {
        append("[")
        for ((i, t) in pinned.withIndex()) {
            if (i > 0) append(",")
            val color = when (t.status) {
                "open" -> "#22C55E"
                "delayed" -> "#EAB308"
                "closed" -> "#EF4444"
                else -> "#94A3B8"
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
html,body{margin:0;padding:0;background:#0F1620;overflow:hidden;}
#m{display:block;}
.lpop{font-family:sans-serif;min-width:180px;}
.lpop .nm{font-weight:600;margin-bottom:3px;}
.lpop .st{font-size:0.78rem;text-transform:uppercase;letter-spacing:0.06em;font-weight:600;}
.lpop .ag{color:#64748b;font-size:0.78rem;margin-top:2px;}
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
  const map=L.map('m',{zoomControl:true,scrollWheelZoom:false}).setView([$centerLat,$centerLon],10);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {subdomains:'abcd',maxZoom:19,attribution:'© OSM, © CARTO'}).addTo(map);
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
        html = html, modifier = Modifier.fillMaxSize(),
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
