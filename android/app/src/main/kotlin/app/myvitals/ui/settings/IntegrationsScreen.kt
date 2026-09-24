package app.myvitals.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.DataHealth
import app.myvitals.sync.IntegrationHealth
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.launch
import timber.log.Timber

/** Integrations the phone may trigger a sync for. The rest either poll on
 *  their own (Google Health) or need the dashboard's query token. */
internal val PHONE_SYNCABLE = setOf("strava", "concept2")

/**
 * Integrations (SETTINGS-C). Mirrors web `settings/SettingsIntegrations.vue`.
 *
 * Status, last sync, last item and any error for each integration, straight
 * from `/query/data-health` — the same verdict the web shows. "Sync now"
 * appears where the phone's token can reach a sync endpoint (Strava cookie
 * sync, Concept2). Connecting, reconnecting and pasting credentials are set
 * up on the web by declaration: they go through sign-in pages and secrets
 * that do not belong in a phone form.
 */
@Composable
fun IntegrationsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var health by remember { mutableStateOf<DataHealth?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var syncing by remember { mutableStateOf<Set<String>>(emptySet()) }
    var messages by remember { mutableStateOf<Map<String, String>>(emptyMap()) }

    suspend fun load() {
        try {
            health = settings.call { dataHealth() }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "integrations load failed")
            error = e.settingsMessage()
        } finally {
            loading = false
        }
    }
    LaunchedEffect(Unit) { load() }

    IntegrationsContent(
        health = health, loading = loading, refreshing = refreshing, error = error,
        syncing = syncing, messages = messages,
        onSync = { key ->
            scope.launch {
                syncing = syncing + key
                val msg = try {
                    when (key) {
                        "strava" -> settings.call { stravaCookieSync() }.let { r ->
                            when {
                                r.error != null -> "Strava answered with an error: ${r.error}"
                                r.upserted == 0 -> "Up to date — nothing new."
                                else -> "Synced ${r.upserted} new."
                            }
                        }
                        "concept2" -> settings.call { concept2Sync() }.let { r ->
                            if (r.upserted == 0) "Up to date — nothing new." else "Synced ${r.upserted} new."
                        }
                        else -> "This one syncs on its own."
                    }
                } catch (e: Exception) {
                    "Sync failed: ${e.settingsMessage()}"
                }
                messages = messages + (key to msg)
                syncing = syncing - key
                load()
            }
        },
        onBack = onBack,
        onRefresh = { scope.launch { refreshing = true; try { load() } finally { refreshing = false } } },
    )
}

@Composable
fun IntegrationsContent(
    health: DataHealth?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    syncing: Set<String>,
    messages: Map<String, String>,
    onSync: (String) -> Unit,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    NeonScreen(
        title = "Integrations",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (health == null) {
            if (error != null && !loading) {
                NeonErrorBanner(error, title = "Couldn't load integration status") { onRefresh() }
            } else {
                SettingsSkeleton(listOf(130.dp, 130.dp, 130.dp))
            }
        } else {
            if (error != null) {
                NeonErrorBanner(error, title = "Couldn't refresh — showing the last status") { onRefresh() }
            }
            NeonEyebrow("Connected services")
            for (i in health.integrations) {
                IntegrationCard(
                    i, problem = i.key in health.problemKeys,
                    syncing = i.key in syncing, message = messages[i.key],
                    onSync = { onSync(i.key) },
                )
            }
        }
        WebOnlyNote(
            "Connecting a service, reconnecting an expired one and entering credentials are " +
                "done on the web — they go through sign-in pages and pasted keys.",
        )
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun IntegrationCard(
    i: IntegrationHealth,
    problem: Boolean,
    syncing: Boolean,
    message: String?,
    onSync: () -> Unit,
) {
    val (pill, color) = integrationPill(i, problem)
    SettingsCard {
        Row(
            Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(i.label, color = NeonMV.Ink, fontSize = 16.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f))
            StatusPill(pill, color)
        }
        if (i.configured) {
            SettingsKv("Last sync", fmtAgeHours(i.ageHours).let { if (it == "never") it else "$it ago" })
            SettingsKv(
                "Newest item",
                fmtAgeHours(i.itemAgeHours).let { if (it == "never") "none yet" else "$it ago" },
            )
            if (i.importingNothing) {
                SettingsNote("Polling works, but nothing new has arrived for a month. " +
                    "That may simply be a quiet month.")
            }
        } else {
            SettingsNote("Not connected. Set it up on the web.")
        }
        i.lastError?.let { SettingsNote(it.take(200), color = NeonMV.Amber) }
        i.action?.let {
            SettingsNote(it, color = if (i.needsReconnect) NeonMV.Amber else NeonMV.Muted)
        }
        if (i.configured) {
            Row(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        message ?: if (i.key in PHONE_SYNCABLE) "" else "Syncs on its own schedule.",
                        color = NeonMV.Muted, fontSize = 12.sp,
                    )
                }
                if (i.key in PHONE_SYNCABLE) {
                    Spacer(Modifier.width(10.dp))
                    NeonButton(if (syncing) "Syncing…" else "Sync now", onSync,
                        enabled = !syncing, filled = false, accent = NeonMV.Cyan)
                }
            }
        }
    }
}

/** Pill text + colour for the server's status. Amber, never rose. */
internal fun integrationPill(i: IntegrationHealth, problem: Boolean): Pair<String, Color> = when {
    !i.configured -> "Not connected" to NeonMV.Muted
    i.needsReconnect -> "Reconnect" to NeonMV.Amber
    i.status == "error" -> "Error" to NeonMV.Amber
    i.status == "stale" || problem -> "Stale" to NeonMV.Amber
    i.status == "never" -> "Never synced" to NeonMV.Amber
    else -> "Working" to NeonMV.Lime
}
