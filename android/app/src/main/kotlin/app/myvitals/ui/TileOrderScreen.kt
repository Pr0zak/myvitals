package app.myvitals.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.TilePrefOption
import app.myvitals.sync.TilePrefsIn
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * TILE-1 — Key-metrics tile order and visibility (phone half).
 *
 * Mirrors `frontend/src/components/TileOrderEditor.vue`. Both surfaces
 * read the same reconciled list from `GET /profile/tile-prefs`, so the
 * order shown here is the order the web shows, including for tiles this
 * build predates.
 *
 * Reordering is by move buttons rather than long-press drag: the list is
 * short, the buttons are reachable one-handed, and a drag handle inside a
 * scrolling LazyColumn needs gesture arbitration that is not worth it for
 * eight rows.
 */
@Composable
fun TileOrderScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()

    val neon = settings.neonShellEnabled
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val bad = if (neon) NeonMV.Bad else MV.Red
    val good = if (neon) NeonMV.Lime else MV.Green
    val onAccent = if (neon) NeonMV.OnAccent else MV.OnSurface
    val card = if (neon) NeonMV.Card else MV.Surface

    var rows by remember { mutableStateOf<List<TilePrefOption>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun fetch() {
        if (!settings.isConfigured()) { loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val prefs = withContext(Dispatchers.IO) { api.tilePrefs() }
            rows = prefs.available
            error = null
        } catch (e: Exception) {
            Timber.w(e, "tile prefs load failed")
            if (rows.isEmpty()) error = e.message?.take(160) ?: "Could not load."
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { fetch() }

    val visibleCount = rows.count { !it.hidden }

    fun move(index: Int, delta: Int) {
        val target = index + delta
        if (target < 0 || target >= rows.size) return
        val next = rows.toMutableList()
        val tmp = next[index]
        next[index] = next[target]
        next[target] = tmp
        rows = next
        status = null
    }

    fun toggle(index: Int) {
        // Guarded on both surfaces and again server-side. Hiding the last
        // visible tile removes the Key metrics section entirely, and with
        // it the entry point back to this screen.
        if (!rows[index].hidden && visibleCount <= 1) return
        val next = rows.toMutableList()
        next[index] = next[index].copy(hidden = !next[index].hidden)
        rows = next
        status = null
    }

    fun save(reset: Boolean = false) {
        scope.launch {
            saving = true; error = null; status = null
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val body = if (reset) {
                    // An empty order means "no preference" — the server
                    // reconciles it back to the default sequence, so the
                    // default list does not need duplicating here.
                    TilePrefsIn(order = emptyList(), hidden = emptyList())
                } else {
                    TilePrefsIn(
                        order = rows.map { it.key },
                        hidden = rows.filter { it.hidden }.map { it.key },
                    )
                }
                val prefs = withContext(Dispatchers.IO) { api.putTilePrefs(body) }
                rows = prefs.available
                status = if (reset) "Reset." else "Saved."
            } catch (e: Exception) {
                Timber.w(e, "tile prefs save failed")
                error = e.message?.take(160) ?: "Could not save."
            } finally {
                saving = false
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().background(bg).padding(horizontal = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = ink)
            }
            Text("Key metrics", color = ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        }

        Text(
            "Which metrics appear on the home screen, and in what order. "
                + "Applies to the web dashboard too.",
            color = muted, fontSize = 12.sp,
            modifier = Modifier.padding(start = 4.dp, bottom = 10.dp),
        )

        when {
            loading -> Text("Loading…", color = muted, modifier = Modifier.padding(4.dp))
            rows.isEmpty() -> Text(
                error ?: "Could not load.", color = bad, modifier = Modifier.padding(4.dp),
            )
            else -> {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(rows, key = { it.key }) { row ->
                        val index = rows.indexOfFirst { it.key == row.key }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(card)
                                .padding(horizontal = 10.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    row.label,
                                    color = if (row.hidden) muted else ink,
                                    fontSize = 15.sp,
                                )
                                row.group?.let {
                                    Text(it.uppercase(), color = muted, fontSize = 10.sp)
                                }
                            }
                            IconButton(
                                onClick = { move(index, -1) },
                                enabled = index > 0,
                                modifier = Modifier.size(36.dp),
                            ) {
                                Icon(
                                    Icons.Filled.KeyboardArrowUp,
                                    contentDescription = "Move ${row.label} up",
                                    tint = if (index > 0) ink else muted.copy(alpha = 0.4f),
                                )
                            }
                            IconButton(
                                onClick = { move(index, 1) },
                                enabled = index < rows.size - 1,
                                modifier = Modifier.size(36.dp),
                            ) {
                                Icon(
                                    Icons.Filled.KeyboardArrowDown,
                                    contentDescription = "Move ${row.label} down",
                                    tint = if (index < rows.size - 1) ink else muted.copy(alpha = 0.4f),
                                )
                            }
                            IconButton(
                                onClick = { toggle(index) },
                                enabled = row.hidden || visibleCount > 1,
                                modifier = Modifier.size(36.dp),
                            ) {
                                Icon(
                                    if (row.hidden) Icons.Filled.VisibilityOff
                                    else Icons.Filled.Visibility,
                                    contentDescription =
                                        if (row.hidden) "Show ${row.label}" else "Hide ${row.label}",
                                    tint = if (row.hidden) muted else accent,
                                )
                            }
                        }
                    }
                }

                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Button(
                        onClick = { save() },
                        enabled = !saving,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = accent, contentColor = onAccent,
                        ),
                    ) { Text(if (saving) "Saving…" else "Save order") }
                    Spacer(Modifier.size(8.dp))
                    TextButton(onClick = { save(reset = true) }, enabled = !saving) {
                        Text("Reset", color = muted)
                    }
                    Spacer(Modifier.weight(1f))
                    status?.let { Text(it, color = good, fontSize = 12.sp) }
                    error?.let { Text(it, color = bad, fontSize = 12.sp) }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
    }
}
