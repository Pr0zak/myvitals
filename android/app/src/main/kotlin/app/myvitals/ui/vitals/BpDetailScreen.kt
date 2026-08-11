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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
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
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import app.myvitals.ui.LocalAppTokens

private data class BpReading(val ms: Long, val sys: Int, val dia: Int)

@Composable
fun BpDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    val tok = LocalAppTokens.current
    val context = androidx.compose.ui.platform.LocalContext.current
    var pts by remember { mutableStateOf<List<BpReading>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val ptsType = remember {
        app.myvitals.data.JsonCache.listType(BpReading::class.java)
    }

    suspend fun load() {
        // SWR hydrate
        app.myvitals.data.JsonCache.read<List<BpReading>>(
            context, "bp_detail_points", ptsType,
        )?.let { pts = it.value; loading = false }
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since = LocalDate.now().minusDays(89).toString()
            val raw = withContext(Dispatchers.IO) { api.bpSeries(since = since).string() }
            val obj = JSONObject(raw)
            val arr = obj.optJSONArray("points") ?: org.json.JSONArray()
            val out = mutableListOf<BpReading>()
            for (i in 0 until arr.length()) {
                val p = arr.getJSONObject(i)
                val sys = p.optInt("systolic", -1)
                val dia = p.optInt("diastolic", -1)
                val t = p.optString("time").takeIf { it.isNotBlank() } ?: continue
                if (sys < 0 || dia < 0) continue
                runCatching { out += BpReading(Instant.parse(t).toEpochMilli(), sys, dia) }
            }
            pts = out.sortedBy { it.ms }
            if (pts.isNotEmpty()) {
                app.myvitals.data.JsonCache.write(
                    context, "bp_detail_points", ptsType, pts,
                )
            }
            Timber.i("BP detail: %d readings", pts.size)
        } catch (e: Exception) {
            Timber.w(e, "BP detail load failed")
            if (pts.isEmpty()) error = e.message?.take(160)
        } finally { loading = false }
    }
    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().background(tok.bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = tok.onSurface)
            }
            Icon(Vital.BP.icon, contentDescription = null, tint = Vital.BP.accent,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Blood pressure", color = tok.onSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        when {
            loading -> Text("Loading…", color = tok.onSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = tok.red, modifier = Modifier.padding(16.dp))
            pts.isEmpty() -> Text("No readings in the last 90 days.",
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
                    item { BpHero(pts.last()) }
                    if (pts.size >= 2) item { BpChart(pts) }
                    item { BpStats(pts) }
                    item { BpHistoryList(pts.takeLast(10).reversed()) }
                }
            }
        }
    }
}

@Composable
private fun BpHero(latest: BpReading) {
    val tok = LocalAppTokens.current
    val cat = bpCategory(latest.sys, latest.dia)
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LATEST", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Row(verticalAlignment = Alignment.Bottom) {
                Text("${latest.sys}/${latest.dia}", color = tok.onSurface,
                    fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(6.dp))
                Text("mmHg", color = tok.onSurfaceDim, fontSize = 12.sp,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).clip(RoundedCornerShape(2.dp)).background(cat.second))
                Spacer(Modifier.width(6.dp))
                Text(cat.first, color = cat.second, fontSize = 13.sp,
                    fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(8.dp))
                Text(formatLocal(latest.ms), color = tok.onSurfaceDim, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun BpChart(pts: List<BpReading>) {
    val tok = LocalAppTokens.current
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TREND", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val sysColor = Color(0xFFEF4444)
            val diaColor = Color(0xFFEC4899)
            val all = pts.flatMap { listOf(it.sys, it.dia) }
            Canvas(Modifier.fillMaxWidth().height(190.dp)) {
                val domain = niceDomain(
                    all.min().toFloat(), all.max().toFloat(), targetTicks = 4,
                )
                val g = chartGeom(domain, ChartInsets(
                    left = 30.dp.toPx(), top = 6.dp.toPx(),
                    right = 4.dp.toPx(), bottom = 16.dp.toPx(),
                ))
                val tStart = pts.first().ms
                val tEnd = pts.last().ms.coerceAtLeast(tStart + 1)
                val tSpanF = (tEnd - tStart).toFloat()
                // Category bands (sys-axis only). These stay semantic
                // green→red — a BP stage is a clinical fact, not a theme
                // choice, so they do NOT follow the shell accent.
                val catBands = listOf(
                    0 to 120 to Color(0xFF22C55E),
                    120 to 130 to Color(0xFFFBBF24),
                    130 to 140 to Color(0xFFF97316),
                    140 to 220 to Color(0xFFEF4444),
                )
                for ((rangePair, col) in catBands) {
                    val (lo, hi) = rangePair
                    if (hi <= domain.min || lo >= domain.max) continue
                    val y0 = g.y(hi.toFloat()); val y1 = g.y(lo.toFloat())
                    drawRect(
                        color = col.copy(alpha = 0.07f),
                        topLeft = Offset(g.left, y0),
                        size = Size(g.width, (y1 - y0).coerceAtLeast(0f)),
                    )
                }
                // The y labels used to be a SpaceBetween Column laid over the
                // Canvas, so they spread across the whole box while the plot
                // sat inside its padding — the numbers never lined up with
                // anything. Drawn on the same geometry as the data now.
                drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface) {
                    "%.0f".format(it)
                }
                fun drawSeries(getter: (BpReading) -> Int, color: Color) {
                    val path = androidx.compose.ui.graphics.Path()
                    for ((i, r) in pts.withIndex()) {
                        val x = g.left + ((r.ms - tStart) / tSpanF) * g.width
                        val py = g.y(getter(r).toFloat())
                        if (i == 0) path.moveTo(x, py) else path.lineTo(x, py)
                        // De-smear: skip per-point dots once the window is dense.
                        if (pts.size <= 31) drawCircle(color = color, radius = 2.5.dp.toPx(),
                            center = Offset(x, py))
                    }
                    drawPath(path = path, color = color, style = Stroke(
                        width = 2.dp.toPx(),
                        cap = androidx.compose.ui.graphics.StrokeCap.Round,
                        join = androidx.compose.ui.graphics.StrokeJoin.Round,
                    ))
                }
                drawSeries({ it.sys }, sysColor)
                drawSeries({ it.dia }, diaColor)
                drawXLabels(g, measurer, tok.onSurfaceDim, buildList {
                    add(0f to shortMdOfMs(pts.first().ms))
                    if (pts.size >= 5) add(0.5f to shortMdOfMs(pts[pts.size / 2].ms))
                    add(1f to shortMdOfMs(pts.last().ms))
                })
            }
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                LegendDot(sysColor, "Systolic")
                LegendDot(diaColor, "Diastolic")
            }
        }
    }
}

