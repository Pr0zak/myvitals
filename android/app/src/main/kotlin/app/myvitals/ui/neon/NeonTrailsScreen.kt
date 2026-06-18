package app.myvitals.ui.neon

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.Trail
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Trails — neon RainoutLine status board. Mirrors web `TrailsHub.vue`: a
 * per-trail open/wet-delayed/closed board from /trails, open-first sort, a
 * force-refresh, and a tap that drills into the full map/history Trails
 * screen via [onOpen]("trails").
 */

/** Status → (label, glow color), byte-identical intent to web's STATUS map. */
private data class TrailStatus(val label: String, val color: Color)

private fun statusFor(raw: String?): TrailStatus = when (raw) {
    "open" -> TrailStatus("Open", NeonMV.Lime)
    "delayed" -> TrailStatus("Wet · delayed", NeonMV.Amber)
    "closed" -> TrailStatus("Closed", NeonMV.Bad)
    else -> TrailStatus("Unknown", NeonMV.Muted)
}

/** Open first, then delayed, closed, unknown; subscribed floats up within. */
private fun statusRank(raw: String?): Int = when (raw) {
    "open" -> 0
    "delayed" -> 1
    "closed" -> 2
    else -> 3
}

private fun placeOf(t: Trail): String =
    listOfNotNull(t.city?.takeIf { it.isNotBlank() }, t.state?.takeIf { it.isNotBlank() })
        .joinToString(", ")
        .ifBlank { "—" }

@Composable
fun NeonTrailsScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var trails by remember { mutableStateOf<List<Trail>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }

    suspend fun load() {
        val r = runCatching {
            withContext(Dispatchers.IO) {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                api.trails()
            }
        }.getOrNull()
        if (r != null) {
            trails = r.trails.sortedWith(
                compareBy<Trail> { statusRank(it.status) }
                    .thenByDescending { it.subscribed },
            )
        }
        loading = false
    }

    LaunchedEffect(Unit) { load() }

    val openCount = trails.count { it.status == "open" }

    NeonScreen(
        title = "Trails",
        contentPadding = contentPadding,
        headerTrailing = {
            // Force-refresh: refreshTrails() then reload, matching the web ↻.
            RefreshButton(
                spinning = refreshing,
                onClick = {
                    if (refreshing) return@RefreshButton
                    scope.launch {
                        refreshing = true
                        runCatching {
                            withContext(Dispatchers.IO) {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                api.refreshTrails()
                            }
                        }
                        load()
                        refreshing = false
                    }
                },
            )
        },
    ) {
        if (!loading) {
            Text(
                "$openCount of ${trails.size} open · RAINOUTLINE",
                color = NeonMV.Muted,
                fontFamily = NeonNumberFamily,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 0.7.sp,
                modifier = Modifier.padding(bottom = 16.dp),
            )
        }

        when {
            loading -> {
                Text(
                    "Loading trails…",
                    color = NeonMV.Muted,
                    fontSize = 14.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 48.dp),
                )
            }
            trails.isEmpty() -> {
                Text(
                    "No trails configured. Set your RainoutLine DNIS in " +
                        "Settings → Trail status.",
                    color = NeonMV.Muted,
                    fontSize = 14.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 48.dp, horizontal = 8.dp),
                )
            }
            else -> {
                Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
                    for (t in trails) {
                        TrailRow(t) { onOpen("trails") }
                    }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun RefreshButton(spinning: Boolean, onClick: () -> Unit) {
    val rotation = if (spinning) {
        val transition = rememberInfiniteTransition(label = "trails-refresh")
        transition.animateFloat(
            initialValue = 0f,
            targetValue = 360f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = 800, easing = LinearEasing),
            ),
            label = "trails-refresh-rot",
        ).value
    } else 0f

    Box(
        modifier = Modifier
            .size(42.dp)
            .clip(CircleShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Track, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            "↻",
            color = NeonMV.Cyan,
            fontSize = 20.sp,
            modifier = Modifier.graphicsLayer { rotationZ = rotation },
        )
    }
}

@Composable
private fun TrailRow(t: Trail, onClick: () -> Unit) {
    val s = statusFor(t.status)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(horizontal = 18.dp, vertical = 15.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Glowing status dot — colored shadow ring approximates the web glow.
        Box(
            modifier = Modifier.size(20.dp),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(20.dp)
                    .clip(CircleShape)
                    .background(s.color.copy(alpha = 0.22f)),
            )
            Box(
                modifier = Modifier
                    .size(12.dp)
                    .clip(CircleShape)
                    .background(s.color),
            )
        }
        Spacer(Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    t.name,
                    color = NeonMV.Ink,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (t.subscribed) {
                    Spacer(Modifier.width(6.dp))
                    Text("★", color = NeonMV.Amber, fontSize = 13.sp)
                }
            }
            Spacer(Modifier.height(2.dp))
            Text(
                buildString {
                    append(placeOf(t))
                    t.comment?.takeIf { it.isNotBlank() }?.let { append(" · $it") }
                },
                color = NeonMV.Muted,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(10.dp))
        Text(
            s.label,
            color = s.color,
            fontFamily = NeonNumberFamily,
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}
