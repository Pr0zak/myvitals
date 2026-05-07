package app.myvitals.ui.activities

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityLinkTrailBody
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.sync.Trail
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActivityDetailScreen(
    settings: SettingsRepository,
    source: String,
    sourceId: String,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var activity by remember { mutableStateOf<ActivityRow?>(null) }
    var trails by remember { mutableStateOf<List<Trail>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var showPicker by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured."; loading = false; return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val (a, ts) = withContext(Dispatchers.IO) {
                Pair(api.activity(source, sourceId), api.trails())
            }
            activity = a
            trails = ts.trails.sortedBy { it.name }
            error = null
            Timber.i(
                "activity loaded: %s/%s — type=%s avg_hr=%s polyline_len=%d trail_id=%s",
                a.source, a.sourceId, a.type,
                a.avgHr?.toString() ?: "null",
                a.polyline?.length ?: 0,
                a.trailId?.toString() ?: "null",
            )
        } catch (e: Exception) {
            Timber.w(e, "activity load failed for %s/%s", source, sourceId)
            error = e.message?.take(160)
        } finally { loading = false }
    }

    suspend fun setTrail(trailId: Long?) {
        saving = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) {
                api.linkActivityTrail(source, sourceId, ActivityLinkTrailBody(trailId))
            }
            if (resp.isSuccessful) {
                showPicker = false
                load()
            }
        } catch (e: Exception) {
            Timber.w(e, "link failed")
        } finally { saving = false }
    }

    LaunchedEffect(source, sourceId) { load() }

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Text(
                activity?.name?.takeIf { it.isNotBlank() }
                    ?: activity?.let { prettyType(it.type) }
                    ?: "Activity",
                color = MV.OnSurface, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
                maxLines = 1,
            )
        }

        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red, modifier = Modifier.padding(16.dp))
            activity == null -> Text("Not found", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            else -> {
                val a = activity!!
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item { StatsCard(a) }
                    if (!a.polyline.isNullOrBlank() ||
                        (a.trailId != null && trails.any { it.id == a.trailId && it.latitude != null })) {
                        item { ActivityMap(a, trails) }
                    }
                    item { TrailLinkCard(a, trails, onPick = { showPicker = true }) }
                    if (!a.notes.isNullOrBlank()) {
                        item {
                            Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
                                Column(Modifier.padding(12.dp)) {
                                    Text("Notes", color = MV.OnSurfaceVariant,
                                        fontSize = 11.sp, fontWeight = FontWeight.Bold,
                                        letterSpacing = 1.5.sp)
                                    Text(a.notes, color = MV.OnSurface, fontSize = 14.sp)
                                }
                            }
                        }
                    }
                }
            }
        }

        if (showPicker && activity != null) {
            val a = activity!!
            ModalBottomSheet(
                onDismissRequest = { if (!saving) showPicker = false },
                containerColor = MV.SurfaceContainer,
            ) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Text("Link to trail", color = MV.OnSurface,
                        fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(6.dp))
                    val pickable = remember(trails) {
                        trails.filter { it.latitude != null && it.longitude != null }
                            .sortedBy { it.name }
                    }
                    LazyColumn(
                        Modifier.fillMaxWidth().height(360.dp),
                        verticalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        items(pickable, key = { it.id }) { t ->
                            val isCurrent = t.id == a.trailId
                            Card(
                                colors = CardDefaults.cardColors(
                                    containerColor =
                                        if (isCurrent) MV.BrandRed.copy(alpha = 0.15f)
                                        else MV.SurfaceContainerLow,
                                ),
                                modifier = Modifier.fillMaxWidth().clickable(enabled = !saving) {
                                    scope.launch { setTrail(t.id) }
                                },
                            ) {
                                Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                                    verticalAlignment = Alignment.CenterVertically) {
                                    Text(t.name, modifier = Modifier.weight(1f),
                                        color = MV.OnSurface, fontSize = 14.sp)
                                    val cs = listOfNotNull(t.city, t.state).joinToString(", ")
                                    if (cs.isNotEmpty()) {
                                        Text(cs, color = MV.OnSurfaceDim, fontSize = 11.sp)
                                    }
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
    }
}

@Composable
private fun StatsCard(a: ActivityRow) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text(prettyType(a.type), color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Text(formatStartAt(a.startAt), color = MV.OnSurface, fontSize = 14.sp)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                a.distanceM?.let { Stat("Distance", "%.2f mi".format(it / 1609.34)) }
                Stat("Duration", "${a.durationS / 60}m")
                a.elevationGainM?.let { Stat("Elev", "%.0f ft".format(it * 3.28084)) }
            }
            if (a.avgHr != null || a.kcal != null) {
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    a.avgHr?.let { Stat("Avg HR", "%.0f bpm".format(it)) }
                    a.maxHr?.let { Stat("Max HR", "%.0f bpm".format(it)) }
                    a.kcal?.let { Stat("kcal", "%.0f".format(it)) }
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun TrailLinkCard(a: ActivityRow, trails: List<Trail>, onPick: () -> Unit) {
    val linked = a.trailId?.let { id -> trails.firstOrNull { it.id == id } }
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().clickable { onPick() },
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Link, contentDescription = null,
                tint = MV.OnSurfaceVariant, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                if (linked != null) {
                    Text("Linked to", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    Text(linked.name, color = MV.OnSurface, fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold)
                    val visits = linked.visitsTotal
                    if (visits > 0) {
                        Text("${visits} all-time visit${if (visits == 1) "" else "s"}",
                            color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    }
                } else {
                    Text("Not linked", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    Text("Tap to link a trail", color = MV.OnSurface, fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun ActivityMap(a: ActivityRow, trails: List<Trail>) {
    val polylineEsc = a.polyline?.replace("'", "\\'") ?: ""
    val trail = a.trailId?.let { id -> trails.firstOrNull { it.id == id } }
    val trailLat = trail?.latitude
    val trailLon = trail?.longitude
    val nameEsc = trail?.name?.replace("'", "\\'") ?: ""
    val html = """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="initial-scale=1.0,width=device-width"/>
<link rel="stylesheet" href="leaflet.css"/>
<style>html,body{height:100%;margin:0;background:#0F1620;}
#m{position:absolute;top:0;left:0;right:0;bottom:0;}</style>
</head><body>
<div id="m"></div>
<script src="leaflet.js"></script>
<script>
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
  const map = L.map('m', {zoomControl:true,scrollWheelZoom:false}).setView([39, -94], 13);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {subdomains:'abcd',maxZoom:19,attribution:'© OSM, © CARTO'}).addTo(map);
  const enc = '$polylineEsc';
  let bounds = null;
  if (enc.length > 0) {
    const pts = decodePolyline(enc);
    if (pts.length > 1) {
      const line = L.polyline(pts, {color:'#ef4444', weight:3, opacity:0.9}).addTo(map);
      bounds = line.getBounds();
    }
  }
  ${if (trailLat != null && trailLon != null) """
  const m = L.marker([$trailLat,$trailLon]).addTo(map).bindPopup('$nameEsc');
  if (bounds) bounds.extend([$trailLat,$trailLon]);
  else bounds = L.latLngBounds([$trailLat,$trailLon], [$trailLat,$trailLon]);
  """ else ""}
  if (bounds) map.fitBounds(bounds.pad(0.1));
  setTimeout(() => map.invalidateSize(), 50);
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
                setBackgroundColor(android.graphics.Color.parseColor("#0F1620"))
                loadDataWithBaseURL(
                    "file:///android_asset/leaflet/", html, "text/html", "utf-8", null,
                )
                tag = html
            }
        },
        update = { webview ->
            if (webview.tag != html) {
                webview.loadDataWithBaseURL(
                    "file:///android_asset/leaflet/", html, "text/html", "utf-8", null,
                )
                webview.tag = html
            }
        },
        modifier = Modifier.fillMaxWidth().height(260.dp),
    )
}

private fun formatStartAt(iso: String): String =
    try {
        val ldt = java.time.OffsetDateTime.parse(iso)
            .atZoneSameInstant(java.time.ZoneId.systemDefault())
        ldt.format(java.time.format.DateTimeFormatter.ofPattern("EEE MMM d, h:mm a"))
    } catch (_: Exception) { iso }
