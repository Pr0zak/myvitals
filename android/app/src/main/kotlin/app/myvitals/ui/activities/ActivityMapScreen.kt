package app.myvitals.ui.activities

import android.annotation.SuppressLint
import android.webkit.JavascriptInterface
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CenterFocusStrong
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.ZoomOutMap
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityMapResponse
import app.myvitals.sync.BackendClient
import app.myvitals.sync.MapTrack
import app.myvitals.ui.common.LeafletAssets
import app.myvitals.ui.common.LeafletWebView
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * Every GPS-tracked activity drawn on one map.
 *
 * The tracks come from `GET /activities/map` already RDP-simplified
 * server-side (~400 KB for 559 tracks instead of 3.4 MB) — see
 * `analytics/geo.py`. Nothing is simplified or aggregated here; the
 * client just draws what the server sends, per the architecture rule.
 *
 * Rendering goes through the same Leaflet-in-WebView path as the
 * per-activity and trail-status maps. Tapping a track calls back through
 * a small JS bridge to open that activity's detail screen.
 */

/** Broad movement families, so the legend stays readable. The catalog has
 *  ~37 distinct `type` strings (Strava, Fitbit and MyFitnessPal all name
 *  things differently), which is far too many to colour individually. */
private enum class TrackKind(val label: String, val classic: Color, val neon: Color) {
    RIDE("Ride", Color(0xFF3B82F6), NeonMV.Cyan),
    RUN("Run", Color(0xFFEF4444), Color(0xFFFF4D6D)),
    WALK("Walk", Color(0xFF22C55E), NeonMV.Lime),
    HIKE("Hike", Color(0xFFF59E0B), Color(0xFFFFB020)),
    PADDLE("Paddle", Color(0xFFA855F7), Color(0xFFC084FC)),
    OTHER("Other", Color(0xFF94A3B8), Color(0xFF7C8BA1)),
}

private fun kindOf(type: String): TrackKind {
    val t = type.lowercase()
    return when {
        t.contains("kayak") || t.contains("row") || t.contains("paddle") ||
            t.contains("canoe") -> TrackKind.PADDLE
        t.contains("hike") -> TrackKind.HIKE
        // Check run before walk: "running" contains neither, but several
        // MyFitnessPal types embed both words in one label.
        t.contains("run") || t.contains("jog") -> TrackKind.RUN
        t.contains("walk") -> TrackKind.WALK
        t.contains("bike") || t.contains("cycl") || t.contains("ride") ||
            t.contains("bicycl") -> TrackKind.RIDE
        else -> TrackKind.OTHER
    }
}

