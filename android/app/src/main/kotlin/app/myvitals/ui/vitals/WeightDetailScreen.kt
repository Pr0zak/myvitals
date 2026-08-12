package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import app.myvitals.ui.LocalAppTokens

private data class WPoint(val ms: Long, val kg: Double)

@Composable
fun WeightDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    val tok = LocalAppTokens.current
    val context = androidx.compose.ui.platform.LocalContext.current
    var range by remember { mutableStateOf(VitalRange.MONTH) }
    var pts by remember { mutableStateOf<List<WPoint>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val ptsType = remember {
        app.myvitals.data.JsonCache.listType(WPoint::class.java)
    }

    suspend fun load() {
        val cacheKey = "weight_detail_${range.name.lowercase()}"
        app.myvitals.data.JsonCache.read<List<WPoint>>(
            context, cacheKey, ptsType,
        )?.let { pts = it.value; loading = false }
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        if (pts.isEmpty()) loading = true
        error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since = LocalDate.now().minusDays(range.days.toLong() - 1).toString()
            val raw = withContext(Dispatchers.IO) { api.weightSeries(since = since).string() }
            val obj = JSONObject(raw)
            val arr = obj.optJSONArray("points") ?: org.json.JSONArray()
            val out = mutableListOf<WPoint>()
            for (i in 0 until arr.length()) {
                val p = arr.getJSONObject(i)
                val w = p.optDouble("weight_kg", Double.NaN)
                val t = p.optString("time").takeIf { it.isNotBlank() } ?: continue
                if (w.isNaN()) continue
                runCatching { out += WPoint(Instant.parse(t).toEpochMilli(), w) }
            }
            pts = out
            if (pts.isNotEmpty()) {
                app.myvitals.data.JsonCache.write(context, cacheKey, ptsType, pts)
            }
            Timber.i("weight detail: range=%s points=%d", range, pts.size)
        } catch (e: Exception) {
            Timber.w(e, "weight detail load failed")
            if (pts.isEmpty()) error = e.message?.take(160)
        } finally { loading = false }
    }
    LaunchedEffect(range) { load() }

    Column(Modifier.fillMaxSize().background(tok.bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = tok.onSurface)
            }
            Icon(Vital.WEIGHT.icon, contentDescription = null, tint = Vital.WEIGHT.accent,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Weight", color = tok.onSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            VitalRange.entries.forEach { r ->
                FilterChip(
                    selected = r == range,
                    onClick = { range = r },
                    label = { Text(r.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = Vital.WEIGHT.accent.copy(alpha = 0.20f),
                        selectedLabelColor = tok.onSurface,
                    ),
                )
            }
        }
        when {
            loading -> Text("Loading…", color = tok.onSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = tok.red, modifier = Modifier.padding(16.dp))
            pts.size < 2 -> Text("Need at least 2 weight readings in this window.",
                color = tok.onSurfaceVariant, modifier = Modifier.padding(16.dp))
            else -> app.myvitals.ui.common.PullableMetricBox(
                refreshing = refreshing,
                onRefresh = {
                    refreshing = true
                    try { load() } finally { refreshing = false }
                },
            ) {
                LazyColumn(
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { WeightHero(pts) }
                    item { WeightChart(pts, Vital.WEIGHT.accent) }
                    item { WeightStats(pts) }
                }
            }
        }
    }
}

@Composable
private fun WeightHero(pts: List<WPoint>) {
    val tok = LocalAppTokens.current
    val latestLb = pts.last().kg * 2.20462
    val firstLb = pts.first().kg * 2.20462
    val delta = latestLb - firstLb
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LATEST", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Row(verticalAlignment = Alignment.Bottom) {
                Text("%.1f".format(latestLb), color = tok.onSurface,
                    fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(6.dp))
                Text("lb", color = tok.onSurfaceDim, fontSize = 12.sp,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
            val arrow = if (delta > 0.05) "↑" else if (delta < -0.05) "↓" else "→"
            val color = when {
                delta > 0.5 -> Color(0xFFFBBF24)
                delta < -0.5 -> Color(0xFF60A5FA)
                else -> tok.onSurfaceDim
            }
            Text("$arrow %+.1f lb in window".format(delta),
                color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium)
        }
    }
}

