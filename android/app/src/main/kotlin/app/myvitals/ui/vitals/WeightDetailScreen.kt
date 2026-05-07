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

private data class WPoint(val ms: Long, val kg: Double)

@Composable
fun WeightDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    var range by remember { mutableStateOf(VitalRange.MONTH) }
    var pts by remember { mutableStateOf<List<WPoint>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(range) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
        loading = true; error = null
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
            Timber.i("weight detail: range=%s points=%d", range, pts.size)
        } catch (e: Exception) {
            Timber.w(e, "weight detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Icon(Vital.WEIGHT.icon, contentDescription = null, tint = Vital.WEIGHT.color,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Weight", color = MV.OnSurface, fontSize = 16.sp,
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
                        selectedContainerColor = Vital.WEIGHT.color.copy(alpha = 0.20f),
                        selectedLabelColor = MV.OnSurface,
                    ),
                )
            }
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red, modifier = Modifier.padding(16.dp))
            pts.size < 2 -> Text("Need at least 2 weight readings in this window.",
                color = MV.OnSurfaceVariant, modifier = Modifier.padding(16.dp))
            else -> LazyColumn(
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item { WeightHero(pts) }
                item { WeightChart(pts, Vital.WEIGHT.color) }
                item { WeightStats(pts) }
            }
        }
    }
}

@Composable
private fun WeightHero(pts: List<WPoint>) {
    val latestLb = pts.last().kg * 2.20462
    val firstLb = pts.first().kg * 2.20462
    val delta = latestLb - firstLb
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LATEST", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Row(verticalAlignment = Alignment.Bottom) {
                Text("%.1f".format(latestLb), color = MV.OnSurface,
                    fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(6.dp))
                Text("lb", color = MV.OnSurfaceDim, fontSize = 12.sp,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
            val arrow = if (delta > 0.05) "↑" else if (delta < -0.05) "↓" else "→"
            val color = when {
                delta > 0.5 -> Color(0xFFFBBF24)
                delta < -0.5 -> Color(0xFF60A5FA)
                else -> MV.OnSurfaceDim
            }
            Text("$arrow %+.1f lb in window".format(delta),
                color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium)
        }
    }
}

@Composable
private fun WeightChart(pts: List<WPoint>, color: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TREND", color = MV.OnSurfaceVariant,
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
            Box(Modifier.fillMaxWidth().height(180.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val padX = 32.dp.toPx()
                    val padTop = 8.dp.toPx()
                    val padBot = 14.dp.toPx()
                    val plotW = size.width - padX
                    val plotH = size.height - padTop - padBot
                    val stepX = plotW / (n - 1).coerceAtLeast(1)
                    // Ticks
                    val ticks = listOf(maxV, (minV + maxV) / 2, minV)
                    for (yv in ticks) {
                        val py = padTop + ((maxV - yv) / span * plotH).toFloat()
                        drawLine(
                            color = MV.OnSurfaceDim.copy(alpha = 0.18f),
                            start = Offset(padX, py), end = Offset(size.width, py),
                            strokeWidth = 0.7.dp.toPx(),
                        )
                    }
                    // Trend line
                    val ty0 = (a + b * 0).toFloat()
                    val ty1 = (a + b * (n - 1)).toFloat()
                    val tpy0 = padTop + ((maxV - ty0) / span * plotH).toFloat()
                    val tpy1 = padTop + ((maxV - ty1) / span * plotH).toFloat()
                    drawLine(
                        color = color.copy(alpha = 0.55f),
                        start = Offset(padX, tpy0), end = Offset(size.width, tpy1),
                        strokeWidth = 1.2.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(
                            floatArrayOf(5.dp.toPx(), 4.dp.toPx())
                        ),
                    )
                    // Data line + dots
                    val path = androidx.compose.ui.graphics.Path()
                    for ((i, w) in lbs.withIndex()) {
                        val x = padX + i * stepX
                        val py = padTop + ((maxV - w) / span * plotH).toFloat()
                        if (i == 0) path.moveTo(x, py) else path.lineTo(x, py)
                        drawCircle(color = color, radius = 3.dp.toPx(),
                            center = Offset(x, py))
                    }
                    drawPath(path = path, color = color, style = Stroke(width = 2.dp.toPx()))
                }
                // Y-axis labels
                Column(Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.SpaceBetween) {
                    Text("%.1f".format(maxV), color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("%.1f".format((minV + maxV) / 2),
                        color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("%.1f".format(minV), color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp, bottom = 12.dp))
                }
            }
        }
    }
}

@Composable
private fun WeightStats(pts: List<WPoint>) {
    val lbs = pts.map { it.kg * 2.20462 }
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("STATS", color = MV.OnSurfaceVariant,
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
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}
