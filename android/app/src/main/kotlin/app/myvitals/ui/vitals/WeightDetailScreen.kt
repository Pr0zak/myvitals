package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.data.Units
import app.myvitals.sync.BackendClient
import app.myvitals.sync.VitalTile
import app.myvitals.sync.WeightDelta
import app.myvitals.sync.WeightHistogram
import app.myvitals.sync.WeightSeriesOut
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonScreen
import app.myvitals.ui.neon.NeonStatTile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Weight detail (UI-4). The hero is the latest weigh-in, the change over the
 * window coloured by the SERVER's tone, the goal distance, and the trend
 * line with the goal line. Every figure — min/avg/max, the 7- and 30-day
 * changes, the fitted trend, and whether a change counts as progress — comes
 * from `/query/weight`'s `stats` block (analytics/detail_stats.py). The
 * phone's own `weightDeltaTone` and its index-based regression are gone:
 * the colour of a weight change is GOAL-STATE's decision, made once.
 *
 * All values arrive in kilograms and are shown in the user's unit.
 *
 * UI-F1: the distribution histogram (`stats.histogram`, kg bands) and
 * "days at min" (`stats.days_at_min`, LOCAL days) are server fields too;
 * this screen only converts the band edges to the user's unit.
 */
@Composable
fun WeightDetailScreen(settings: SettingsRepository, onBack: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    var range by remember { mutableStateOf(VitalRange.MONTH) }
    var data by remember { mutableStateOf<WeightSeriesOut?>(null) }
    var tile by remember { mutableStateOf<VitalTile?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        val cacheKey = "weight_detail_v2_${range.name.lowercase()}"
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since = LocalDate.now().minusDays(range.days.toLong() - 1).toString()
            coroutineScope {
                val dD = async(Dispatchers.IO) { api.weightSeriesStats(since = since) }
                val tD = async(Dispatchers.IO) {
                    runCatching { api.summaryTiles().tiles.firstOrNull { it.key == "weight" } }.getOrNull()
                }
                data = dD.await()
                data?.let { JsonCache.write(context, cacheKey, WeightSeriesOut::class.java, it) }
                tile = tD.await()
            }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "weight detail load failed")
            // Kept alongside any cached series, never instead of it.
            error = e.message?.take(160) ?: "Couldn't reach the backend."
        } finally { loading = false }
    }
    LaunchedEffect(range) {
        data = JsonCache.read<WeightSeriesOut>(
            context, "weight_detail_v2_${range.name.lowercase()}", WeightSeriesOut::class.java,
        )?.value
        loading = data == null
        load()
    }

    val winEnd = System.currentTimeMillis()
    val winStart = LocalDate.now().minusDays(range.days.toLong() - 1)
        .atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
    WeightDetailContent(
        range = range, data = data, tile = tile, winStart = winStart, winEnd = winEnd,
        loading = loading, refreshing = refreshing, error = error,
        onBack = onBack, onRange = { range = it },
        onRefresh = { scope.launch { refreshing = true; try { load() } finally { refreshing = false } } },
    )
}

private fun toneColor(tone: String?): Color = when (tone) {
    "positive" -> NeonMV.Lime
    // Amber, never rose: drifting from a weight goal is worth noticing, not
    // a crisis (GOAL-STATE).
    "caution" -> NeonMV.Amber
    else -> NeonMV.Ink
}

private fun signedWeight(kg: Double?): String? {
    val v = Units.weight(kg) ?: return null
    return "%+.1f".format(v)
}

