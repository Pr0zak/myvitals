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
import app.myvitals.sync.SleepNight
import app.myvitals.sync.SleepRawSegment
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val STAGE_COLORS = mapOf(
    "deep" to Color(0xFF1E40AF),
    "rem" to Color(0xFFA78BFA),
    "light" to Color(0xFF60A5FA),
    "awake" to Color(0xFFF97316),
    "wake" to Color(0xFFF97316),
    "out_of_bed" to Color(0xFF94A3B8),
    "unknown" to Color(0xFF64748B),
)

// Vertical order (top → bottom) when drawing hypnogram bands
private val HYPNO_ORDER = listOf("awake", "rem", "light", "deep")

@Composable
fun SleepDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    var nights by remember { mutableStateOf<List<SleepNight>>(emptyList()) }
    var lastRaw by remember { mutableStateOf<List<SleepRawSegment>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since = LocalDate.now().minusDays(13).toString()
            val rawSince = Instant.now().minusSeconds(48 * 3600).toString()
            coroutineScope {
                val nightsD = async(Dispatchers.IO) { api.sleepRange(since = since) }
                val rawD = async(Dispatchers.IO) { api.sleepRaw(since = rawSince) }
                nights = nightsD.await()
                lastRaw = rawD.await()
            }
            Timber.i("sleep detail: %d nights, %d raw segments", nights.size, lastRaw.size)
        } catch (e: Exception) {
            Timber.w(e, "sleep detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Text("Sleep", color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red, modifier = Modifier.padding(16.dp))
            else -> LazyColumn(
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item { LastNightHero(nights.lastOrNull()) }
                item { Hypnogram(lastRaw) }
                item { StageBreakdownChart(nights.takeLast(14)) }
                item { DurationTrend(nights.takeLast(14)) }
                item { StageLegend() }
            }
        }
    }
}

@Composable
private fun LastNightHero(n: SleepNight?) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LAST NIGHT", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            if (n == null) {
                Text("—", color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                return@Card
            }
            val totalH = n.totalS / 3600
            val totalM = (n.totalS % 3600) / 60
            Text("${totalH}h ${totalM}m", color = MV.OnSurface,
                fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
            Text(formatStartEnd(n), color = MV.OnSurfaceVariant, fontSize = 12.sp)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                val byStage = n.stages.associate { it.stage to it.durationS }
                for (st in HYPNO_ORDER) {
                    val s = byStage[st] ?: continue
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(8.dp)
                                .clip(RoundedCornerShape(2.dp))
                                .background(STAGE_COLORS[st] ?: MV.OnSurfaceDim))
                            Spacer(Modifier.width(4.dp))
                            Text(st.replaceFirstChar { it.titlecase() },
                                color = MV.OnSurfaceDim, fontSize = 10.sp,
                                fontWeight = FontWeight.Bold)
                        }
                        Text("${s / 60}m", color = MV.OnSurface, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}

