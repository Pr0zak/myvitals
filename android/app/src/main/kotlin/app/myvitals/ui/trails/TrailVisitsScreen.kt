package app.myvitals.ui.trails

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.automirrored.outlined.DirectionsWalk
import androidx.compose.material.icons.outlined.Hiking
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Rowing
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.TrailVisit
import app.myvitals.sync.TrailVisitsResponse
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter

/**
 * Every activity linked to one trail, newest first.
 *
 * Backed by `GET /trails/{id}/visits`, which already existed for the
 * visit counters on the trails list — this screen just surfaces the rows
 * behind those counts. Tapping a visit opens the activity detail.
 *
 * `days` is set wide (10 years) rather than the endpoint's 365-day
 * default: the trails list shows an all-time `visits_total`, so a
 * one-year window here would show fewer rows than the badge promises.
 */
@Composable
fun TrailVisitsScreen(
    settings: SettingsRepository,
    trailId: Long,
    onBack: () -> Unit,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    val neon = settings.neonShellEnabled

    var data by remember { mutableStateOf<TrailVisitsResponse?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val bg = if (neon) NeonMV.Bg else Color(0xFF0F1620)
    val cardBg = if (neon) NeonMV.Card else Color(0xFF16202B)
    val fg = if (neon) NeonMV.Ink else Color(0xFFE2E8F0)
    val dim = if (neon) NeonMV.Muted else Color(0xFF94A3B8)
    val accent = if (neon) NeonMV.Lime else Color(0xFF22C55E)

    val cacheKey = "trail_visits_$trailId"

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.trailVisits(trailId) }
            data = resp
            error = null
            JsonCache.write(context, cacheKey, TrailVisitsResponse::class.java, resp)
        } catch (e: Exception) {
            Timber.w(e, "trail visits load failed")
            if (data == null) error = e.message ?: "Failed to load visits"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(trailId) {
        JsonCache.read<TrailVisitsResponse>(
            context, cacheKey, TrailVisitsResponse::class.java,
        )?.value?.let { data = it; loading = false }
        fetch()
    }

    val visits = data?.visits ?: emptyList()

    Column(Modifier.fillMaxSize().background(bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back", tint = fg)
            }
            Column(Modifier.weight(1f)) {
                Text(
                    data?.name ?: "Trail",
                    color = fg, fontWeight = FontWeight.SemiBold, fontSize = 16.sp,
                )
                Text(
                    when {
                        loading && data == null -> "Loading…"
                        visits.isEmpty() -> "No linked activities"
                        else -> "${visits.size} linked " +
                            if (visits.size == 1) "activity" else "activities"
                    },
                    color = dim, fontSize = 12.sp,
                )
            }
        }

        PullableMetricBox(
            refreshing = refreshing,
            onRefresh = {
                refreshing = true
                try { fetch() } finally { refreshing = false }
            },
            modifier = Modifier.weight(1f),
        ) {
            when {
                error != null && data == null -> Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Couldn't load visits", color = fg, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(6.dp))
                    Text(error ?: "", color = dim, fontSize = 12.sp)
                }
                visits.isEmpty() && !loading -> Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("No activities linked yet", color = fg,
                        fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Use \"Link activities\" on the Trails screen to match "
                            + "GPS activities to this trail.",
                        color = dim, fontSize = 12.sp,
                    )
                }
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(visits, key = { "${it.source}/${it.sourceId}" }) { v ->
                        VisitRow(v, cardBg, fg, dim, accent) {
                            onOpenActivity(v.source, v.sourceId)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun VisitRow(
    v: TrailVisit,
    cardBg: Color,
    fg: Color,
    dim: Color,
    accent: Color,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(cardBg)
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(28.dp), contentAlignment = Alignment.Center) {
            Icon(iconFor(v.type), contentDescription = null, tint = accent,
                modifier = Modifier.size(20.dp))
        }
        Spacer(Modifier.size(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                v.name?.takeIf { it.isNotBlank() } ?: v.type,
                color = fg, fontSize = 14.sp, fontWeight = FontWeight.Medium,
                maxLines = 1,
            )
            Text(prettyDate(v.startAt), color = dim, fontSize = 11.sp)
        }
        Column(horizontalAlignment = Alignment.End) {
            v.distanceM?.let {
                Text(String.format("%.1f mi", it / 1609.344), color = fg, fontSize = 13.sp)
            }
            Text(prettyDuration(v.durationS), color = dim, fontSize = 11.sp)
        }
    }
}

private fun iconFor(type: String): ImageVector {
    val t = type.lowercase()
    return when {
        t.contains("hike") -> Icons.Outlined.Hiking
        t.contains("run") || t.contains("jog") -> Icons.AutoMirrored.Outlined.DirectionsRun
        t.contains("walk") -> Icons.AutoMirrored.Outlined.DirectionsWalk
        t.contains("kayak") || t.contains("row") || t.contains("paddle") ->
            Icons.Outlined.Rowing
        t.contains("bike") || t.contains("cycl") || t.contains("ride") ->
            Icons.AutoMirrored.Outlined.DirectionsBike
        else -> Icons.Outlined.MonitorHeart
    }
}

private fun prettyDate(iso: String): String = runCatching {
    OffsetDateTime.parse(iso).format(DateTimeFormatter.ofPattern("MMM d, yyyy"))
}.getOrDefault(iso.take(10))

private fun prettyDuration(seconds: Int): String {
    if (seconds <= 0) return "—"
    val h = seconds / 3600
    val m = (seconds % 3600) / 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}
