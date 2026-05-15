package app.myvitals.ui.vitals

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.TimePoint
import app.myvitals.ui.MV
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberBottom
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberStart
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoZoomState
import com.patrykandpatrick.vico.core.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.core.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.core.cartesian.data.CartesianChartModelProducer
import com.patrykandpatrick.vico.core.cartesian.data.lineSeries
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate
import java.time.format.DateTimeFormatter

enum class VitalRange(val label: String, val days: Int) {
    DAY("24h", 1), WEEK("7d", 7), MONTH("30d", 30), QUARTER("90d", 90),
}

@Composable
fun VitalsDetailScreen(
    settings: SettingsRepository,
    vital: Vital,
    onBack: () -> Unit,
) {
    when (vital) {
        Vital.SLEEP -> { SleepDetailScreen(settings, onBack); return }
        Vital.STEPS -> { StepsDetailScreen(settings, onBack); return }
        Vital.HR -> { HrDetailScreen(settings, onBack); return }
        Vital.WEIGHT -> { WeightDetailScreen(settings, onBack); return }
        Vital.BP -> { BpDetailScreen(settings, onBack); return }
        else -> {}
    }
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    var range by remember { mutableStateOf(VitalRange.MONTH) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    val producer = remember { CartesianChartModelProducer() }
    var stats by remember { mutableStateOf(Triple<Float?, Float?, Float?>(null, null, null)) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured."; loading = false; return
        }
        loading = true; error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val (xs, ys) = withContext(Dispatchers.IO) { fetchSeries(api, vital, range) }
            if (xs.isNotEmpty() && ys.isNotEmpty()) {
                producer.runTransaction { lineSeries { series(x = xs, y = ys) } }
                val realY = ys.filter { it.isFinite() }
                stats = Triple(
                    realY.minOrNull()?.toFloat(),
                    realY.maxOrNull()?.toFloat(),
                    if (realY.isEmpty()) null else realY.average().toFloat(),
                )
            } else {
                producer.runTransaction { lineSeries { series(x = listOf(0.0), y = listOf(0.0)) } }
                stats = Triple(null, null, null)
            }
        } catch (e: Exception) {
            Timber.w(e, "vitals detail fetch failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(range) { load() }

    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Icon(vital.icon, contentDescription = null,
                tint = vital.color, modifier = Modifier.width(20.dp).height(20.dp))
            Spacer(Modifier.width(8.dp))
            Text(vital.label, color = MV.OnSurface,
                fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f))
        }

        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            VitalRange.entries.forEach { r ->
                FilterChip(
                    selected = r == range,
                    onClick = { range = r },
                    label = { Text(r.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = vital.color.copy(alpha = 0.20f),
                        selectedLabelColor = MV.OnSurface,
                    ),
                )
            }
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
            modifier = Modifier.fillMaxWidth().padding(12.dp),
        ) {
            if (loading) {
                Text("Loading…", Modifier.padding(20.dp), color = MV.OnSurfaceVariant)
            } else if (error != null) {
                Text(error!!, Modifier.padding(20.dp), color = MV.Red)
            } else {
                Column(Modifier.padding(8.dp)) {
                    CartesianChartHost(
                        chart = rememberCartesianChart(
                            rememberLineCartesianLayer(),
                            startAxis = VerticalAxis.rememberStart(),
                            bottomAxis = HorizontalAxis.rememberBottom(),
                        ),
                        modelProducer = producer,
                        scrollState = rememberVicoScrollState(),
                        zoomState = rememberVicoZoomState(),
                        modifier = Modifier.fillMaxWidth().height(240.dp),
                    )

                    Spacer(Modifier.height(8.dp))
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 8.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Stat("Min", stats.first, vital)
                        Stat("Avg", stats.third, vital)
                        Stat("Max", stats.second, vital)
                    }
                }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: Float?, vital: Vital) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(
            value?.let { fmtForVital(it, vital) } ?: "—",
            color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
        )
    }
}