@Composable
private fun Hypnogram(segments: List<SleepRawSegment>) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("HYPNOGRAM", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (segments.isEmpty()) {
                Text("No raw stage data for the last 48h.",
                    color = MV.OnSurfaceVariant, fontSize = 12.sp)
                return@Card
            }
            val parsed = remember(segments) {
                segments.mapNotNull { s ->
                    val t = runCatching { Instant.parse(s.time).toEpochMilli() }
                        .getOrNull() ?: return@mapNotNull null
                    Triple(t, t + s.durationS * 1000L, s.stage.lowercase())
                }
            }
            val tStart = parsed.minOfOrNull { it.first } ?: return@Card
            val tEnd = parsed.maxOfOrNull { it.second } ?: return@Card
            Box(Modifier.fillMaxWidth().height(140.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val span = (tEnd - tStart).toFloat().coerceAtLeast(1f)
                    val rowH = size.height / HYPNO_ORDER.size
                    // Faint bg gridlines per stage
                    for (i in 0..HYPNO_ORDER.size) {
                        val y = i * rowH
                        drawLine(
                            color = MV.OnSurfaceDim.copy(alpha = 0.18f),
                            start = Offset(0f, y), end = Offset(size.width, y),
                            strokeWidth = 0.7.dp.toPx(),
                        )
                    }
                    // Per-segment colored band on the matching row
                    for ((s, e, stage) in parsed) {
                        val idx = HYPNO_ORDER.indexOf(stage).takeIf { it >= 0 }
                            ?: continue
                        val x0 = ((s - tStart).toFloat() / span) * size.width
                        val x1 = ((e - tStart).toFloat() / span) * size.width
                        val y0 = idx * rowH + rowH * 0.18f
                        val h = rowH * 0.64f
                        drawRect(
                            color = STAGE_COLORS[stage] ?: MV.OnSurfaceDim,
                            topLeft = Offset(x0, y0),
                            size = Size((x1 - x0).coerceAtLeast(1f), h),
                        )
                    }
                }
                // Stage labels on the left
                Column(Modifier.fillMaxSize()) {
                    val rowFraction = 1f / HYPNO_ORDER.size
                    for (st in HYPNO_ORDER) {
                        Box(
                            Modifier.fillMaxWidth().height(140.dp * rowFraction),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            Text(st, color = MV.OnSurfaceDim,
                                fontSize = 9.sp, fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(start = 2.dp))
                        }
                    }
                }
            }
            // Time axis labels
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text(formatLocalHour(tStart), color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text(formatLocalHour((tStart + tEnd) / 2),
                    color = MV.OnSurfaceDim, fontSize = 9.sp)
                Text(formatLocalHour(tEnd), color = MV.OnSurfaceDim, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun StageBreakdownChart(nights: List<SleepNight>) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("STAGE BREAKDOWN — ${nights.size} NIGHTS",
                color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (nights.isEmpty()) {
                Text("No data.", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                return@Card
            }
            val maxTotal = (nights.maxOfOrNull { it.totalS } ?: 1).coerceAtLeast(1)
            Box(Modifier.fillMaxWidth().height(150.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val gap = 3.dp.toPx()
                    val barW = (size.width - gap * (nights.size - 1)) / nights.size
                    for ((i, n) in nights.withIndex()) {
                        val x = i * (barW + gap)
                        var yCursor = size.height
                        // Stack from bottom: deep → light → rem → awake
                        for (st in listOf("deep", "light", "rem", "awake", "wake", "out_of_bed", "unknown")) {
                            val s = n.stages.firstOrNull { it.stage.equals(st, true) }?.durationS ?: continue
                            val h = (s.toFloat() / maxTotal) * size.height
                            yCursor -= h
                            drawRect(
                                color = STAGE_COLORS[st.lowercase()] ?: MV.OnSurfaceDim,
                                topLeft = Offset(x, yCursor),
                                size = Size(barW, h),
                            )
                        }
                    }
                }
            }
            // Date strip — show every other day to keep it readable
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                for ((i, n) in nights.withIndex()) {
                    if (i % 2 == 0 || i == nights.lastIndex) {
                        Text(shortDate(n.date), color = MV.OnSurfaceDim, fontSize = 9.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun DurationTrend(nights: List<SleepNight>) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("DURATION", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(4.dp))
            if (nights.isEmpty()) {
                Text("—", color = MV.OnSurface, fontSize = 16.sp); return@Card
            }
            val avgH = nights.map { it.totalS }.average() / 3600.0
            val minN = nights.minByOrNull { it.totalS }
            val maxN = nights.maxByOrNull { it.totalS }
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                Stat("Avg", "%.1f h".format(avgH))
                if (minN != null) Stat("Min", "%.1f h".format(minN.totalS / 3600.0))
                if (maxN != null) Stat("Max", "%.1f h".format(maxN.totalS / 3600.0))
            }
            Spacer(Modifier.height(8.dp))
            Box(Modifier.fillMaxWidth().height(60.dp)) {
                SleepDurationLine(nights, color = STAGE_COLORS["light"] ?: Color(0xFF60A5FA))
            }
        }
    }
}

@Composable
private fun SleepDurationLine(nights: List<SleepNight>, color: Color) {
    Canvas(Modifier.fillMaxSize()) {
        if (nights.size < 2) return@Canvas
        val ys = nights.map { it.totalS.toFloat() / 3600f }
        val minY = ys.min()
        val maxY = ys.max()
        val span = (maxY - minY).coerceAtLeast(1f)
        val padY = size.height * 0.15f
        val plotH = size.height - 2 * padY
        val stepX = size.width / (ys.size - 1)
        // Goal line at 8h
        val gy = size.height - padY - ((8f - minY) / span) * plotH
        drawLine(
            color = color.copy(alpha = 0.30f),
            start = Offset(0f, gy), end = Offset(size.width, gy),
            strokeWidth = 1.dp.toPx(),
        )
        val path = androidx.compose.ui.graphics.Path()
        for ((i, y) in ys.withIndex()) {
            val x = i * stepX
            val py = size.height - padY - ((y - minY) / span) * plotH
            if (i == 0) path.moveTo(x, py) else path.lineTo(x, py)
            drawCircle(color = color, radius = 2.dp.toPx(), center = Offset(x, py))
        }
        drawPath(path = path, color = color, style = Stroke(width = 2.dp.toPx()))
    }
}

@Composable
private fun StageLegend() {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            for (st in HYPNO_ORDER) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(STAGE_COLORS[st] ?: MV.OnSurfaceDim))
                    Spacer(Modifier.width(4.dp))
                    Text(st, color = MV.OnSurface, fontSize = 11.sp)
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

private fun formatStartEnd(n: SleepNight): String {
    val zone = ZoneId.systemDefault()
    val s = n.start?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() }
    val e = n.end?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() }
    val fmt = DateTimeFormatter.ofPattern("h:mm a")
    return when {
        s == null || e == null -> n.date
        else -> "${fmt.format(s)} → ${fmt.format(e)}"
    }
}

private fun formatLocalHour(epochMs: Long): String {
    val zdt = Instant.ofEpochMilli(epochMs).atZone(ZoneId.systemDefault())
    return DateTimeFormatter.ofPattern("h a").format(zdt).lowercase()
}

private fun shortDate(iso: String): String =
    runCatching {
        val d = LocalDate.parse(iso)
        DateTimeFormatter.ofPattern("M/d").format(d)
    }.getOrDefault(iso)
