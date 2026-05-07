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

private data class BpReading(val ms: Long, val sys: Int, val dia: Int)

@Composable
fun BpDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    var pts by remember { mutableStateOf<List<BpReading>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
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
            Timber.i("BP detail: %d readings", pts.size)
        } catch (e: Exception) {
            Timber.w(e, "BP detail load failed")
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
            Icon(Vital.BP.icon, contentDescription = null, tint = Vital.BP.color,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Blood pressure", color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red, modifier = Modifier.padding(16.dp))
            pts.isEmpty() -> Text("No readings in the last 90 days.",
                color = MV.OnSurfaceVariant, modifier = Modifier.padding(16.dp))
            else -> LazyColumn(
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

@Composable
private fun BpHero(latest: BpReading) {
    val cat = bpCategory(latest.sys, latest.dia)
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LATEST", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Row(verticalAlignment = Alignment.Bottom) {
                Text("${latest.sys}/${latest.dia}", color = MV.OnSurface,
                    fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(6.dp))
                Text("mmHg", color = MV.OnSurfaceDim, fontSize = 12.sp,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).clip(RoundedCornerShape(2.dp)).background(cat.second))
                Spacer(Modifier.width(6.dp))
                Text(cat.first, color = cat.second, fontSize = 13.sp,
                    fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(8.dp))
                Text(formatLocal(latest.ms), color = MV.OnSurfaceDim, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun BpChart(pts: List<BpReading>) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TREND", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            val sysColor = Color(0xFFEF4444)
            val diaColor = Color(0xFFEC4899)
            val all = pts.flatMap { listOf(it.sys, it.dia) }
            val minY = (all.min() - 5).coerceAtLeast(40)
            val maxY = (all.max() + 5).coerceAtMost(220)
            val span = (maxY - minY).coerceAtLeast(1)
            Box(Modifier.fillMaxWidth().height(180.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val padX = 30.dp.toPx()
                    val padTop = 6.dp.toPx()
                    val padBot = 14.dp.toPx()
                    val plotW = size.width - padX
                    val plotH = size.height - padTop - padBot
                    val tStart = pts.first().ms
                    val tEnd = pts.last().ms.coerceAtLeast(tStart + 1)
                    val tSpanF = (tEnd - tStart).toFloat()
                    // Category bands (sys-axis only)
                    val bands = listOf(
                        0 to 120 to Color(0xFF22C55E),
                        120 to 130 to Color(0xFFFBBF24),
                        130 to 140 to Color(0xFFF97316),
                        140 to 220 to Color(0xFFEF4444),
                    )
                    for ((rangePair, col) in bands) {
                        val (lo, hi) = rangePair
                        if (hi <= minY || lo >= maxY) continue
                        val y0 = padTop + ((maxY - hi.coerceAtMost(maxY)) /
                            span.toFloat() * plotH)
                        val y1 = padTop + ((maxY - lo.coerceAtLeast(minY)) /
                            span.toFloat() * plotH)
                        drawRect(
                            color = col.copy(alpha = 0.06f),
                            topLeft = Offset(padX, y0),
                            size = Size(plotW, (y1 - y0).coerceAtLeast(0f)),
                        )
                    }
                    // Sys + dia lines
                    fun drawSeries(getter: (BpReading) -> Int, color: Color) {
                        val path = androidx.compose.ui.graphics.Path()
                        for ((i, r) in pts.withIndex()) {
                            val x = padX + ((r.ms - tStart) / tSpanF) * plotW
                            val py = padTop + ((maxY - getter(r)) /
                                span.toFloat() * plotH)
                            if (i == 0) path.moveTo(x, py) else path.lineTo(x, py)
                            drawCircle(color = color, radius = 3.dp.toPx(),
                                center = Offset(x, py))
                        }
                        drawPath(path = path, color = color, style = Stroke(width = 2.dp.toPx()))
                    }
                    drawSeries({ it.sys }, sysColor)
                    drawSeries({ it.dia }, diaColor)
                }
                Column(Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.SpaceBetween) {
                    Text("$maxY", color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("${(minY + maxY) / 2}", color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp))
                    Text("$minY", color = MV.OnSurfaceDim, fontSize = 9.sp,
                        modifier = Modifier.padding(start = 4.dp, bottom = 12.dp))
                }
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
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp)).background(color))
        Spacer(Modifier.width(4.dp))
        Text(label, color = MV.OnSurfaceVariant, fontSize = 11.sp)
    }
}

@Composable
private fun BpStats(pts: List<BpReading>) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("AVERAGES", color = MV.OnSurfaceVariant,
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
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LAST READINGS", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            for (r in pts) {
                val cat = bpCategory(r.sys, r.dia)
                Row(verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(vertical = 4.dp)) {
                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp))
                        .background(cat.second))
                    Spacer(Modifier.width(8.dp))
                    Text("${r.sys}/${r.dia}", color = MV.OnSurface, fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.width(80.dp))
                    Text(cat.first, color = cat.second, fontSize = 11.sp,
                        modifier = Modifier.weight(1f))
                    Text(formatLocal(r.ms), color = MV.OnSurfaceDim, fontSize = 11.sp)
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
        Text(value, color = MV.OnSurface, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun bpCategory(sys: Int, dia: Int): Pair<String, Color> {
    // ACC/AHA categories for systolic; pick worst of sys/dia.
    val sysCat = when {
        sys < 120 -> 0
        sys < 130 -> 1
        sys < 140 -> 2
        else -> 3
    }
    val diaCat = when {
        dia < 80 -> 0
        dia < 90 -> 2
        else -> 3
    }
    return when (maxOf(sysCat, diaCat)) {
        0 -> "Normal" to Color(0xFF22C55E)
        1 -> "Elevated" to Color(0xFFFBBF24)
        2 -> "Stage 1" to Color(0xFFF97316)
        else -> "Stage 2" to Color(0xFFEF4444)
    }
}

private fun formatLocal(ms: Long): String =
    DateTimeFormatter.ofPattern("M/d h:mm a")
        .format(Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()))