private fun fmtForVital(v: Float, vital: Vital): String = when (vital) {
    Vital.HR -> "%.0f bpm".format(v)
    Vital.HRV -> "%.0f ms".format(v)
    Vital.SLEEP -> "%.1f h".format(v)
    Vital.STEPS -> "%,.0f".format(v)
    Vital.WEIGHT -> "%.1f lb".format(v)
    Vital.BP -> "%.0f mmHg".format(v)
    Vital.SOBER -> "${v.toInt()}d"
    Vital.FASTING -> "%.1f h".format(v)
    Vital.WORKOUT, Vital.ACTIVITY, Vital.TRAILS, Vital.COACH,
    Vital.JOURNAL -> "${v.toInt()}"
}

private suspend fun fetchSeries(
    api: app.myvitals.sync.BackendApi, vital: Vital, range: VitalRange,
): Pair<List<Double>, List<Double>> {
    val isDayRange = range == VitalRange.DAY
    when (vital) {
        Vital.HR -> {
            if (isDayRange) {
                val s = api.heartRateSeries(
                    since = Instant.now().minusSeconds(86_400).toString(),
                )
                return tsXY(s.points)
            }
            val rows = dailyRows(api, range)
            return summaryXY(rows) { it.restingHr }
        }
        Vital.HRV -> {
            if (isDayRange) {
                val s = api.hrvSeries(since = Instant.now().minusSeconds(86_400).toString())
                return tsXY(s.points)
            }
            val rows = dailyRows(api, range)
            return summaryXY(rows) { it.hrvAvg }
        }
        Vital.STEPS -> {
            if (isDayRange) {
                val s = api.stepsSeries(since = Instant.now().minusSeconds(86_400).toString())
                return tsXY(s.points)
            }
            return summaryXY(dailyRows(api, range)) { it.stepsTotal?.toDouble() }
        }
        Vital.SLEEP -> {
            return summaryXY(dailyRows(api, range)) {
                it.sleepDurationS?.toDouble()?.div(3600.0)
            }
        }
        Vital.WEIGHT -> {
            return summaryXY(dailyRows(api, range)) { it.weightKg?.times(2.20462) }
        }
        Vital.BP -> {
            return summaryXY(dailyRows(api, range)) { it.bpSystolicAvg }
        }
        Vital.SOBER -> return Pair(emptyList(), emptyList())  // not chartable here
        Vital.FASTING -> {
            // Chart fasting_hours from the daily summary range. Day range
            // is meaningless for fasting (it's a per-day rollup).
            return summaryXY(dailyRows(api, range)) { it.fastingHours }
        }
        Vital.WORKOUT, Vital.ACTIVITY, Vital.TRAILS, Vital.COACH,
        Vital.JOURNAL ->
            return Pair(emptyList(), emptyList())  // navigate, no chart
    }
}

private suspend fun dailyRows(
    api: app.myvitals.sync.BackendApi, range: VitalRange,
): List<DailySummary> {
    val since = LocalDate.now().minusDays((range.days - 1).toLong()).toString()
    return api.summaryRange(since = since)
}

private fun tsXY(points: List<TimePoint>): Pair<List<Double>, List<Double>> {
    if (points.isEmpty()) return emptyList<Double>() to emptyList<Double>()
    val xs = points.map {
        runCatching { Instant.parse(it.time).toEpochMilli() / 60_000.0 }.getOrDefault(0.0)
    }
    val origin = xs.min()
    return xs.map { it - origin } to points.map { it.value }
}

private fun summaryXY(
    rows: List<DailySummary>, sel: (DailySummary) -> Double?,
): Pair<List<Double>, List<Double>> {
    val pairs = rows.mapNotNull { row ->
        val v = sel(row) ?: return@mapNotNull null
        val day = runCatching {
            LocalDate.parse(row.date, DateTimeFormatter.ISO_LOCAL_DATE).toEpochDay()
        }.getOrNull() ?: return@mapNotNull null
        day.toDouble() to v
    }
    if (pairs.isEmpty()) return emptyList<Double>() to emptyList<Double>()
    val originDay = pairs.first().first
    return pairs.map { it.first - originDay } to pairs.map { it.second }
}
