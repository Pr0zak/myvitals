package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.MonitorWeight
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Speed
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.TimePoint
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import timber.log.Timber
import java.time.Instant
import java.time.LocalDate

enum class Vital(val label: String, val icon: ImageVector, val color: Color) {
    HR("Heart rate", Icons.Outlined.FavoriteBorder, Color(0xFFEF4444)),
    HRV("HRV", Icons.Outlined.Speed, Color(0xFFA855F7)),
    SLEEP("Sleep", Icons.Outlined.Bedtime, Color(0xFF60A5FA)),
    STEPS("Steps", Icons.AutoMirrored.Outlined.DirectionsRun, Color(0xFF22C55E)),
    WEIGHT("Weight", Icons.Outlined.MonitorWeight, Color(0xFFF59E0B)),
    BP("Blood pressure", Icons.Outlined.FavoriteBorder, Color(0xFFEC4899)),
    SOBER("Sober", Icons.Outlined.Timer, Color(0xFF84CC16)),
}

/** Lightweight wrapper for the live HR points + their freshness. */
data class HrSnapshot(val points: List<TimePoint>, val latest: Double?, val lastIso: String?)
data class WeightSnapshot(val points: List<Pair<Long, Double>>, val latestKg: Double?, val lastIso: String?)
data class BpSnapshot(val latestSys: Int?, val latestDia: Int?, val lastIso: String?)

