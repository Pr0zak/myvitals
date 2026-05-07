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
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
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
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.trails() }
            trails = r.trails.sortedBy { it.name }
            error = null
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
            withContext(Dispatchers.IO) { api.refreshTrails() }
            load()
        } catch (e: Exception) {
            Timber.w(e, "trails refresh failed")
            error = e.message?.take(160)
        } finally {
            refreshing = false
        }
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
            actionResult = "OSM: ${r.fetched} fetched · ${r.skipped} cached · ${r.failed} failed"
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
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    val grouped by remember(trails) {
        derivedStateOf {
            Triple(
                trails.filter { it.status == "open" },
                trails.filter { it.status == "closed" },
                trails.filter { it.status != "open" && it.status != "closed" },
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
                    else "${grouped.first.size} open · ${grouped.second.size} closed",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(
                    onClick = { scope.launch { linkActivities() } },
                    enabled = !linking,
                ) {
                    Text(
                        if (linking) "Linking…" else "Link rides",
                        color = MV.OnSurface, fontSize = 12.sp,
                    )
                }
                TextButton(
                    onClick = { scope.launch { fetchOsmRoutes() } },
                    enabled = !fetchingOsm,
                ) {
                    Text(
                        if (fetchingOsm) "OSM…" else "OSM routes",
                        color = MV.OnSurface, fontSize = 12.sp,
                    )
                }
                TextButton(onClick = { scope.launch { refreshNow() } }, enabled = !refreshing) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
                    Spacer(Modifier.width(4.dp))
                    Text(if (refreshing) "…" else "Refresh", color = MV.OnSurface)
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
                if (grouped.first.isNotEmpty()) {
                    item { GroupHeader("Open · ${grouped.first.size}") }
                    items(grouped.first, key = { it.id }) { t ->
                        TrailRow(t, nowMs,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
                    }
                }
                if (grouped.second.isNotEmpty()) {
                    item { GroupHeader("Closed · ${grouped.second.size}") }
                    items(grouped.second, key = { it.id }) { t ->
                        TrailRow(t, nowMs,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
                    }
                }
                if (grouped.third.isNotEmpty()) {
                    item { GroupHeader("Other · ${grouped.third.size}") }
                    items(grouped.third, key = { it.id }) { t ->
                        TrailRow(t, nowMs,
                            expanded = expandedTrail.value == t.id,
                            onTap = { togglePreview(t) },
                            onSubscribeToggle = { scope.launch { toggleSubscribe(t) } },
                            onLongPress = { openEdit(t) })
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
    onTap: () -> Unit,
    onSubscribeToggle: () -> Unit,
    onLongPress: () -> Unit,
) {
    val context = LocalContext.current
    val color = when (t.status) {
        "open" -> Color(0xFF22C55E)
        "closed" -> Color(0xFFEF4444)
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
                            Text(
                                "  ·  🚴 ${t.visitsTotal}",
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
                                Icons.Filled.Navigation,
                                contentDescription = "Open mini map",
                                tint = MV.OnSurfaceDim,
                                modifier = Modifier.size(12.dp),
                            )
                        }
                    }
                }
                IconButton(onClick = onSubscribeToggle) {
                    Icon(
                        if (t.subscribed) Icons.Filled.Star else Icons.Filled.StarBorder,
                        contentDescription = if (t.subscribed) "Unsubscribe" else "Subscribe",
                        tint = if (t.subscribed) MV.Amber else MV.OnSurfaceVariant,
                    )
                }
            }

            // Mini-map preview when expanded
            if (expanded && t.latitude != null && t.longitude != null) {
                MiniMap(t.latitude, t.longitude, t.name)
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
                        Icon(Icons.Filled.Navigation, contentDescription = null,
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
private fun MiniMap(lat: Double, lon: Double, name: String) {
    val nameEsc = name.replace("'", "\\'")
    val html = """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="initial-scale=1.0,width=device-width"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>html,body,#m{height:100%;margin:0;background:#0F1620;}</style>
</head><body>
<div id="m"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map('m', {zoomControl:true,scrollWheelZoom:false}).setView([$lat,$lon], 14);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  {subdomains:'abcd',maxZoom:19,attribution:'© OSM, © CARTO'}).addTo(map);
L.marker([$lat,$lon]).addTo(map).bindPopup('$nameEsc').openPopup();
</script></body></html>"""
    AndroidView(
        factory = { ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                webViewClient = WebViewClient()
                setBackgroundColor(android.graphics.Color.parseColor("#0F1620"))
                loadDataWithBaseURL("https://localhost/", html, "text/html", "utf-8", null)
            }
        },
        modifier = Modifier.fillMaxWidth().height(220.dp),
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
