package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.Terrain
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.MonitorWeight
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Speed
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material.icons.outlined.ArrowDropDown
import androidx.compose.material.icons.outlined.ArrowDropUp
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
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
import androidx.compose.ui.draw.clip
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
    WORKOUT("Workout", Icons.Outlined.FitnessCenter, Color(0xFFEF4444)),
    ACTIVITY("Last activity", Icons.AutoMirrored.Outlined.DirectionsBike,
        Color(0xFF38BDF8)),
    TRAILS("Trails", Icons.Outlined.Terrain, Color(0xFF22C55E)),
}

/** Lightweight wrapper for the live HR points + their freshness. */
data class HrSnapshot(val points: List<TimePoint>, val latest: Double?, val lastIso: String?)
data class WeightSnapshot(val points: List<Pair<Long, Double>>, val latestKg: Double?, val lastIso: String?)
data class BpSnapshot(val latestSys: Int?, val latestDia: Int?, val lastIso: String?)

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun VitalsScreen(
    settings: SettingsRepository,
    onOpenSettings: () -> Unit,
    onOpenSober: () -> Unit,
    onOpenVitalDetail: (Vital) -> Unit,
    onOpenWorkout: () -> Unit = {},
    onOpenActivity: (source: String, sourceId: String) -> Unit = { _, _ -> },
    onOpenTrails: () -> Unit = {},
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var today by remember { mutableStateOf<DailySummary?>(null) }
    var hr by remember { mutableStateOf(HrSnapshot(emptyList(), null, null)) }
    var weight by remember { mutableStateOf(WeightSnapshot(emptyList(), null, null)) }
    var bp by remember { mutableStateOf(BpSnapshot(null, null, null)) }
    var sober by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    var lastActivity by remember { mutableStateOf<app.myvitals.sync.ActivityRow?>(null) }
    var trailCounts by remember { mutableStateOf(Triple(0, 0, 0)) }  // open/delayed/closed
    var lastWorkout by remember {
        mutableStateOf<app.myvitals.sync.StrengthWorkoutSummary?>(null)
    }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    val context = LocalContext.current

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."; loading = false; return
        }
        // Stale-while-revalidate: render cached state immediately so the
        // grid doesn't flash "Loading…" between launches. Fresh fetch runs
        // below and overwrites on success.
        val cachedToday = app.myvitals.data.JsonCache.read<DailySummary>(
            context, "vitals_today",
            app.myvitals.sync.DailySummary::class.java,
        )
        if (cachedToday != null) {
            today = cachedToday.value
            loading = false
            refreshing = true
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
                val activityD = async(Dispatchers.IO) {
                    runCatching {
                        api.activities(limit = 1).firstOrNull()
                    }.getOrNull()
                }
                val trailsD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.trails().trails
                        Triple(
                            r.count { it.status == "open" },
                            r.count { it.status == "delayed" },
                            r.count { it.status == "closed" },
                        )
                    }.getOrDefault(Triple(0, 0, 0))
                }
                val workoutD = async(Dispatchers.IO) {
                    runCatching {
                        api.strengthWorkouts().workouts.firstOrNull()
                    }.getOrNull()
                }

                rows = rowsD.await()
                today = todayD.await()
                hr = hrD.await()
                weight = weightD.await()
                bp = bpD.await()
                sober = soberD.await()
                profile = profileD.await()
                lastActivity = activityD.await()
                trailCounts = trailsD.await()
                lastWorkout = workoutD.await()

                today?.let {
                    app.myvitals.data.JsonCache.write(
                        context, "vitals_today",
                        app.myvitals.sync.DailySummary::class.java, it,
                    )
                }
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
        } finally { loading = false; refreshing = false }
    }

    LaunchedEffect(Unit) { load() }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }
    LaunchedEffect(Unit) {
        while (true) { delay(1_000); nowMs = System.currentTimeMillis() }
    }

    // Default order — overridden by profile.extra.vitals_order if set.
    val canonicalOrder = remember {
        listOf(
            Vital.HR, Vital.SLEEP, Vital.STEPS, Vital.HRV,
            Vital.WORKOUT, Vital.ACTIVITY, Vital.TRAILS,
            Vital.WEIGHT, Vital.BP, Vital.SOBER,
        )
    }
    val tiles = remember(profile) {
        val savedOrder = profile?.extra?.vitalsOrder ?: emptyList()
        val hidden = profile?.extra?.vitalsHidden?.toSet() ?: emptySet()
        val sortedByPref: List<Vital> = if (savedOrder.isNotEmpty()) {
            // Saved order wins; tile names not in saved-order tail-append.
            val byName = canonicalOrder.associateBy { it.name }
            (savedOrder.mapNotNull { byName[it] } +
                canonicalOrder.filter { it.name !in savedOrder })
        } else canonicalOrder
        sortedByPref.filter { it.name !in hidden }
    }
    var manageOpen by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 12.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("VITALS",
                        color = MV.OnSurfaceVariant,
                        fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                    if (refreshing) {
                        Spacer(Modifier.width(8.dp))
                        Text("refreshing…",
                            color = MV.OnSurfaceVariant, fontSize = 10.sp,
                            fontWeight = FontWeight.Normal)
                    }
                }
                Text(
                    rows.lastOrNull()?.date ?: "—",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            Row {
                IconButton(onClick = { manageOpen = true }) {
                    Icon(Icons.Outlined.Tune, contentDescription = "Manage badges",
                        tint = MV.OnSurface)
                }
                IconButton(onClick = { scope.launch { loading = true; load() } }, enabled = !loading) {
                    Icon(Icons.Outlined.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
                }
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

        // Manage-badges modal sheet
        if (manageOpen) {
            ManageBadgesSheet(
                canonical = canonicalOrder,
                profile = profile,
                onDismiss = { manageOpen = false },
                onSave = { orderedNames, hiddenSet ->
                    scope.launch {
                        try {
                            val api = BackendClient.create(
                                settings.backendUrl, settings.bearerToken,
                            )
                            val newExtra = mutableMapOf<String, Any>()
                            // Preserve any unrelated extra fields the user might have set.
                            profile?.extra?.let { ex ->
                                ex.stepsGoal?.let { newExtra["steps_goal"] = it }
                                ex.sleepGoalH?.let { newExtra["sleep_goal_h"] = it }
                            }
                            newExtra["vitals_order"] = orderedNames
                            newExtra["vitals_hidden"] = hiddenSet.toList()
                            withContext(Dispatchers.IO) {
                                api.putProfile(
                                    app.myvitals.sync.ProfilePutBody(
                                        birthDate = profile?.birthDate,
                                        sex = profile?.sex,
                                        heightCm = profile?.heightCm,
                                        weightGoalKg = profile?.weightGoalKg,
                                        restingHrBaseline = profile?.restingHrBaseline,
                                        activityLevel = profile?.activityLevel,
                                        extra = newExtra,
                                    ),
                                )
                            }
                            manageOpen = false
                            Timber.i("badges saved: order=%s hidden=%s",
                                orderedNames, hiddenSet)
                            load()
                        } catch (e: Exception) {
                            Timber.w(e, "save vitals layout failed")
                            error = "Save failed: ${e.message?.take(80)}"
                        }
                    }
                },
            )
        }

        androidx.compose.material3.pulltorefresh.PullToRefreshBox(
            isRefreshing = loading,
            onRefresh = { scope.launch { loading = true; load() } },
            modifier = Modifier.weight(1f),
        ) {
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
                    Vital.SLEEP -> SleepBadge(today, rows, nowMs, onClick = { onOpenVitalDetail(v) })
                    Vital.STEPS -> StepsBadge(
                        todayCount = today?.stepsTotal ?: rows.lastOrNull()?.stepsTotal,
                        goal = profile?.stepsGoal() ?: 10_000,
                        lastDate = today?.date ?: rows.lastOrNull()?.date,
                        nowMs = nowMs,
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.WORKOUT -> WorkoutBadge(lastWorkout, nowMs, onClick = onOpenWorkout)
                    Vital.ACTIVITY -> ActivityBadge(
                        lastActivity, nowMs,
                        onClick = {
                            lastActivity?.let { onOpenActivity(it.source, it.sourceId) }
                        },
                    )
                    Vital.TRAILS -> TrailsBadge(
                        open = trailCounts.first,
                        delayed = trailCounts.second,
                        closed = trailCounts.third,
                        onClick = onOpenTrails,
                    )
                    Vital.WEIGHT -> WeightBadge(weight, nowMs,
                        onClick = { onOpenVitalDetail(v) })
                    Vital.BP -> BpBadge(bp, nowMs, onClick = { onOpenVitalDetail(v) })
                }
            }
        }
        }  // end PullToRefreshBox
    }
}