@Composable
private fun WeightChart(pts: List<WPoint>, color: Color) {
    val tok = LocalAppTokens.current
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TREND", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val lbs = pts.map { it.kg * 2.20462 }
            val minV = lbs.min()
            val maxV = lbs.max()
            val span = (maxV - minV).coerceAtLeast(0.5)
            // Linear regression a + b*x for trend overlay
            val n = pts.size
            val xs = pts.indices.map { it.toDouble() }
            val sumX = xs.sum(); val sumY = lbs.sum()
            val sumXY = xs.zip(lbs).sumOf { it.first * it.second }
            val sumX2 = xs.sumOf { it * it }
            val b = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX)
            val a = (sumY - b * sumX) / n
            Canvas(Modifier.fillMaxWidth().height(190.dp)) {
                val domain = niceDomain(minV.toFloat(), maxV.toFloat(), targetTicks = 4,
                    minStep = 1f)
                val g = chartGeom(domain, ChartInsets(
                    left = 34.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                // The labels used to be a separate SpaceBetween Column laid
                // over the Canvas, so they spread across the whole box while
                // the gridlines sat inside the padded plot — the numbers never
                // lined up with the lines they labelled. Drawn together now.
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface) {
                    "%.0f".format(it)
                }
                // Regression trend
                drawLine(
                    color = color.copy(alpha = 0.55f),
                    start = Offset(g.left, g.y(a.toFloat())),
                    end = Offset(g.right, g.y((a + b * (n - 1)).toFloat())),
                    strokeWidth = 1.2.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(
                        floatArrayOf(5.dp.toPx(), 4.dp.toPx())
                    ),
                )
                val path = androidx.compose.ui.graphics.Path()
                val area = androidx.compose.ui.graphics.Path()
                for ((i, w) in lbs.withIndex()) {
                    val x = g.x(i, n); val py = g.y(w.toFloat())
                    if (i == 0) {
                        path.moveTo(x, py); area.moveTo(x, g.bottom); area.lineTo(x, py)
                    } else { path.lineTo(x, py); area.lineTo(x, py) }
                    // De-smear: skip per-point dots once the window is dense.
                    if (n <= 31) drawCircle(color = color, radius = 2.5.dp.toPx(),
                        center = Offset(x, py))
                }
                area.lineTo(g.x(n - 1, n), g.bottom); area.close()
                drawPath(area, brush = androidx.compose.ui.graphics.Brush.verticalGradient(
                    listOf(color.copy(alpha = 0.22f), color.copy(alpha = 0f)),
                    startY = g.top, endY = g.bottom,
                ))
                drawPath(path = path, color = color, style = Stroke(
                    width = 2.dp.toPx(),
                    cap = androidx.compose.ui.graphics.StrokeCap.Round,
                    join = androidx.compose.ui.graphics.StrokeJoin.Round,
                ))
                drawLatestMarker(
                    Offset(g.x(n - 1, n), g.y(lbs.last().toFloat())),
                    color, tok.surfaceContainer,
                )
                drawXLabels(g, measurer, tok.onSurfaceDim, buildList {
                    pts.firstOrNull()?.let { add(0f to shortMdOf(it.ms)) }
                    if (n >= 5) add(0.5f to shortMdOf(pts[n / 2].ms))
                    pts.lastOrNull()?.let { add(1f to shortMdOf(it.ms)) }
                })
            }
        }
    }
}

@Composable
private fun WeightStats(pts: List<WPoint>) {
    val tok = LocalAppTokens.current
    val lbs = pts.map { it.kg * 2.20462 }
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("STATS", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Min", "%.1f lb".format(lbs.min()))
                Stat("Avg", "%.1f lb".format(lbs.average()))
                Stat("Max", "%.1f lb".format(lbs.max()))
                Stat("Readings", "${pts.size}")
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    val tok = LocalAppTokens.current
    Column {
        Text(label, color = tok.onSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = tok.onSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}


/** "M/d" for an epoch-ms x-axis tick. */
private fun shortMdOf(ms: Long): String {
    val d = java.time.Instant.ofEpochMilli(ms)
        .atZone(java.time.ZoneId.systemDefault()).toLocalDate()
    return "${d.monthValue}/${d.dayOfMonth}"
}