@Composable
fun VitalsScreen(
    settings: SettingsRepository,
    onOpenSettings: () -> Unit,
    onOpenSober: () -> Unit,
    onOpenVitalDetail: (Vital) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var today by remember { mutableStateOf<DailySummary?>(null) }
    var hr by remember { mutableStateOf(HrSnapshot(emptyList(), null, null)) }
    var weight by remember { mutableStateOf(WeightSnapshot(emptyList(), null, null)) }
    var bp by remember { mutableStateOf(BpSnapshot(null, null, null)) }
    var sober by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."; loading = false; return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since30 = LocalDate.now().minusDays(29).toString()
            val hrSince = Instant.now().minusSeconds(8 * 3600).toString()
            val weightSince = LocalDate.now().minusDays(60).toString()
            val bpSince = LocalDate.now().minusDays(30).toString()
            coroutineScope {
                val rowsD = async(Dispatchers.IO) { api.summaryRange(since = since30) }
                val todayD = async(Dispatchers.IO) {
                    runCatching { api.summaryToday() }.getOrNull()
                }
                val hrD = async(Dispatchers.IO) {
                    runCatching {
                        val s = api.heartRateSeries(since = hrSince)
                        HrSnapshot(
                            points = s.points,
                            latest = s.points.lastOrNull()?.value,
                            lastIso = s.points.lastOrNull()?.time,
                        )
                    }.getOrDefault(HrSnapshot(emptyList(), null, null))
                }
                val weightD = async(Dispatchers.IO) {
                    runCatching {
                        val raw = api.weightSeries(since = weightSince).string()
                        val obj = JSONObject(raw)
                        val arr = obj.optJSONArray("points") ?: org.json.JSONArray()
                        val pts = mutableListOf<Pair<Long, Double>>()
                        var lastIso: String? = null
                        for (i in 0 until arr.length()) {
                            val p = arr.getJSONObject(i)
                            val w = p.optDouble("weight_kg", Double.NaN)
                            val t: String? = p.optString("time").takeIf { it.isNotBlank() }
                            if (!w.isNaN() && t != null) {
                                pts += runCatching {
                                    Instant.parse(t).toEpochMilli() to w
                                }.getOrNull() ?: continue
                                lastIso = t
                            }
                        }
                        WeightSnapshot(
                            points = pts,
                            latestKg = obj.optDouble("latest_kg").takeIf { !it.isNaN() },
                            lastIso = lastIso,
                        )
                    }.getOrDefault(WeightSnapshot(emptyList(), null, null))
                }
                val bpD = async(Dispatchers.IO) {
                    runCatching {
                        val raw = api.bpSeries(since = bpSince).string()
                        val obj = JSONObject(raw)
                        val latest = obj.optJSONObject("latest")
                        if (latest != null) {
                            BpSnapshot(
                                latestSys = latest.optInt("systolic"),
                                latestDia = latest.optInt("diastolic"),
                                lastIso = latest.optString("time").takeIf { it.isNotBlank() },
                            )
                        } else BpSnapshot(null, null, null)
                    }.getOrDefault(BpSnapshot(null, null, null))
                }
                val soberD = async(Dispatchers.IO) {
                    runCatching { api.soberCurrent() }.getOrNull()
                }
                val profileD = async(Dispatchers.IO) {
                    runCatching { api.profile() }.getOrNull()
                }

                rows = rowsD.await()
                today = todayD.await()
                hr = hrD.await()
                weight = weightD.await()
                bp = bpD.await()
                sober = soberD.await()
                profile = profileD.await()
            }
            error = null
            Timber.i(
                "vitals: %d daily rows, hr=%d pts, weight=%d pts, bp=%s, today=%s",
                rows.size, hr.points.size, weight.points.size,
                if (bp.latestSys != null) "y" else "n",
                today?.date,
            )
        } catch (e: Exception) {
            Timber.w(e, "vitals load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) {
        while (true) { delay(1_000); nowMs = System.currentTimeMillis() }
    }

    val tiles = remember {
        listOf(Vital.HR, Vital.SLEEP, Vital.STEPS, Vital.HRV, Vital.WEIGHT, Vital.BP, Vital.SOBER)
    }

    Column(Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 12.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text("VITALS",
                    color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                Text(
                    rows.lastOrNull()?.date ?: "—",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            IconButton(onClick = { scope.launch { loading = true; load() } }, enabled = !loading) {
                Icon(Icons.Outlined.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
            }
        }

        if (error != null) {
            Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
            ) {
                Row(Modifier.padding(12.dp)) {
                    Text(error!!, modifier = Modifier.weight(1f),
                        color = MV.Red, fontSize = 12.sp)
                    TextButton(onClick = onOpenSettings) {
                        Text("Settings", color = MV.OnSurface, fontSize = 12.sp)
                    }
                }
            }
        }

        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 6.dp, horizontal = 0.dp),
        ) {
            items(tiles, key = { it.name }) { v ->
                when (v) {
                    Vital.SOBER -> SoberBadge(sober, onClick = onOpenSober)
                    Vital.HR -> HrBadge(hr, today, rows, nowMs,
                        onClick = { onOpenVitalDetail(v) })
                    Vital.HRV -> HrvBadge(rows, nowMs, onClick = { onOpenVitalDetail(v) })
                    Vital.SLEEP -> SleepBadge(rows, nowMs, onClick = { onOpenVitalDetail(v) })
                    Vital.STEPS -> StepsBadge(
                        todayCount = today?.stepsTotal ?: rows.lastOrNull()?.stepsTotal,
                        goal = profile?.stepsGoal() ?: 10_000,
                        lastDate = today?.date ?: rows.lastOrNull()?.date,
                        nowMs = nowMs,
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.WEIGHT -> WeightBadge(weight, nowMs,
                        onClick = { onOpenVitalDetail(v) })
                    Vital.BP -> BpBadge(bp, nowMs, onClick = { onOpenVitalDetail(v) })
                }
            }
        }
    }
}

// ============================================================
// Badges
// ============================================================

@Composable
private fun BadgeFrame(v: Vital, lastUpdate: String?, onClick: () -> Unit, content: @Composable () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(v.icon, contentDescription = v.label,
                    tint = v.color, modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(6.dp))
                Text(v.label, color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
                    modifier = Modifier.weight(1f))
                if (lastUpdate != null) {
                    Text(lastUpdate, color = MV.OnSurfaceDim, fontSize = 9.sp)
                }
            }
            Spacer(Modifier.height(8.dp))
            content()
        }
    }
}