@Composable
private fun LegendDot(color: Color, label: String) {
    val tok = LocalAppTokens.current
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp)).background(color))
        Spacer(Modifier.width(4.dp))
        Text(label, color = tok.onSurfaceVariant, fontSize = 11.sp)
    }
}

@Composable
private fun BpStats(pts: List<BpReading>) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("AVERAGES", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Sys avg", "%.0f".format(pts.map { it.sys }.average()))
                Stat("Dia avg", "%.0f".format(pts.map { it.dia }.average()))
                Stat("Readings", "${pts.size}")
            }
        }
    }
}

@Composable
private fun BpHistoryList(pts: List<BpReading>) {
    val tok = LocalAppTokens.current
    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LAST READINGS", color = tok.onSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            for (r in pts) {
                val cat = bpCategory(r.sys, r.dia)
                Row(verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(vertical = 4.dp)) {
                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp))
                        .background(cat.second))
                    Spacer(Modifier.width(8.dp))
                    Text("${r.sys}/${r.dia}", color = tok.onSurface, fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.width(80.dp))
                    Text(cat.first, color = cat.second, fontSize = 11.sp,
                        modifier = Modifier.weight(1f))
                    Text(formatLocal(r.ms), color = tok.onSurfaceDim, fontSize = 11.sp)
                }
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

private fun bpCategory(sys: Int, dia: Int): Pair<String, Color> {
    // ACC/AHA categories; pick worst of sys/dia. This screen already had
    // the "worst of the two" rule right — Body.vue and BodyScreen did not.
    // Crisis added so it matches frontend/src/bp.ts and analytics/tiles.py.
    val sysCat = when {
        sys < 120 -> 0
        sys < 130 -> 1
        sys < 140 -> 2
        sys < 180 -> 3
        else -> 4
    }
    val diaCat = when {
        dia < 80 -> 0
        dia < 90 -> 2
        dia < 120 -> 3
        else -> 4
    }
    return when (maxOf(sysCat, diaCat)) {
        0 -> "Normal" to Color(0xFF22C55E)
        1 -> "Elevated" to Color(0xFFFBBF24)
        2 -> "Stage 1" to Color(0xFFF97316)
        3 -> "Stage 2" to Color(0xFFEF4444)
        else -> "Crisis" to Color(0xFFEF4444)
    }
}

private fun formatLocal(ms: Long): String =
    DateTimeFormatter.ofPattern("M/d h:mm a")
        .format(Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()))


/** "M/d" for an epoch-ms x-axis tick. */
private fun shortMdOfMs(ms: Long): String {
    val d = java.time.Instant.ofEpochMilli(ms)
        .atZone(java.time.ZoneId.systemDefault()).toLocalDate()
    return "${d.monthValue}/${d.dayOfMonth}"
}