@Composable
fun WeightDetailContent(
    range: VitalRange,
    data: WeightSeriesOut?,
    tile: VitalTile?,
    winStart: Long,
    winEnd: Long,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    onBack: () -> Unit,
    onRange: (VitalRange) -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    val accent = Vital.WEIGHT.accent
    val u = Units.weightUnit
    NeonScreen(
        title = "Weight",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
        headerTrailing = { DetailTitleIcon(Vital.WEIGHT) },
    ) {
        app.myvitals.ui.common.VitalRangeGroup(
            selected = range, accent = accent, modifier = Modifier.padding(bottom = 10.dp),
        ) { onRange(it) }

        if (data == null) {
            if (error != null && !loading) NeonErrorBanner(error, title = "Couldn't load weight") { onRefresh() }
            else DetailSkeleton(accent)
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        // Above the cached chart, never replacing it.
        if (error != null) NeonErrorBanner("Showing your last saved copy. $error", title = "Couldn't refresh") { onRefresh() }

        val s = data.stats
        NeonHeroCard(accent) {
            NeonEyebrow("Latest", Modifier.padding(top = 0.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(Units.weight(s?.latestKg)?.let { "%.1f".format(it) } ?: "—", color = accent, size = 52)
                Spacer(Modifier.width(6.dp))
                Text(u, color = NeonMV.Muted, fontSize = 13.sp, modifier = Modifier.padding(bottom = 10.dp))
            }
            s?.deltaKg?.let { d ->
                val arrow = if (d > 0.02) "↑" else if (d < -0.02) "↓" else "→"
                // The arrow is a fact; the colour is the server's verdict,
                // which needs a goal and says nothing without one.
                Text("$arrow ${signedWeight(d)} $u over ${range.label}",
                    color = toneColor(s.tone), fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
            Spacer(Modifier.height(8.dp))
            val goalText = s?.goalKg?.let { g ->
                val gap = s.goalGapKg
                val gapWord = when {
                    gap == null -> null
                    kotlin.math.abs(Units.weight(gap) ?: 0.0) < 0.05 -> "at goal"
                    gap > 0 -> "%.1f %s to lose".format(Units.weight(gap), u)
                    else -> "%.1f %s to gain".format(Units.weight(-gap), u)
                }
                "Goal %.1f %s".format(Units.weight(g), u) + (gapWord?.let { " · $it" } ?: "")
            }
            // A distance to the goal takes no tone; a stale reading says so.
            DetailStatusChip(null, tile?.statusReason ?: goalText)
            if (tile?.statusReason != null && goalText != null) {
                Spacer(Modifier.height(6.dp))
                DetailStatusChip(null, goalText)
            }
            Spacer(Modifier.height(12.dp))
            if (data.points.count { it.weightKg != null } < 2) {
                DetailNote("Need at least 2 weigh-ins in this window to draw a trend.")
            } else {
                WeightTrendChart(data, accent, winStart, winEnd)
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for ((v, label) in listOf(
                Units.weight(s?.minKg)?.let { "%.1f".format(it) } to "Min $u",
                Units.weight(s?.avgKg)?.let { "%.1f".format(it) } to "Avg $u",
                Units.weight(s?.maxKg)?.let { "%.1f".format(it) } to "Max $u",
            )) NeonStatTile(v ?: "—", label, Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DeltaTile(s?.delta7d, "7-day Δ $u", Modifier.weight(1f))
            DeltaTile(s?.delta30d, "30-day Δ $u", Modifier.weight(1f))
            NeonStatTile("${s?.count ?: 0}", "Readings", Modifier.weight(1f))
        }
        val times = data.points.filter { it.weightKg != null }
            .mapNotNull { runCatching { Instant.parse(it.time).toEpochMilli() }.getOrNull() }
        s?.daysAtMin?.let { n ->
            Spacer(Modifier.height(8.dp))
            val low = Units.weight(s.minKg)?.let { "%.1f %s".format(it, u) } ?: "—"
            Text("Lowest reading, $low, on $n day${if (n == 1) "" else "s"}",
                color = NeonMV.Muted, fontSize = 11.sp)
        }
        coverageNote(times, winStart, winEnd) { mdOf(it) }?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = NeonMV.Muted, fontSize = 11.sp)
        }
        s?.histogram?.takeIf { it.bins.size >= 2 }?.let { h ->
            DetailCard(
                "Distribution",
                subtitle = "Readings per %.1f-%s band".format(Units.weight(h.binKg) ?: h.binKg, u),
            ) { WeightHistogramChart(h, accent) }
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun DeltaTile(d: WeightDelta?, label: String, modifier: Modifier) {
    NeonStatTile(
        value = signedWeight(d?.deltaKg) ?: "—", label = label, modifier = modifier,
        accent = d?.takeIf { it.deltaKg != null }?.let { toneColor(it.tone) },
    )
}

@Composable
private fun WeightTrendChart(data: WeightSeriesOut, color: Color, winStart: Long, winEnd: Long) {
    val measurer = rememberTextMeasurer()
    val pts = remember(data) {
        data.points.mapNotNull { p ->
            val kg = p.weightKg ?: return@mapNotNull null
            runCatching { Instant.parse(p.time).toEpochMilli() }.getOrNull()?.let { it to kg }
        }.sortedBy { it.first }
    }
    if (pts.size < 2) return
    val goal = Units.weight(data.stats?.goalKg)?.toFloat()
    val trend = data.stats?.trend
    Canvas(Modifier.fillMaxWidth().height(180.dp)) {
        val vals = pts.map { (Units.weight(it.second) ?: 0.0).toFloat() }
        // The goal is folded into the domain so its line is never silently
        // off-canvas — it would vanish exactly when furthest away.
        val domain = niceDomain(vals.min(), vals.max(), includeLo = goal, includeHi = goal,
            targetTicks = 4, minStep = 1f)
        val g = chartGeom(domain, ChartInsets(
            left = 34.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track) { "%.0f".format(it) }
        goal?.let { drawReferenceLine(g, it, NeonMV.Ink, measurer, "goal %.0f".format(it)) }
        // Server-fitted trend, positioned by its timestamps.
        trend?.let { t ->
            val s = runCatching { Instant.parse(t.startTime).toEpochMilli() }.getOrNull()
            val e = runCatching { Instant.parse(t.endTime).toEpochMilli() }.getOrNull()
            val sv = Units.weight(t.startKg)?.toFloat()
            val ev = Units.weight(t.endKg)?.toFloat()
            if (s != null && e != null && sv != null && ev != null) {
                drawLine(color.copy(alpha = 0.55f),
                    Offset(g.xAt(s, winStart, winEnd), g.y(sv)), Offset(g.xAt(e, winStart, winEnd), g.y(ev)),
                    strokeWidth = 1.2.dp.toPx(),
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(5.dp.toPx(), 4.dp.toPx())))
            }
        }
        val path = androidx.compose.ui.graphics.Path()
        val area = androidx.compose.ui.graphics.Path()
        val firstX = g.xAt(pts.first().first, winStart, winEnd)
        val lastX = g.xAt(pts.last().first, winStart, winEnd)
        for ((i, p) in pts.withIndex()) {
            val x = g.xAt(p.first, winStart, winEnd); val y = g.y(vals[i])
            if (i == 0) { path.moveTo(x, y); area.moveTo(x, g.bottom); area.lineTo(x, y) }
            else { path.lineTo(x, y); area.lineTo(x, y) }
            if (pts.size <= 31) drawCircle(color, radius = 2.4.dp.toPx(), center = Offset(x, y))
        }
        area.lineTo(lastX, g.bottom); area.close()
        drawPath(area, brush = androidx.compose.ui.graphics.Brush.verticalGradient(
            listOf(color.copy(alpha = 0.22f), color.copy(alpha = 0f)), startY = g.top, endY = g.bottom))
        drawPath(path, color, style = Stroke(width = 2.dp.toPx(),
            cap = androidx.compose.ui.graphics.StrokeCap.Round,
            join = androidx.compose.ui.graphics.StrokeJoin.Round))
        val minGap = GAP_MIN_FRACTION * (winEnd - winStart)
        if (pts.first().first - winStart > minGap) drawNoDataSpan(g.left, firstX, g.y(vals.first()), color)
        if (winEnd - pts.last().first > minGap) drawNoDataSpan(lastX, g.right, g.y(vals.last()), color)
        drawLatestMarker(Offset(lastX, g.y(vals.last())), color, NeonMV.CardHigh)
        drawXLabels(g, measurer, NeonMV.Muted, listOf(
            0f to mdOf(winStart), 0.5f to mdOf(winStart + (winEnd - winStart) / 2), 1f to mdOf(winEnd),
        ))
    }
}

/** UI-F1 — the server's kg bands as bars; edges converted for labels only. */
@Composable
private fun WeightHistogramChart(h: WeightHistogram, color: Color) {
    val measurer = rememberTextMeasurer()
    val bins = h.bins
    Canvas(Modifier.fillMaxWidth().height(130.dp)) {
        val domain = niceDomain(
            lo = 0f, hi = (bins.maxOfOrNull { it.count } ?: 1).toFloat().coerceAtLeast(1f),
            zeroAnchored = true, targetTicks = 3, minStep = 1f,
        )
        val g = chartGeom(domain, ChartInsets(
            left = 24.dp.toPx(), top = 6.dp.toPx(), right = 4.dp.toPx(), bottom = 16.dp.toPx(),
        ))
        drawGrid(g, measurer, NeonMV.Muted, NeonMV.Track, maxLabels = 3) { "%.0f".format(it) }
        val barW = g.slot(bins.size) * 0.8f
        bins.forEachIndexed { i, b ->
            if (b.count <= 0) return@forEachIndexed
            drawBar(g, g.xBar(i, bins.size), barW, g.y(b.count.toFloat()), color)
        }
        val lbl = { kg: Double -> Units.weight(kg)?.let { "%.1f".format(it) } ?: "" }
        drawXLabels(g, measurer, NeonMV.Muted, buildList {
            add(0f to lbl(bins.first().loKg))
            if (bins.size >= 5) add(0.5f to lbl(bins[bins.size / 2].loKg))
            add(1f to lbl(bins.last().hiKg))
        })
    }
}

private fun mdOf(ms: Long): String {
    val d = Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()).toLocalDate()
    return "${d.monthValue}/${d.dayOfMonth}"
}