private fun Color.toHex(): String = String.format(
    "#%02X%02X%02X", (red * 255).toInt(), (green * 255).toInt(), (blue * 255).toInt(),
)

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun ActivityMapScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    val neon = settings.neonShellEnabled

    var tracks by remember { mutableStateOf<List<MapTrack>>(emptyList()) }
    var bounds by remember { mutableStateOf<List<Double>?>(null) }
    var primaryBounds by remember { mutableStateOf<List<Double>?>(null) }
    // false = open on the home cluster, true = fit every track. Server
    // decides what "home cluster" means so web and phone agree.
    var fitAll by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var kindFilter by remember { mutableStateOf<TrackKind?>(null) }

    val bg = if (neon) NeonMV.Bg else Color(0xFF0F1620)
    val cardBg = if (neon) NeonMV.Card else Color(0xFF16202B)
    val line = if (neon) NeonMV.Line else Color(0xFF243244)
    val fg = if (neon) NeonMV.Ink else Color(0xFFE2E8F0)
    val dim = if (neon) NeonMV.Muted else Color(0xFF94A3B8)

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.activitiesMap() }
            tracks = resp.tracks
            bounds = resp.bounds
            primaryBounds = resp.primaryBounds
            error = null
            JsonCache.write(context, CACHE_KEY, ActivityMapResponse::class.java, resp)
            Timber.i("activity map: ${resp.returned} tracks")
        } catch (e: Exception) {
            Timber.w(e, "activity map load failed")
            // Keep whatever is already drawn — a failed refresh should not
            // blank a map the user is looking at.
            if (tracks.isEmpty()) error = e.message ?: "Failed to load map"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        JsonCache.read<ActivityMapResponse>(
            context, CACHE_KEY, ActivityMapResponse::class.java,
        )?.value?.let {
            tracks = it.tracks
            bounds = it.bounds
            primaryBounds = it.primaryBounds
            loading = false
        }
        fetch()
    }

    val shown = remember(tracks, kindFilter) {
        if (kindFilter == null) tracks else tracks.filter { kindOf(it.type) == kindFilter }
    }

    val bridge = remember {
        object {
            @JavascriptInterface
            fun openActivity(source: String, sourceId: String) {
                // WebView callbacks arrive off the main thread.
                scope.launch { onOpenActivity(source, sourceId) }
            }
        }
    }

    val leafletCss = remember { LeafletAssets.css(context) }
    val leafletJs = remember { LeafletAssets.js(context) }
    val fitTo = if (fitAll) bounds else (primaryBounds ?: bounds)
    val html = remember(shown, fitTo, neon) {
        buildMapHtml(shown, fitTo, neon, leafletCss, leafletJs)
    }

    Column(Modifier.fillMaxSize().background(bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back", tint = fg)
            }
            Column(Modifier.weight(1f)) {
                Text("Activity map", color = fg, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                Text(
                    if (loading && tracks.isEmpty()) "Loading…"
                    else "${shown.size} track${if (shown.size == 1) "" else "s"}" +
                        if (fitAll) " · all" else "",
                    color = dim, fontSize = 12.sp,
                )
            }
            // Only worth offering when the two extents actually differ —
            // with no far-flung activities they're the same view.
            if (primaryBounds != null && bounds != null && primaryBounds != bounds) {
                IconButton(onClick = { fitAll = !fitAll }) {
                    Icon(
                        if (fitAll) Icons.Outlined.CenterFocusStrong
                        else Icons.Outlined.ZoomOutMap,
                        contentDescription = if (fitAll) "Back to home area" else "Fit all activities",
                        tint = if (fitAll) (if (neon) NeonMV.Cyan else Color(0xFF3B82F6)) else fg,
                    )
                }
            }
            IconButton(
                onClick = {
                    if (!refreshing) scope.launch {
                        refreshing = true
                        try { fetch() } finally { refreshing = false }
                    }
                },
            ) {
                if (refreshing) {
                    CircularProgressIndicator(Modifier.size(18.dp), color = fg, strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Outlined.Refresh, "Refresh", tint = fg)
                }
            }
        }

        // Legend doubles as the filter — tap a kind to isolate it.
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())
                .padding(horizontal = 8.dp, vertical = 2.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val present = remember(tracks) {
                TrackKind.entries.filter { k -> tracks.any { kindOf(it.type) == k } }
            }
            KindChip("All", null, kindFilter == null, fg, dim, cardBg, line) { kindFilter = null }
            present.forEach { k ->
                val c = if (neon) k.neon else k.classic
                KindChip(k.label, c, kindFilter == k, fg, dim, cardBg, line) {
                    kindFilter = if (kindFilter == k) null else k
                }
            }
        }

        Box(Modifier.fillMaxSize()) {
            when {
                error != null && tracks.isEmpty() -> Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Couldn't load the map", color = fg, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(6.dp))
                    Text(error ?: "", color = dim, fontSize = 12.sp)
                }
                tracks.isEmpty() && !loading -> Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("No GPS tracks yet", color = fg, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Activities synced from Strava or imported with GPS "
                            + "will appear here.",
                        color = dim, fontSize = 12.sp,
                    )
                }
                else -> LeafletWebView(
                    html = html,
                    modifier = Modifier.fillMaxSize(),
                    jsInterface = bridge to "MvMap",
                )
            }
        }
    }
}

private const val CACHE_KEY = "activity_map_v1"

@Composable
private fun KindChip(
    label: String,
    dot: Color?,
    selected: Boolean,
    fg: Color,
    dim: Color,
    cardBg: Color,
    line: Color,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .clip(RoundedCornerShape(14.dp))
            .background(if (selected) (dot ?: fg).copy(alpha = 0.18f) else cardBg)
            .border(1.dp, if (selected) (dot ?: fg) else line, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (dot != null) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
            Spacer(Modifier.width(5.dp))
        }
        Text(label, color = if (selected) fg else dim, fontSize = 12.sp)
    }
}