@Composable
private fun HrBadge(
    snap: HrSnapshot,
    today: DailySummary?,
    rows: List<DailySummary>,
    nowMs: Long,
    onClick: () -> Unit,
) {
    val v = Vital.HR
    // Prefer the latest live sample; fall back to today's resting HR.
    val (value, label, lastUpdate) = when {
        snap.latest != null && snap.lastIso != null ->
            Triple("%.0f".format(snap.latest), "live", fmtRelative(snap.lastIso, nowMs))
        today?.restingHr != null ->
            Triple("%.0f".format(today.restingHr), "resting", "today")
        rows.lastOrNull { it.restingHr != null } != null -> {
            val r = rows.last { it.restingHr != null }
            Triple("%.0f".format(r.restingHr), "resting", fmtRelativeDate(r.date, nowMs))
        }
        else -> Triple<String?, String?, String?>(null, null, null)
    }
    BadgeFrame(v, lastUpdate, onClick) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(value ?: "—", color = MV.OnSurface,
                fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("bpm", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
            if (label != null) {
                Spacer(Modifier.width(6.dp))
                Text(label, color = MV.OnSurfaceDim, fontSize = 9.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 6.dp))
            }
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth().height(34.dp)) {
            if (snap.points.size >= 2) {
                HrSparkline(snap.points, color = v.color, nowMs = nowMs)
            } else {
                // No live samples — show resting trend from daily summaries.
                SparkLine(rows.map { it.restingHr?.toFloat() }, color = v.color)
            }
        }
    }
}

@Composable
private fun HrvBadge(rows: List<DailySummary>, nowMs: Long, onClick: () -> Unit) {
    val v = Vital.HRV
    val lastRow = rows.lastOrNull { it.hrvAvg != null }
    val series = rows.map { it.hrvAvg?.toFloat() }
    BadgeFrame(v, lastRow?.date?.let { fmtRelativeDate(it, nowMs) }, onClick) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(lastRow?.hrvAvg?.let { "%.0f".format(it) } ?: "—",
                color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("ms", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth().height(34.dp)) {
            SparkLine(series, color = v.color)
        }
    }
}

@Composable
private fun SleepBadge(rows: List<DailySummary>, nowMs: Long, onClick: () -> Unit) {
    val v = Vital.SLEEP
    val last7 = rows.takeLast(7)
    val lastRow = last7.lastOrNull { it.sleepDurationS != null }
    val hours = lastRow?.sleepDurationS?.toDouble()?.div(3600.0)
    BadgeFrame(v, lastRow?.date?.let { fmtRelativeDate(it, nowMs) }, onClick) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(hours?.let { "%.1f".format(it) } ?: "—",
                color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("h", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth().height(34.dp)) {
            SleepBars(last7.map { it.sleepDurationS?.toFloat()?.div(3600f) }, color = v.color)
        }
    }
}

