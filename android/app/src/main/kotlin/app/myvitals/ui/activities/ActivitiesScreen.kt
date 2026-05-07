package app.myvitals.ui.activities

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.automirrored.outlined.DirectionsWalk
import androidx.compose.material.icons.outlined.Hiking
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.BackendClient
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

@Composable
fun ActivitiesScreen(
    settings: SettingsRepository,
    onOpenActivity: (source: String, sourceId: String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<ActivityRow>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."; loading = false; return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            rows = withContext(Dispatchers.IO) { api.activities(limit = 80) }
            error = null
            val withTrail = rows.count { it.trailId != null }
            Timber.i("activities loaded: %d rows (%d linked to a trail)",
                rows.size, withTrail)
        } catch (e: Exception) {
            Timber.w(e, "activities load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    Column(Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 16.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text("ACTIVITIES",
                    color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                Text(
                    if (rows.isEmpty() && !loading) "—" else "${rows.size} recent",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            IconButton(onClick = { scope.launch { loading = true; load() } }, enabled = !loading) {
                Icon(Icons.Outlined.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
            }
        }

        when {
            loading && rows.isEmpty() -> Text("Loading…", color = MV.OnSurfaceVariant)
            error != null -> Text(error!!, color = MV.Red)
            rows.isEmpty() -> Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "No activities yet. Connect Strava in Settings to start syncing.",
                    Modifier.padding(14.dp), color = MV.OnSurfaceVariant,
                )
            }
            else -> LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(rows, key = { "${it.source}-${it.sourceId}" }) { a ->
                    ActivityListRow(a, nowMs) { onOpenActivity(a.source, a.sourceId) }
                }
            }
        }
    }
}

@Composable
private fun ActivityListRow(a: ActivityRow, nowMs: Long, onClick: () -> Unit) {
    val icon = iconForType(a.type)
    val title = a.name?.takeIf { it.isNotBlank() } ?: prettyType(a.type)
    val ageStr = remember(nowMs, a.startAt) { fmtAge(a.startAt, nowMs) }
    val miles = a.distanceM?.let { "%.1f mi".format(it / 1609.34) } ?: "—"
    val mins = a.durationS / 60
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(32.dp).clip(CircleShape).background(MV.SurfaceContainerLow),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = a.type,
                    tint = MV.OnSurface, modifier = Modifier.size(18.dp))
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(title, color = MV.OnSurface, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, maxLines = 1)
                Text("$ageStr  ·  $miles  ·  ${mins}m",
                    color = MV.OnSurfaceVariant, fontSize = 11.sp)
            }
            if (a.trailName != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Link, contentDescription = "Linked",
                        tint = MV.OnSurfaceVariant, modifier = Modifier.size(12.dp))
                    Spacer(Modifier.width(4.dp))
                    Text(a.trailName, color = MV.OnSurfaceVariant, fontSize = 11.sp,
                        fontWeight = FontWeight.Medium, maxLines = 1)
                }
            }
        }
    }
}

internal fun iconForType(type: String): ImageVector = when {
    type.contains("Ride", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsBike
    type.contains("Run", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsRun
    type.contains("Hike", ignoreCase = true) -> Icons.Outlined.Hiking
    type.contains("Walk", ignoreCase = true) -> Icons.AutoMirrored.Outlined.DirectionsWalk
    else -> Icons.AutoMirrored.Outlined.DirectionsBike
}

internal fun prettyType(type: String): String =
    type.replace(Regex("([a-z])([A-Z])"), "$1 $2")

internal fun fmtAge(iso: String?, nowMs: Long): String {
    if (iso.isNullOrBlank()) return ""
    return try {
        val ms = nowMs - Instant.parse(iso).toEpochMilli()
        val m = ms / 60_000
        when {
            m < 1 -> "just now"
            m < 60 -> "${m}m ago"
            m < 60 * 24 -> "${m / 60}h ago"
            else -> "${m / (60 * 24)}d ago"
        }
    } catch (_: Exception) { "" }
}
