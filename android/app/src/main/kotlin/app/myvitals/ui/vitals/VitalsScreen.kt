package app.myvitals.ui.vitals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate

/** Identifier for each Vitals badge — used by the detail route + future preferences. */
enum class Vital(val label: String, val icon: ImageVector, val color: Color) {
    HR("Heart rate", Icons.Outlined.FavoriteBorder, Color(0xFFEF4444)),
    HRV("HRV", Icons.Outlined.Speed, Color(0xFFA855F7)),
    SLEEP("Sleep", Icons.Outlined.Bedtime, Color(0xFF60A5FA)),
    STEPS("Steps", Icons.AutoMirrored.Outlined.DirectionsRun, Color(0xFF22C55E)),
    WEIGHT("Weight", Icons.Outlined.MonitorWeight, Color(0xFFF59E0B)),
    BP("Blood pressure", Icons.Outlined.FavoriteBorder, Color(0xFFEC4899)),
    SOBER("Sober", Icons.Outlined.Timer, Color(0xFF84CC16)),
}

@Composable
fun VitalsScreen(
    settings: SettingsRepository,
    onOpenSettings: () -> Unit,
    onOpenSober: () -> Unit,
    onOpenVitalDetail: (Vital) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var sober by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."; loading = false; return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since = LocalDate.now().minusDays(29).toString()
            val (summaries, soberResp) = withContext(Dispatchers.IO) {
                Pair(api.summaryRange(since = since), runCatching { api.soberCurrent() }.getOrNull())
            }
            rows = summaries
            sober = soberResp
            error = null
            Timber.i(
                "vitals loaded: %d daily rows; latest=%s sober_active=%s",
                summaries.size, summaries.lastOrNull()?.date,
                soberResp?.active != null,
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

    val tiles by remember(rows) {
        derivedStateOf {
            // Default order — Stage 2 will make this user-configurable.
            listOf(
                Vital.HR, Vital.SLEEP, Vital.STEPS, Vital.HRV,
                Vital.WEIGHT, Vital.BP, Vital.SOBER,
            )
        }
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
                    androidx.compose.material3.TextButton(onClick = onOpenSettings) {
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
                    Vital.SOBER -> SoberBadge(sober, nowMs, onClick = onOpenSober)
                    Vital.HR -> Badge(
                        v, valueOf(rows) { it.restingHr },
                        unit = "bpm", series = seriesOf(rows) { it.restingHr },
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.HRV -> Badge(
                        v, valueOf(rows) { it.hrvAvg },
                        unit = "ms", series = seriesOf(rows) { it.hrvAvg },
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.SLEEP -> Badge(
                        v,
                        rows.lastOrNull { it.sleepDurationS != null }?.sleepDurationS?.let {
                            "%.1f h".format(it / 3600.0)
                        },
                        unit = null,
                        series = seriesOf(rows) {
                            it.sleepDurationS?.toDouble()?.div(3600.0)
                        },
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.STEPS -> Badge(
                        v,
                        rows.lastOrNull { it.stepsTotal != null }?.stepsTotal?.toString(),
                        unit = "steps",
                        series = seriesOf(rows) { it.stepsTotal?.toDouble() },
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.WEIGHT -> Badge(
                        v,
                        rows.lastOrNull { it.weightKg != null }?.weightKg?.let {
                            "%.1f lb".format(it * 2.20462)
                        },
                        unit = null,
                        series = seriesOf(rows) { it.weightKg?.times(2.20462) },
                        onClick = { onOpenVitalDetail(v) },
                    )
                    Vital.BP -> {
                        val latest = rows.lastOrNull {
                            it.bpSystolicAvg != null && it.bpDiastolicAvg != null
                        }
                        Badge(
                            v,
                            latest?.let {
                                "%.0f/%.0f".format(it.bpSystolicAvg!!, it.bpDiastolicAvg!!)
                            },
                            unit = "mmHg",
                            series = seriesOf(rows) { it.bpSystolicAvg },
                            onClick = { onOpenVitalDetail(v) },
                        )
                    }
                }
            }
        }
    }
}

private fun valueOf(rows: List<DailySummary>, sel: (DailySummary) -> Double?): String? {
    val v = rows.lastOrNull { sel(it) != null }?.let(sel) ?: return null
    return "%.0f".format(v)
}

private fun seriesOf(rows: List<DailySummary>, sel: (DailySummary) -> Double?): List<Float?> =
    rows.map { sel(it)?.toFloat() }

@Composable
private fun Badge(
    v: Vital,
    valueText: String?,
    unit: String?,
    series: List<Float?>,
    onClick: () -> Unit,
) {
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
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            }
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    valueText ?: "—",
                    color = MV.OnSurface, fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                )
                if (unit != null && valueText != null) {
                    Spacer(Modifier.width(4.dp))
                    Text(unit, color = MV.OnSurfaceDim, fontSize = 11.sp,
                        modifier = Modifier.padding(bottom = 4.dp))
                }
            }
            Spacer(Modifier.height(6.dp))
            Box(Modifier.fillMaxWidth().height(34.dp)) {
                SparkLine(series, color = v.color)
            }
        }
    }
}

@Composable
private fun SoberBadge(
    sober: SoberCurrentResponse?,
    @Suppress("UNUSED_PARAMETER") nowMs: Long,
    onClick: () -> Unit,
) {
    val v = Vital.SOBER
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
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            }
            Spacer(Modifier.height(8.dp))
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
            Text(
                "Tap to manage",
                color = MV.OnSurfaceDim, fontSize = 10.sp,
            )
        }
    }
}
