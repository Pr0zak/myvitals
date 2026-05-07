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
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.core.cartesian.data.lineSeries
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
    var hrPoints by remember {
        mutableStateOf<List<app.myvitals.sync.TimePoint>>(emptyList())
    }
    var maxHr by remember { mutableStateOf(190) }
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
            runCatching {
                withContext(Dispatchers.IO) { api.profile() }
            }.getOrNull()?.let { maxHr = it.maxHr() }
            trails = ts.trails.sortedBy { it.name }
            error = null
            Timber.i(
                "activity loaded: %s/%s — type=%s avg_hr=%s polyline_len=%d trail_id=%s",
                a.source, a.sourceId, a.type,
                a.avgHr?.toString() ?: "null",
                a.polyline?.length ?: 0,
                a.trailId?.toString() ?: "null",
            )
            // Pull the HR samples covering the activity window so we can
            // render an in-line series under the stats card.
            try {
                val start = java.time.Instant.parse(a.startAt)
                val end = start.plusSeconds(a.durationS.toLong())
                val series = withContext(Dispatchers.IO) {
                    api.heartRateSeries(since = start.toString(), until = end.toString())
                }
                hrPoints = series.points
                Timber.i("activity HR window: %d points", series.points.size)
            } catch (e: Exception) {
                Timber.w(e, "activity HR fetch failed")
                hrPoints = emptyList()
            }
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
                    if (hrPoints.isNotEmpty()) {
                        item { ActivityHrChart(hrPoints, maxHr = maxHr) }
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
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val leafletCss = remember { app.myvitals.ui.common.LeafletAssets.css(ctx) }
    val leafletJs = remember { app.myvitals.ui.common.LeafletAssets.js(ctx) }
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
html,body{margin:0;padding:0;background:#0F1620;overflow:hidden;}
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
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {subdomains:'abcd',maxZoom:19,attribution:'© OSM, © CARTO'}).addTo(window.map);
  const enc = '$polylineEsc';
  let bounds = null;
  if (enc.length > 0) {
    const pts = decodePolyline(enc);
    if (pts.length > 1) {
      const line = L.polyline(pts, {color:'#ef4444', weight:3, opacity:0.9}).addTo(window.map);
      bounds = line.getBounds();
    }
  }
  ${if (trailLat != null && trailLon != null) """
  const pinIcon = L.divIcon({
    html: '<div style="width:16px;height:16px;border-radius:50%;'
        + 'background:#22C55E;border:2px solid #FFFFFF;'
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
                setBackgroundColor(android.graphics.Color.parseColor("#0F1620"))
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
        modifier = Modifier.fillMaxWidth().height(260.dp),
    )
}

@Composable
private fun HrChart(points: List<app.myvitals.sync.TimePoint>) {
    val producer = remember {
        com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModelProducer()
    }
    LaunchedEffect(points) {
        if (points.size < 2) return@LaunchedEffect
        runCatching {
            // Parse + sort + dedupe by timestamp. Vico's series() expects
            // strictly-increasing x values and can OOM/throw on huge or
            // duplicate-x inputs — both common when watch HR is sampled
            // at second-granularity for a multi-hour ride.
            val pairs = points.mapNotNull { p ->
                val ms = runCatching {
                    java.time.Instant.parse(p.time).toEpochMilli()
                }.getOrNull() ?: return@mapNotNull null
                ms to p.value
            }
                .sortedBy { it.first }
                .distinctBy { it.first }
            if (pairs.size < 2) return@runCatching
            // Cap to ~600 points so wide line layers stay performant.
            val maxPoints = 600
            val sampled = if (pairs.size > maxPoints) {
                val stride = pairs.size.toDouble() / maxPoints
                (0 until maxPoints).map { i ->
                    pairs[(i * stride).toInt().coerceAtMost(pairs.lastIndex)]
                }
            } else pairs
            val origin = sampled.first().first
            val xs = sampled.map { (it.first - origin) / 60_000.0 }
            val ys = sampled.map { it.second }
            producer.runTransaction {
                lineSeries { series(x = xs, y = ys) }
            }
        }.onFailure { Timber.w(it, "HrChart series build failed") }
    }
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(12.dp)) {
            Text("HEART RATE", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold,
                letterSpacing = 1.5.sp,
                modifier = Modifier.padding(bottom = 8.dp))
            com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost(
                chart = com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart(
                    com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer(),
                    startAxis = com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis.rememberStart(),
                    bottomAxis = com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis.rememberBottom(),
                    // imports above provide rememberStart/rememberBottom factories
                ),
                modelProducer = producer,
                scrollState = com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState(),
                zoomState = com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState(),
                modifier = Modifier.fillMaxWidth().height(180.dp),
            )
        }
    }
}

private fun formatStartAt(iso: String): String =
    try {
        val ldt = java.time.OffsetDateTime.parse(iso)
            .atZoneSameInstant(java.time.ZoneId.systemDefault())
        ldt.format(java.time.format.DateTimeFormatter.ofPattern("EEE MMM d, h:mm a"))
    } catch (_: Exception) { iso }
