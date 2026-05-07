package app.myvitals.ui.trails

import android.content.Intent
import android.net.Uri
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
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.Trail
import app.myvitals.sync.TrailSubscribeBody
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

@Composable
fun TrailsScreen(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    var trails by remember { mutableStateOf<List<Trail>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.trails() }
            trails = r.trails.sortedBy { it.name }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "trails load failed")
            error = e.message?.take(160)
        } finally {
            loading = false
        }
    }

    suspend fun refreshNow() {
        if (!settings.isConfigured()) return
        refreshing = true
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) { api.refreshTrails() }
            load()
        } catch (e: Exception) {
            Timber.w(e, "trails refresh failed")
            error = e.message?.take(160)
        } finally {
            refreshing = false
        }
    }

    suspend fun toggleSubscribe(t: Trail) {
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                if (t.subscribed) api.unsubscribeTrail(t.id)
                else api.subscribeTrail(t.id, TrailSubscribeBody("any"))
            }
            load()
        } catch (e: Exception) {
            Timber.w(e, "subscribe toggle failed")
            error = e.message?.take(160)
        }
    }

    LaunchedEffect(Unit) { load() }
    LaunchedEffect(Unit) {
        while (true) { delay(60_000); nowMs = System.currentTimeMillis() }
    }

    val grouped by remember(trails) {
        derivedStateOf {
            Triple(
                trails.filter { it.status == "open" },
                trails.filter { it.status == "closed" },
                trails.filter { it.status != "open" && it.status != "closed" },
            )
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text(
                    "TRAILS",
                    color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp,
                )
                Text(
                    if (trails.isEmpty()) "—"
                    else "${grouped.first.size} open · ${grouped.second.size} closed",
                    color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                )
            }
            TextButton(onClick = { scope.launch { refreshNow() } }, enabled = !refreshing) {
                Icon(Icons.Filled.Refresh, contentDescription = "Refresh", tint = MV.OnSurface)
                Spacer(Modifier.width(4.dp))
                Text(if (refreshing) "Refreshing…" else "Refresh", color = MV.OnSurface)
            }
        }

        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant)
            error != null -> Text(error!!, color = MV.Red)
            trails.isEmpty() -> Card(
                colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "No trails seeded yet. The backend poller runs every 15 minutes; tap Refresh to trigger an immediate poll.",
                    modifier = Modifier.padding(14.dp),
                    color = MV.OnSurfaceVariant,
                )
            }
            else -> LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (grouped.first.isNotEmpty()) {
                    item { GroupHeader("Open · ${grouped.first.size}") }
                    items(grouped.first, key = { it.id }) { t ->
                        TrailRow(t, nowMs) { scope.launch { toggleSubscribe(t) } }
                    }
                }
                if (grouped.second.isNotEmpty()) {
                    item { GroupHeader("Closed · ${grouped.second.size}") }
                    items(grouped.second, key = { it.id }) { t ->
                        TrailRow(t, nowMs) { scope.launch { toggleSubscribe(t) } }
                    }
                }
                if (grouped.third.isNotEmpty()) {
                    item { GroupHeader("Other · ${grouped.third.size}") }
                    items(grouped.third, key = { it.id }) { t ->
                        TrailRow(t, nowMs) { scope.launch { toggleSubscribe(t) } }
                    }
                }
            }
        }
    }
}

@Composable
private fun GroupHeader(text: String) {
    Text(
        text, color = MV.OnSurfaceVariant,
        fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp,
        modifier = Modifier.padding(top = 10.dp, bottom = 2.dp),
    )
}

@Composable
private fun TrailRow(t: Trail, nowMs: Long, onSubscribeToggle: () -> Unit) {
    val context = LocalContext.current
    val color = when (t.status) {
        "open" -> Color(0xFF22C55E)
        "closed" -> Color(0xFFEF4444)
        else -> MV.OnSurfaceVariant
    }
    val hasLocation = t.latitude != null && t.longitude != null
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth().clickable {
            if (hasLocation) openMapsNav(context, t)
        },
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(modifier = Modifier.size(10.dp).clip(CircleShape).background(color))
            Spacer(Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(t.name, color = MV.OnSurface, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                if (!t.comment.isNullOrBlank()) {
                    Text(t.comment, color = MV.OnSurfaceVariant, fontSize = 12.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val ageStr = remember(nowMs, t.sourceTs, t.fetchedAt) {
                        fmtAge(t.sourceTs ?: t.fetchedAt, nowMs)
                    }
                    if (ageStr.isNotEmpty()) {
                        Text(ageStr, color = MV.OnSurfaceDim, fontSize = 11.sp)
                    }
                    val cityStr = listOfNotNull(t.city, t.state).joinToString(", ")
                    if (cityStr.isNotEmpty()) {
                        Text(
                            "  ·  $cityStr",
                            color = MV.OnSurfaceDim, fontSize = 11.sp,
                        )
                    }
                    if (hasLocation) {
                        Spacer(Modifier.width(6.dp))
                        Icon(
                            Icons.Filled.Navigation,
                            contentDescription = "Open in maps",
                            tint = MV.OnSurfaceDim,
                            modifier = Modifier.size(12.dp),
                        )
                    }
                }
            }
            IconButton(onClick = onSubscribeToggle) {
                Icon(
                    if (t.subscribed) Icons.Filled.Star else Icons.Filled.StarBorder,
                    contentDescription = if (t.subscribed) "Unsubscribe" else "Subscribe",
                    tint = if (t.subscribed) MV.Amber else MV.OnSurfaceVariant,
                )
            }
        }
    }
}

private fun openMapsNav(context: android.content.Context, t: Trail) {
    val lat = t.latitude ?: return
    val lon = t.longitude ?: return
    val label = Uri.encode(t.name)
    // Prefer Google Maps' navigation intent; fall back to a generic geo: query;
    // fall back to an https Maps URL if neither registers.
    val candidates = listOf(
        Uri.parse("google.navigation:q=$lat,$lon"),
        Uri.parse("geo:$lat,$lon?q=$lat,$lon($label)"),
        Uri.parse("https://www.google.com/maps/search/?api=1&query=$lat,$lon"),
    )
    for (uri in candidates) {
        try {
            val intent = Intent(Intent.ACTION_VIEW, uri).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            if (intent.resolveActivity(context.packageManager) != null) {
                context.startActivity(intent); return
            }
        } catch (_: Exception) { /* try next */ }
    }
    Timber.w("openMapsNav: no map app could handle the intent")
}

private fun fmtAge(iso: String?, nowMs: Long): String {
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