// ============================================================
// Badges
// ============================================================

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun BadgeFrame(
    v: Vital, lastUpdate: String?,
    onClick: () -> Unit,
    onLongPress: (() -> Unit)? = null,
    pulseBpm: Double? = null,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    // When pulseBpm is set, the eyebrow icon scales rhythmically at
    // the user's actual heart rate (60_000 / BPM ms per cycle). HR
    // badge uses this for live samples; everything else stays static.
    val pulseScale = if (pulseBpm != null && pulseBpm > 0) {
        val durationMs = (60_000.0 / pulseBpm).coerceIn(400.0, 2_000.0).toInt()
        val transition = androidx.compose.animation.core.rememberInfiniteTransition(label = "hr-pulse")
        transition.animateFloat(
            initialValue = 1.0f, targetValue = 1.25f,
            animationSpec = androidx.compose.animation.core.infiniteRepeatable(
                animation = androidx.compose.animation.core.tween(
                    durationMillis = durationMs / 2,
                    easing = androidx.compose.animation.core.EaseInOut,
                ),
                repeatMode = androidx.compose.animation.core.RepeatMode.Reverse,
            ),
            label = "hr-pulse-scale",
        ).value
    } else 1.0f

    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().height(150.dp)
            .combinedClickable(
                onClick = { onClick() },
                onLongClick = { onLongPress?.invoke() },
            ),
    ) {
        Column(Modifier.padding(12.dp).fillMaxSize()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    v.icon, contentDescription = v.label, tint = v.color,
                    modifier = Modifier.size(14.dp).then(
                        if (pulseScale != 1.0f)
                            Modifier.graphicsLayer(scaleX = pulseScale, scaleY = pulseScale)
                        else Modifier,
                    ),
                )
                Spacer(Modifier.width(6.dp))
                Text(v.label, color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
                    modifier = Modifier.weight(1f), maxLines = 1)
                if (lastUpdate != null) {
                    Text(lastUpdate, color = MV.OnSurfaceDim, fontSize = 9.sp)
                }
            }
            Spacer(Modifier.height(6.dp))
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
    val livePulseBpm = if (label == "live" && snap.latest != null) snap.latest else null
    BadgeFrame(v, lastUpdate, onClick, pulseBpm = livePulseBpm) {
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
private fun HrMiniHistogram(points: List<TimePoint>, color: Color) {
    // 5-bpm bins computed from the available samples (whatever window
    // the caller pulled — typically the last 8h on the Vitals tab).
    Canvas(Modifier.fillMaxSize()) {
        if (points.isEmpty()) return@Canvas
        val bin = 5
        val byBin = HashMap<Int, Int>()
        var lo = Int.MAX_VALUE; var hi = Int.MIN_VALUE
        for (p in points) {
            val b = (p.value / bin).toInt() * bin
            byBin[b] = (byBin[b] ?: 0) + 1
            if (b < lo) lo = b
            if (b > hi) hi = b
        }
        if (lo == Int.MAX_VALUE) return@Canvas
        val bins = (lo..hi step bin).toList()
        if (bins.isEmpty()) return@Canvas
        val maxCount = (byBin.values.maxOrNull() ?: 1).coerceAtLeast(1)
        val gap = 1.5f
        val barW = (size.width - gap * (bins.size - 1)) / bins.size
        bins.forEachIndexed { i, b ->
            val c = byBin[b] ?: 0
            val h = (c.toFloat() / maxCount) * size.height
            val x = i * (barW + gap)
            drawRect(
                color = color,
                topLeft = androidx.compose.ui.geometry.Offset(x, size.height - h),
                size = androidx.compose.ui.geometry.Size(barW, h),
            )
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
private fun SleepBadge(
    today: DailySummary?, rows: List<DailySummary>, nowMs: Long,
    onClick: () -> Unit,
) {
    val v = Vital.SLEEP
    val last7 = rows.takeLast(7)
    // Prefer today's live /summary/today value over the persisted daily-
    // summary row — the daily_summary cron runs at 03:00 local, before
    // the user has typically finished sleeping, so the persisted row
    // for today lags until the next cron pass. The live endpoint
    // re-computes from sleep_stages on every request.
    val headline = today?.takeIf { it.sleepDurationS != null }
        ?: last7.lastOrNull { it.sleepDurationS != null }
    val hours = headline?.sleepDurationS?.toDouble()?.div(3600.0)
    // Build the 7-bar history with today's value swapped in if the
    // last row is missing or stale.
    val barRows = last7.map { row ->
        if (today != null && row.date == today.date && today.sleepDurationS != null) today
        else row
    }
    BadgeFrame(v, headline?.date?.let { fmtRelativeDate(it, nowMs) }, onClick) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(hours?.let { "%.1f".format(it) } ?: "—",
                color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("h", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth().height(34.dp)) {
            SleepBars(barRows.map { it.sleepDurationS?.toFloat()?.div(3600f) }, color = v.color)
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

@Composable
private fun WorkoutBadge(
    last: app.myvitals.sync.StrengthWorkoutSummary?,
    nowMs: Long,
    onClick: () -> Unit,
) {
    val v = Vital.WORKOUT
    val freshness = last?.startedAt?.let { fmtRelative(it, nowMs) }
        ?: last?.date?.let { fmtRelativeDate(it, nowMs) }
    BadgeFrame(v, freshness, onClick) {
        if (last == null) {
            Text("—", color = MV.OnSurface, fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text("No workouts yet", color = MV.OnSurfaceDim, fontSize = 11.sp)
            return@BadgeFrame
        }
        Text(
            last.splitFocus.replaceFirstChar { it.titlecase() },
            color = MV.OnSurface, fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold, maxLines = 1,
        )
        Spacer(Modifier.height(2.dp))
        Text(
            last.date, color = MV.OnSurfaceVariant, fontSize = 12.sp,
        )
        Spacer(Modifier.weight(1f))
        Text(
            when (last.status) {
                "completed" -> "Complete"
                "in_progress" -> "In progress"
                "skipped" -> "Skipped"
                else -> last.status ?: ""
            },
            color = when (last.status) {
                "completed" -> Color(0xFF22C55E)
                "in_progress" -> Color(0xFFFBBF24)
                "skipped" -> MV.OnSurfaceDim
                else -> MV.OnSurfaceVariant
            },
            fontSize = 10.sp, fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun ActivityBadge(
    last: app.myvitals.sync.ActivityRow?,
    nowMs: Long,
    onClick: () -> Unit,
) {
    val v = Vital.ACTIVITY
    val freshness = last?.startAt?.let { fmtRelative(it, nowMs) }
    BadgeFrame(v, freshness, onClick) {
        if (last == null) {
            Text("—", color = MV.OnSurface, fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text("No activities", color = MV.OnSurfaceDim, fontSize = 11.sp)
            return@BadgeFrame
        }
        val miles = last.distanceM?.let { it / 1609.34 } ?: 0.0
        Row(verticalAlignment = Alignment.Bottom) {
            Text("%.1f".format(miles),
                color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("mi", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        Spacer(Modifier.height(2.dp))
        Text(
            last.type.replace("Ride", " ride", ignoreCase = true).trim(),
            color = MV.OnSurfaceVariant, fontSize = 11.sp, maxLines = 1,
        )
        if (!last.trailName.isNullOrBlank()) {
            Text("@ ${last.trailName}", color = MV.OnSurfaceDim,
                fontSize = 10.sp, maxLines = 1)
        }
        Spacer(Modifier.weight(1f))
        val mins = last.durationS / 60
        Text(
            "${mins} min · ${last.avgHr?.let { "%.0f bpm".format(it) } ?: "—"}",
            color = MV.OnSurfaceDim, fontSize = 10.sp,
        )
    }
}

@Composable
private fun TrailsBadge(
    open: Int, delayed: Int, closed: Int,
    onClick: () -> Unit,
) {
    val v = Vital.TRAILS
    BadgeFrame(v, null, onClick) {
        val total = open + delayed + closed
        if (total == 0) {
            Text("—", color = MV.OnSurface, fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text("No trails", color = MV.OnSurfaceDim, fontSize = 11.sp)
            return@BadgeFrame
        }
        Row(verticalAlignment = Alignment.Bottom) {
            Text("$open", color = Color(0xFF22C55E),
                fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(4.dp))
            Text("open", color = MV.OnSurfaceDim, fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 4.dp))
        }
        Spacer(Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (delayed > 0) {
                Text("$delayed delayed", color = Color(0xFFEAB308), fontSize = 11.sp)
            }
            if (closed > 0) {
                Text("$closed closed", color = Color(0xFFEF4444), fontSize = 11.sp)
            }
        }
        Spacer(Modifier.weight(1f))
        // Mini stacked bar showing proportions
        Row(Modifier.fillMaxWidth().height(6.dp).clip(
            androidx.compose.foundation.shape.RoundedCornerShape(3.dp)
        )) {
            if (open > 0) Box(Modifier.weight(open.toFloat()).fillMaxSize()
                .background(Color(0xFF22C55E)))
            if (delayed > 0) Box(Modifier.weight(delayed.toFloat()).fillMaxSize()
                .background(Color(0xFFEAB308)))
            if (closed > 0) Box(Modifier.weight(closed.toFloat()).fillMaxSize()
                .background(Color(0xFFEF4444)))
        }
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
        // Use the data's own time domain (8h fetch window typically),
        // not a hardcoded 2h tail — otherwise the badge goes blank
        // whenever the most-recent sample is older than 2h.
        val parsed = points.mapNotNull { p ->
            runCatching { Instant.parse(p.time).toEpochMilli() }.getOrNull()
                ?.let { it to p.value.toFloat() }
        }.sortedBy { it.first }
        if (parsed.size < 2) return@Canvas
        val start = parsed.first().first
        val end = (parsed.last().first.coerceAtLeast(nowMs - 1)).coerceAtLeast(start + 1)
        // Walk points and group into segments where consecutive samples
        // are within 8 min of each other; otherwise leave a gap.
        val segments = mutableListOf<MutableList<Pair<Long, Float>>>()
        var current = mutableListOf<Pair<Long, Float>>()
        var prevT: Long? = null
        for ((t, v) in parsed) {
            if (prevT != null && (t - prevT) > 8 * 60_000) {
                if (current.size >= 2) segments += current
                current = mutableListOf()
            }
            current += t to v
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

// ============================================================
// Manage-badges sheet — reorder + hide
// ============================================================

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun ManageBadgesSheet(
    canonical: List<Vital>,
    profile: app.myvitals.sync.ProfileResponse?,
    onDismiss: () -> Unit,
    onSave: (orderedNames: List<String>, hidden: Set<String>) -> Unit,
) {
    val savedOrder = profile?.extra?.vitalsOrder ?: emptyList()
    val initialOrder = remember {
        val byName = canonical.associateBy { it.name }
        val front = savedOrder.mapNotNull { byName[it] }
        val tail = canonical.filter { it.name !in savedOrder }
        (front + tail).map { it.name }
    }
    var order by remember { mutableStateOf(initialOrder) }
    var hidden by remember {
        mutableStateOf(profile?.extra?.vitalsHidden?.toSet() ?: emptySet())
    }

    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = MV.SurfaceContainer,
    ) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
            Text("Manage badges", color = MV.OnSurface,
                fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            Text("Use the arrows to reorder. Tap the eye to hide.",
                color = MV.OnSurfaceVariant, fontSize = 11.sp)
            Spacer(Modifier.height(8.dp))
            val byName = canonical.associateBy { it.name }
            for ((idx, name) in order.withIndex()) {
                val v = byName[name] ?: continue
                val isHidden = name in hidden
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(v.icon, contentDescription = null,
                        tint = v.color, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(v.label, color = if (isHidden) MV.OnSurfaceDim else MV.OnSurface,
                        fontSize = 14.sp, modifier = Modifier.weight(1f))
                    androidx.compose.material3.IconButton(
                        onClick = {
                            if (idx > 0) {
                                order = order.toMutableList().also {
                                    val tmp = it[idx]; it[idx] = it[idx - 1]; it[idx - 1] = tmp
                                }
                            }
                        },
                        enabled = idx > 0,
                    ) {
                        Icon(Icons.Outlined.ArrowDropUp, contentDescription = "Up",
                            tint = if (idx > 0) MV.OnSurface else MV.OnSurfaceDim)
                    }
                    androidx.compose.material3.IconButton(
                        onClick = {
                            if (idx < order.lastIndex) {
                                order = order.toMutableList().also {
                                    val tmp = it[idx]; it[idx] = it[idx + 1]; it[idx + 1] = tmp
                                }
                            }
                        },
                        enabled = idx < order.lastIndex,
                    ) {
                        Icon(Icons.Outlined.ArrowDropDown, contentDescription = "Down",
                            tint = if (idx < order.lastIndex) MV.OnSurface else MV.OnSurfaceDim)
                    }
                    androidx.compose.material3.IconButton(
                        onClick = {
                            hidden = if (isHidden) hidden - name else hidden + name
                        },
                    ) {
                        Icon(
                            if (isHidden) Icons.Outlined.VisibilityOff
                            else Icons.Outlined.Visibility,
                            contentDescription = if (isHidden) "Show" else "Hide",
                            tint = if (isHidden) MV.OnSurfaceDim else MV.OnSurface,
                        )
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                androidx.compose.material3.Button(
                    onClick = { onSave(order, hidden) },
                    modifier = Modifier.weight(1f),
                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                        containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                    ),
                ) { Text("Save") }
                androidx.compose.material3.TextButton(
                    onClick = onDismiss,
                    modifier = Modifier.weight(1f),
                ) { Text("Cancel") }
            }
        }
    }
}