/**
 * Build the Leaflet document. Track data is emitted as a JSON array and
 * decoded in-page rather than as generated JS statements — 559 tracks of
 * inline `L.polyline(...)` calls would be a megabyte of script for the
 * WebView to parse.
 */
private fun buildMapHtml(
    tracks: List<MapTrack>,
    bounds: List<Double>?,
    neon: Boolean,
    leafletCss: String,
    leafletJs: String,
): String {
    val pageBg = if (neon) "#0F1118" else "#0F1620"
    // Escape order matters: backslash FIRST. Google's polyline encoding is
    // full of backslashes and a stray '\u' aborts the whole script.
    fun esc(s: String?): String = (s ?: "")
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", " ")
        .replace("\r", "")

    val json = tracks.joinToString(",") { t ->
        val c = if (neon) kindOf(t.type).neon else kindOf(t.type).classic
        """{"p":"${esc(t.polyline)}","c":"${c.toHex()}","s":"${esc(t.source)}",""" +
            """"i":"${esc(t.sourceId)}","n":"${esc(t.name ?: t.type)}",""" +
            """"d":"${esc(t.startAt.take(10))}","t":"${esc(t.trailName)}"}"""
    }
    val fit = if (bounds != null && bounds.size == 4) {
        "map.fitBounds([[${bounds[0]},${bounds[1]}],[${bounds[2]},${bounds[3]}]]," +
            "{padding:[16,16]});"
    } else {
        "map.setView([39,-94],10);"
    }

    return """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="initial-scale=1.0,width=device-width"/>
<style>$leafletCss
html,body{margin:0;padding:0;background:$pageBg;overflow:hidden;}
#m{display:block;}
.mvpop{font:12px system-ui,sans-serif;}
.mvpop b{display:block;font-size:13px;margin-bottom:2px;}
.mvpop a{color:#2563eb;text-decoration:none;font-weight:600;}</style>
</head><body>
<div id="m"></div>
<script>$leafletJs</script>
<script>
function applySize() {
  const w = window.innerWidth || document.documentElement.clientWidth || 360;
  const h = window.innerHeight || document.documentElement.clientHeight || 400;
  const m = document.getElementById('m');
  m.style.width = w + 'px'; m.style.height = h + 'px';
  document.body.style.width = w + 'px'; document.body.style.height = h + 'px';
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
  const map = L.map('m', {zoomControl:true, preferCanvas:true}).setView([39,-94],10);
  window.map = map;
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {subdomains:'abcd',maxZoom:19,attribution:'© OSM, © CARTO'}).addTo(map);
  // preferCanvas above matters: 559 SVG paths make panning crawl on a
  // mid-range phone, while one canvas surface stays smooth.
  const data = [$json];
  data.forEach(function(t) {
    const pts = decodePolyline(t.p);
    if (pts.length < 2) return;
    const line = L.polyline(pts, {color:t.c, weight:3, opacity:0.75});
    line.on('click', function() {
      const trail = t.t ? '<br/>' + t.t : '';
      L.popup({closeButton:true})
        .setLatLng(pts[Math.floor(pts.length/2)])
        .setContent('<div class="mvpop"><b>' + t.n + '</b>' + t.d + trail +
          '<br/><a href="#" onclick="MvMap.openActivity(\'' + t.s +
          '\',\'' + t.i + '\');return false;">Open activity →</a></div>')
        .openOn(map);
    });
    line.on('mouseover', function() { line.setStyle({weight:5, opacity:1}); });
    line.on('mouseout',  function() { line.setStyle({weight:3, opacity:0.75}); });
    line.addTo(map);
  });
  $fit
  function fix() { applySize(); map.invalidateSize(); }
  window.addEventListener('resize', fix);
  setTimeout(fix, 60); setTimeout(fix, 300);
} catch (e) { console.error('map init failed: ' + e.message); }
</script>
</body></html>"""
}