@Composable
private fun StepsBadge(
    todayCount: Int?, goal: Int, lastDate: String?, nowMs: Long, onClick: () -> Unit,
) {
    val v = Vital.STEPS
    BadgeFrame(v, lastDate?.let { fmtRelativeDate(it, nowMs) }, onClick) {
        Box(Modifier.fillMaxWidth().aspectRatio(1.6f),
            contentAlignment = Alignment.Center) {
            StepsRing(
                count = todayCount ?: 0,
                goal = goal,
                color = v.color,
                modifier = Modifier.fillMaxSize(),
            )
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    todayCount?.let { "%,d".format(it) } ?: "—",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
                Text("/ ${"%,d".format(goal)}",
                    color = MV.OnSurfaceDim, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun WeightBadge(snap: WeightSnapshot, nowMs: Long, onClick: () -> Unit) {
    val v = Vital.WEIGHT
    val lbs = snap.latestKg?.times(2.20462)
    // Trend = current vs ~30d-ago value (average of oldest 3 points)
    val trend: Double? = remember(snap.points) {
        if (snap.points.size < 4) null else {
            val cur = snap.points.last().second
            val baseline = snap.points.take(3).map { it.second }.average()
            (cur - baseline) * 2.20462
        }
    }
    BadgeFrame(v, snap.lastIso?.let { fmtRelative(it, nowMs) }, onClick) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(lbs?.let { "%.1f".format(it) } ?: "—",
                color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("lb", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        if (trend != null) {
            val arrow = if (trend > 0.05) "↑" else if (trend < -0.05) "↓" else "→"
            val trendColor = when {
                trend > 0.5 -> Color(0xFFFBBF24)
                trend < -0.5 -> Color(0xFF60A5FA)
                else -> MV.OnSurfaceDim
            }
            Text("$arrow %+.1f lb (30d)".format(trend),
                color = trendColor, fontSize = 11.sp, fontWeight = FontWeight.Medium)
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth().height(34.dp)) {
            SparkLine(snap.points.map { (it.second * 2.20462).toFloat() }, color = v.color)
        }
    }
}

@Composable
private fun BpBadge(bp: BpSnapshot, nowMs: Long, onClick: () -> Unit) {
    val v = Vital.BP
    BadgeFrame(v, bp.lastIso?.let { fmtRelative(it, nowMs) }, onClick) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                if (bp.latestSys != null && bp.latestDia != null)
                    "${bp.latestSys}/${bp.latestDia}"
                else "—",
                color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.width(4.dp))
            Text("mmHg", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        Spacer(Modifier.height(6.dp))
        // Category bar — map systolic into normal/elevated/high regions.
        val catColor = when {
            bp.latestSys == null -> MV.OnSurfaceDim
            bp.latestSys < 120 -> Color(0xFF22C55E)   // normal
            bp.latestSys < 130 -> Color(0xFFFBBF24)   // elevated
            bp.latestSys < 140 -> Color(0xFFF97316)   // stage-1
            else -> Color(0xFFEF4444)                 // stage-2+
        }
        Text(when {
            bp.latestSys == null -> "no readings"
            bp.latestSys < 120 -> "Normal"
            bp.latestSys < 130 -> "Elevated"
            bp.latestSys < 140 -> "Stage 1"
            else -> "Stage 2"
        }, color = catColor, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun SoberBadge(sober: SoberCurrentResponse?, onClick: () -> Unit) {
    val v = Vital.SOBER
    BadgeFrame(v, null, onClick) {
        val days = sober?.days
        val hours = sober?.hours
        if (days != null) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text("$days", color = MV.OnSurface,
                    fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(4.dp))
                Text(if (days == 1) "day" else "days",
                    color = MV.OnSurfaceDim, fontSize = 11.sp,
                    modifier = Modifier.padding(bottom = 4.dp))
                if (hours != null) {
                    Spacer(Modifier.width(8.dp))
                    Text("${hours}h", color = MV.OnSurfaceVariant, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 4.dp))
                }
            }
        } else {
            Text("—", color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.height(6.dp))
        Text("Tap to manage", color = MV.OnSurfaceDim, fontSize = 10.sp)
    }
}

// ============================================================
// Visualisations
// ============================================================

@Composable
private fun HrSparkline(
    points: List<TimePoint>,
    color: Color,
    nowMs: Long,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    Canvas(modifier = modifier) {
        if (points.size < 2) return@Canvas
        // Compute time domain — current end is "now"; span back 2h.
        val end = nowMs
        val start = end - 2 * 3600_000L
        // Walk points and group into segments where consecutive samples
        // are within 5 min of each other; otherwise leave a gap.
        val segments = mutableListOf<MutableList<Pair<Long, Float>>>()
        var current = mutableListOf<Pair<Long, Float>>()
        var prevT: Long? = null
        for (p in points) {
            val t = runCatching { Instant.parse(p.time).toEpochMilli() }.getOrNull() ?: continue
            if (t < start || t > end + 60_000) continue
            if (prevT != null && (t - prevT) > 5 * 60_000) {
                if (current.size >= 2) segments += current
                current = mutableListOf()
            }
            current += t to p.value.toFloat()
            prevT = t
        }
        if (current.size >= 2) segments += current
        if (segments.isEmpty()) return@Canvas

        val allY = segments.flatten().map { it.second }
        val minY = allY.min()
        val maxY = allY.max()
        val span = (maxY - minY).coerceAtLeast(1f)
        val padY = size.height * 0.12f
        val plotH = size.height - 2 * padY

        for (seg in segments) {
            val path = androidx.compose.ui.graphics.Path()
            seg.forEachIndexed { idx, (t, y) ->
                val x = ((t - start).toFloat() / (end - start).toFloat()) * size.width
                val py = size.height - padY - ((y - minY) / span) * plotH
                if (idx == 0) path.moveTo(x, py) else path.lineTo(x, py)
            }
            drawPath(path, color = color, style = Stroke(width = 1.5.dp.toPx()))
        }
        // Latest sample dot
        val (lt, ly) = segments.last().last()
        val lx = ((lt - start).toFloat() / (end - start).toFloat()) * size.width
        val ply = size.height - padY - ((ly - minY) / span) * plotH
        drawCircle(color = color, radius = 2.5.dp.toPx(),
            center = Offset(lx, ply))
    }
}

@Composable
private fun SleepBars(
    nights: List<Float?>,
    color: Color,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    Canvas(modifier = modifier) {
        if (nights.isEmpty()) return@Canvas
        val maxV = (nights.filterNotNull().maxOrNull() ?: 8f).coerceAtLeast(8f)
        val gapPx = 2.dp.toPx()
        val barW = (size.width - gapPx * (nights.size - 1)) / nights.size
        val target = 8f
        for ((i, v) in nights.withIndex()) {
            val x = i * (barW + gapPx)
            val h = (v ?: 0f) / maxV * size.height
            val barColor = when {
                v == null -> color.copy(alpha = 0.2f)
                v >= target -> color
                v >= target * 0.85f -> color.copy(alpha = 0.75f)
                else -> color.copy(alpha = 0.45f)
            }
            drawRect(
                color = barColor,
                topLeft = Offset(x, size.height - h),
                size = androidx.compose.ui.geometry.Size(barW, h),
            )
        }
    }
}

@Composable
private fun StepsRing(
    count: Int, goal: Int, color: Color,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier) {
        val stroke = 6.dp.toPx()
        val pad = stroke / 2 + 4.dp.toPx()
        val rect = androidx.compose.ui.geometry.Rect(
            left = pad, top = pad,
            right = size.width - pad, bottom = size.height - pad,
        )
        val side = minOf(rect.width, rect.height)
        val cx = rect.center.x
        val cy = rect.center.y
        val sq = androidx.compose.ui.geometry.Rect(
            left = cx - side / 2, top = cy - side / 2,
            right = cx + side / 2, bottom = cy + side / 2,
        )
        // Background ring
        drawArc(
            color = color.copy(alpha = 0.18f),
            startAngle = -90f, sweepAngle = 360f, useCenter = false,
            topLeft = sq.topLeft, size = androidx.compose.ui.geometry.Size(sq.width, sq.height),
            style = Stroke(width = stroke),
        )
        val pct = (count.toFloat() / goal.toFloat()).coerceAtLeast(0f)
        val sweep = (pct * 360f).coerceAtMost(360f)
        drawArc(
            color = color,
            startAngle = -90f, sweepAngle = sweep, useCenter = false,
            topLeft = sq.topLeft, size = androidx.compose.ui.geometry.Size(sq.width, sq.height),
            style = Stroke(width = stroke, cap = androidx.compose.ui.graphics.StrokeCap.Round),
        )
    }
}

// ============================================================
// Time helpers
// ============================================================

private fun fmtRelative(iso: String, nowMs: Long): String {
    return try {
        val ms = nowMs - Instant.parse(iso).toEpochMilli()
        val s = ms / 1000
        when {
            s < 60 -> "now"
            s < 3600 -> "${s / 60}m"
            s < 86400 -> "${s / 3600}h"
            else -> "${s / 86400}d"
        }
    } catch (_: Exception) { "" }
}

private fun fmtRelativeDate(date: String, nowMs: Long): String {
    return try {
        val d = LocalDate.parse(date)
        val today = LocalDate.now()
        val days = today.toEpochDay() - d.toEpochDay()
        when {
            days <= 0L -> "today"
            days == 1L -> "1d"
            else -> "${days}d"
        }
    } catch (_: Exception) { "" }
}
