package app.myvitals.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Coffee
import androidx.compose.material.icons.outlined.LocalDrink
import androidx.compose.material.icons.outlined.Mood
import androidx.compose.material.icons.outlined.Note
import androidx.compose.material.icons.outlined.MedicalServices
import androidx.compose.material.icons.outlined.Restaurant
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
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.Annotation
import app.myvitals.sync.AnnotationCreate
import app.myvitals.sync.BackendClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

/**
 * Phone parity for the web Today AnnotationLog (LOG-3).
 *
 * Mirrors the web quick-add row: five one-tap buttons (Caffeine /
 * Alcohol / Food / Mood / Meds) each POST `/journal` with the same
 * default payload shape Journal.vue uses, so later edits on either
 * surface round-trip cleanly. A history list below shows recent
 * entries.
 *
 * Free-text notes are intentionally not surfaced here — they remain
 * an edit-on-the-web affordance. The phone is optimised for
 * frictionless tap-in-the-moment logging.
 */

private data class QuickAdd(
    val kind: String,
    val label: String,
    val icon: ImageVector,
    val payload: Map<String, Any>,
)

private val QUICK_ADDS = listOf(
    QuickAdd("caffeine", "Caffeine", Icons.Outlined.Coffee,
        mapOf("mg" to 100, "source" to "coffee")),
    QuickAdd("alcohol", "Alcohol", Icons.Outlined.LocalDrink,
        mapOf("drinks" to 1, "type" to "beer")),
    QuickAdd("food", "Food", Icons.Outlined.Restaurant,
        mapOf("description" to "")),
    QuickAdd("mood", "Mood", Icons.Outlined.Mood,
        mapOf("score" to 7)),
    QuickAdd("meds", "Meds", Icons.Outlined.MedicalServices,
        mapOf("name" to "", "dose" to "")),
)

@Composable
fun JournalScreen(settings: SettingsRepository, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<Annotation>>(emptyList()) }
    var busy by remember { mutableStateOf<String?>(null) }
    var flash by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun reload() {
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            rows = withContext(Dispatchers.IO) { api.journalList(limit = 30) }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "journal list failed")
            error = e.message?.take(160)
        }
    }

    LaunchedEffect(Unit) { reload() }

    fun quickAdd(q: QuickAdd) {
        if (busy != null) return
        busy = q.kind
        error = null
        scope.launch {
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                withContext(Dispatchers.IO) {
                    api.journalCreate(
                        AnnotationCreate(type = q.kind, payload = q.payload),
                    )
                }
                flash = q.kind
                reload()
            } catch (e: Exception) {
                Timber.w(e, "journal create failed: %s", q.kind)
                error = "Failed: ${e.message?.take(80)}"
            } finally {
                busy = null
            }
        }
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
            Icon(Icons.Outlined.Note, contentDescription = null, tint = MV.OnSurface,
                modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Journal", color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }

        Card(
            colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
        ) {
            Column(Modifier.padding(14.dp)) {
                Text("QUICK LOG", color = MV.OnSurfaceVariant,
                    fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
                Spacer(Modifier.height(10.dp))
                // Wrap by row of three so labels stay readable on narrow screens.
                val chunks = QUICK_ADDS.chunked(3)
                chunks.forEachIndexed { idx, chunk ->
                    if (idx > 0) Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        chunk.forEach { q ->
                            QuickButton(
                                q = q,
                                busy = busy == q.kind,
                                flash = flash == q.kind,
                                enabled = busy == null,
                                onClick = { quickAdd(q) },
                                modifier = Modifier.weight(1f),
                            )
                        }
                        // Pad row to 3 cells so widths stay consistent on the last row.
                        repeat(3 - chunk.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
                if (error != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(error!!, color = MV.Red, fontSize = 11.sp)
                }
            }
        }

        Spacer(Modifier.height(6.dp))

        LazyColumn(
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (rows.isEmpty()) {
                item {
                    Text("No entries yet — tap a quick-log above.",
                        color = MV.OnSurfaceDim, fontSize = 12.sp,
                        modifier = Modifier.padding(8.dp))
                }
            } else {
                items(rows, key = { it.id }) { a ->
                    JournalRow(a)
                }
            }
        }
    }
}

@Composable
private fun QuickButton(
    q: QuickAdd,
    busy: Boolean,
    flash: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val bg = when {
        flash -> Color(0x2922C55E)
        busy  -> MV.SurfaceContainerHigh
        else  -> MV.SurfaceContainerLow
    }
    val borderColor = if (flash) Color(0x8C22C55E) else MV.OutlineVariant
    Card(
        colors = CardDefaults.cardColors(containerColor = bg),
        modifier = modifier
            .height(56.dp)
            .border(BorderStroke(1.dp, borderColor), RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClick = onClick),
    ) {
        Column(
            Modifier.fillMaxSize().padding(6.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(q.icon, contentDescription = q.label, tint = MV.OnSurface,
                modifier = Modifier.size(18.dp))
            Spacer(Modifier.height(3.dp))
            Text(q.label, color = MV.OnSurface, fontSize = 10.sp,
                fontWeight = FontWeight.Medium, maxLines = 1)
        }
    }
}

@Composable
private fun JournalRow(a: Annotation) {
    val whenLabel = remember(a.ts) {
        runCatching {
            val t = Instant.parse(a.ts).toEpochMilli()
            val ageMs = System.currentTimeMillis() - t
            when {
                ageMs < 60_000     -> "just now"
                ageMs < 3_600_000  -> "${ageMs / 60_000}m ago"
                ageMs < 86_400_000 -> "${ageMs / 3_600_000}h ago"
                else                -> "${ageMs / 86_400_000}d ago"
            }
        }.getOrDefault("—")
    }
    val summary = remember(a.payload) {
        a.payload.entries.joinToString(" · ") { (_, v) -> v.toString() }
            .ifBlank { "—" }
    }
    val icon: ImageVector = when (a.type) {
        "caffeine" -> Icons.Outlined.Coffee
        "alcohol"  -> Icons.Outlined.LocalDrink
        "food"     -> Icons.Outlined.Restaurant
        "mood"     -> Icons.Outlined.Mood
        "meds"     -> Icons.Outlined.MedicalServices
        else        -> Icons.Outlined.Note
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(icon, contentDescription = null, tint = MV.OnSurfaceVariant,
                modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(a.type.replaceFirstChar { it.titlecase() },
                    color = MV.OnSurface, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                Text(summary, color = MV.OnSurfaceVariant, fontSize = 11.sp, maxLines = 1)
            }
            Text(whenLabel, color = MV.OnSurfaceDim, fontSize = 11.sp)
        }
    }
}
