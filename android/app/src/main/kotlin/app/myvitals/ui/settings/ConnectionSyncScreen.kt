package app.myvitals.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.DeleteSweep
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.CloudUpload
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.work.WorkInfo
import androidx.work.WorkManager
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.DataHealth
import app.myvitals.sync.SyncWorker
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant

/** Where the manual sync chain is, observed from WorkManager (UX-P8). */
enum class SyncPhase { IDLE, QUEUED, RUNNING, RETRYING, SUCCEEDED, FAILED }

/** Collapse the unique chain's WorkInfos into one phase. */
fun syncPhaseOf(infos: List<WorkInfo>): SyncPhase {
    if (infos.isEmpty()) return SyncPhase.IDLE
    if (infos.any { it.state == WorkInfo.State.RUNNING }) return SyncPhase.RUNNING
    infos.firstOrNull { it.state == WorkInfo.State.ENQUEUED || it.state == WorkInfo.State.BLOCKED }
        ?.let { return if (it.runAttemptCount > 0) SyncPhase.RETRYING else SyncPhase.QUEUED }
    return when (infos.last().state) {
        WorkInfo.State.SUCCEEDED -> SyncPhase.SUCCEEDED
        WorkInfo.State.FAILED -> SyncPhase.FAILED
        else -> SyncPhase.IDLE
    }
}

/** Phone-side facts the page shows; all read from SettingsRepository. */
data class PhoneSyncFacts(
    val hcAvailable: Boolean,
    val permsGranted: Boolean,
    val permissionsLost: Boolean,
    val lastAttempt: Instant?,
    val lastSuccess: Instant?,
)

/**
 * Connection & sync (SETTINGS-C). Mirrors web `settings/SettingsConnection.vue`.
 *
 *   connection   "Server address" and "Access key" in plain words, the key
 *                masked with a reveal toggle (it used to sit on screen in
 *                plain text)
 *   phone        Health Connect status + grant, the last sync, Sync now
 *                with LIVE state from WorkManager instead of a blind
 *                "Sync queued" toast, and backfill — the ten-year one asks
 *                first
 *   data health  the full per-stream card (HEALTH-1)
 *   diagnostics  on-device logs, upload, clear the buffer (asks first)
 */
@Composable
fun ConnectionSyncScreen(
    settings: SettingsRepository,
    isHealthConnectAvailable: Boolean,
    hasPermissions: suspend () -> Boolean,
    onRequestPermissions: () -> Unit,
    onSyncNow: () -> Unit,
    onSyncLogs: () -> Unit,
    onBackfill: (Int) -> Unit,
    onOpenLogs: () -> Unit,
    onClearBuffer: () -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(settings.backendUrl) }
    var token by remember { mutableStateOf(settings.bearerToken) }
    var savedNote by remember { mutableStateOf<String?>(null) }
    var health by remember { mutableStateOf<DataHealth?>(null) }
    var healthLoading by remember { mutableStateOf(true) }
    var healthError by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }

    app.myvitals.ui.common.LifecycleResumeEffect(staleAfterMs = 0L) { tick++ }
    val permsGranted by produceState(false, isHealthConnectAvailable, tick) { value = hasPermissions() }
    val infos by remember(context) {
        WorkManager.getInstance(context).getWorkInfosForUniqueWorkFlow(SyncWorker.MANUAL_UNIQUE_NAME)
    }.collectAsState(initial = emptyList())
    val phase = syncPhaseOf(infos)

    suspend fun loadHealth() {
        try {
            health = settings.call { dataHealth() }
            healthError = null
        } catch (e: Exception) {
            Timber.w(e, "data health load failed")
            healthError = e.settingsMessage()
        } finally {
            healthLoading = false
        }
    }
    LaunchedEffect(Unit) { loadHealth() }
    // A finished sync changes both the phone facts and the server's view.
    LaunchedEffect(phase) {
        tick++
        if (phase == SyncPhase.SUCCEEDED) loadHealth()
    }

    // Re-read the phone facts whenever something may have moved them.
    val facts = remember(tick, permsGranted) {
        PhoneSyncFacts(
            hcAvailable = isHealthConnectAvailable,
            permsGranted = permsGranted,
            permissionsLost = settings.permissionsLost,
            lastAttempt = settings.lastSyncInstant(),
            lastSuccess = settings.lastSuccessInstant(),
        )
    }

    ConnectionSyncContent(
        url = url, token = token,
        connDirty = url.trim() != settings.backendUrl || token.trim() != settings.bearerToken,
        savedNote = savedNote,
        onUrl = { url = it; savedNote = null },
        onToken = { token = it; savedNote = null },
        onSaveConnection = {
            settings.backendUrl = url.trim()
            settings.bearerToken = token.trim()
            url = settings.backendUrl; token = settings.bearerToken
            savedNote = if (settings.isConfigured()) "Saved. Checking the server…"
            else "Saved, but both the address and the key are needed."
            if (settings.isConfigured()) scope.launch {
                healthLoading = true
                loadHealth()
                savedNote = if (healthError == null) "Saved — the server answered." else "Saved, but the server didn't answer."
            }
        },
        facts = facts,
        phase = phase,
        configured = settings.isConfigured(),
        onGrant = onRequestPermissions,
        onOpenHealthConnect = { openHealthConnectSettings(context) },
        onSyncNow = onSyncNow,
        onBackfill = onBackfill,
        health = health, healthLoading = healthLoading, healthError = healthError,
        onOpenLogs = onOpenLogs,
        onUploadLogs = {
            onSyncLogs()
            android.widget.Toast.makeText(context, "Uploading logs to the server", android.widget.Toast.LENGTH_SHORT).show()
        },
        onClearBuffer = {
            onClearBuffer()
            android.widget.Toast.makeText(context, "Sync buffer cleared", android.widget.Toast.LENGTH_SHORT).show()
        },
        now = Instant.now(),
        refreshing = refreshing,
        onRefresh = { scope.launch { refreshing = true; tick++; try { loadHealth() } finally { refreshing = false } } },
        onBack = onBack,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ConnectionSyncContent(
    url: String,
    token: String,
    connDirty: Boolean,
    savedNote: String?,
    onUrl: (String) -> Unit,
    onToken: (String) -> Unit,
    onSaveConnection: () -> Unit,
    facts: PhoneSyncFacts,
    phase: SyncPhase,
    configured: Boolean,
    onGrant: () -> Unit,
    onOpenHealthConnect: () -> Unit,
    onSyncNow: () -> Unit,
    onBackfill: (Int) -> Unit,
    health: DataHealth?,
    healthLoading: Boolean,
    healthError: String?,
    onOpenLogs: () -> Unit,
    onUploadLogs: () -> Unit,
    onClearBuffer: () -> Unit,
    now: Instant,
    refreshing: Boolean,
    onRefresh: () -> Unit,
    onBack: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    var confirmBackfill by remember { mutableStateOf<Int?>(null) }
    var confirmClear by remember { mutableStateOf(false) }
    confirmBackfill?.let { days ->
        SettingsConfirm(
            title = if (days >= 3650) "Re-read ten years?" else "Re-read a year?",
            text = "The phone reads everything Health Connect holds for that period and sends it " +
                "to the server. This can take a long time and use a lot of battery and data. " +
                "Readings already on the server are not duplicated.",
            confirmLabel = "Start backfill",
            onConfirm = { onBackfill(days) },
            onDismiss = { confirmBackfill = null },
        )
    }
    if (confirmClear) {
        SettingsConfirm(
            title = "Clear the sync buffer?",
            text = "Discards every set log, workout change and log line waiting on this phone to " +
                "be sent. Only use this if the buffer is stuck and you accept losing them.",
            confirmLabel = "Clear buffer",
            onConfirm = onClearBuffer,
            onDismiss = { confirmClear = false },
        )
    }

    NeonScreen(
        title = "Connection & sync",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        NeonEyebrow("Server")
        SettingsCard {
            SettingsTextField(
                "Server address", url, onUrl,
                placeholder = "https://vitals.example.com",
                keyboardType = KeyboardType.Uri,
                help = "The web address of your myvitals server — the same one you open the dashboard at.",
            )
            SettingsTextField(
                "Access key", token, onToken,
                secret = true, secretName = "access key", mono = true,
                help = "The server's ingest token. It lets this phone send readings and read your data.",
            )
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    savedNote ?: if (connDirty) "Unsaved changes" else if (configured) "Saved on this phone" else "Not set up yet",
                    color = if (connDirty) NeonMV.Amber else NeonMV.Muted, fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                NeonButton("Save", onSaveConnection, enabled = connDirty)
            }
        }

        NeonEyebrow("This phone")
        if (facts.permissionsLost) {
            NeonErrorBanner(
                "The app has every permission, but Health Connect itself is blocking reads. Open " +
                    "Health Connect, tap myvitals, and turn each permission off and back on.",
                title = "Health Connect is denying reads",
                actionLabel = "Open Health Connect",
                onRetry = onOpenHealthConnect,
            )
        }
        SettingsCard {
            val hc = when {
                !facts.hcAvailable -> "Not available — install or update it from the Play Store" to NeonMV.Amber
                !facts.permsGranted -> "Permissions missing — nothing new can be read" to NeonMV.Amber
                facts.permissionsLost -> "Denying reads" to NeonMV.Amber
                else -> "All permissions granted" to NeonMV.Lime
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                StatusDot(hc.second)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text("Health Connect", color = NeonMV.Ink, fontSize = 15.sp)
                    Text(hc.first, color = if (hc.second == NeonMV.Lime) NeonMV.Muted else NeonMV.Amber, fontSize = 12.sp)
                }
                NeonButton(
                    if (facts.permsGranted) "Manage" else "Grant", onGrant,
                    filled = !facts.permsGranted, enabled = facts.hcAvailable, accent = NeonMV.Cyan,
                )
            }
            SettingsDivider()
            SettingsKv("Last sync attempt", relAge(facts.lastAttempt, now))
            SettingsKv(
                "Last successful sync", relAge(facts.lastSuccess, now),
                valueColor = if (facts.permissionsLost) NeonMV.Amber else NeonMV.Muted,
            )
            SettingsDivider()
            val (label, color) = phaseLabel(phase)
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Sync now", color = NeonMV.Ink, fontSize = 15.sp)
                    Text(label, color = color, fontSize = 12.sp)
                }
                val busy = phase == SyncPhase.QUEUED || phase == SyncPhase.RUNNING
                NeonButton(
                    if (busy) "Syncing…" else "Sync now", onSyncNow,
                    enabled = configured && facts.permsGranted && !busy,
                )
            }
            SettingsDivider()
            Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text("Backfill history", color = NeonMV.Ink, fontSize = 15.sp)
                Text("Re-read older data from Health Connect.", color = NeonMV.Muted, fontSize = 12.sp)
                Spacer(Modifier.height(10.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    val enabled = configured && facts.permsGranted
                    NeonChip("7 days", false, enabled = enabled) { onBackfill(7) }
                    NeonChip("30 days", false, enabled = enabled) { onBackfill(30) }
                    NeonChip("1 year", false, enabled = enabled) { confirmBackfill = 365 }
                    NeonChip("All (10 years)", false, enabled = enabled) { confirmBackfill = 3650 }
                }
            }
        }

        NeonEyebrow("Data health")
        when {
            health != null -> {
                if (healthError != null) {
                    NeonErrorBanner(healthError, title = "Couldn't refresh — showing the last check") { onRefresh() }
                }
                DataHealthCard(health)
            }
            healthError != null && !healthLoading ->
                NeonErrorBanner(healthError, title = "Couldn't check data health") { onRefresh() }
            else -> SettingsSkeleton(listOf(220.dp))
        }

        NeonEyebrow("Diagnostics")
        SettingsCard {
            SettingsNavRow(Icons.Outlined.Description, NeonMV.Periwinkle, "On-device logs",
                "What the app has been doing, newest first", onClick = onOpenLogs)
            SettingsDivider()
            SettingsNavRow(Icons.Outlined.CloudUpload, NeonMV.Periwinkle, "Upload logs",
                "Send them to the server for troubleshooting", onClick = onUploadLogs)
            SettingsDivider()
            SettingsNavRow(Icons.Outlined.DeleteSweep, NeonMV.Amber, "Clear sync buffer",
                "Discard writes waiting to be sent — asks first", onClick = { confirmClear = true })
        }
        Spacer(Modifier.height(24.dp))
    }
}

private fun phaseLabel(phase: SyncPhase): Pair<String, Color> = when (phase) {
    SyncPhase.IDLE -> "Reads Health Connect and sends anything new." to NeonMV.Muted
    SyncPhase.QUEUED -> "Waiting to start…" to NeonMV.Cyan
    SyncPhase.RUNNING -> "Syncing now…" to NeonMV.Cyan
    SyncPhase.RETRYING -> "The last attempt failed — trying again shortly." to NeonMV.Amber
    SyncPhase.SUCCEEDED -> "Last manual sync finished." to NeonMV.Lime
    SyncPhase.FAILED -> "The last manual sync failed — see the logs." to NeonMV.Amber
}

/**
 * HEALTH-1 — renders only; every status is decided on the server so this
 * and the web card cannot drift. Most streams are SUPPOSED to be quiet
 * (a weigh-in, a blood-pressure reading) and render neutral; only a stream
 * meant to be continuous can show as needing attention. Amber, never rose.
 */
@Composable
fun DataHealthCard(dh: DataHealth) {
    fun tone(status: String): Color = when (status) {
        "ok" -> NeonMV.Lime
        "stale", "error", "never" -> NeonMV.Amber
        else -> NeonMV.Muted          // ad_hoc, not_configured — not faults
    }
    SettingsCard {
        Column(Modifier.padding(16.dp)) {
            Text(
                dh.overview?.headline
                    ?: if (dh.ok) "Everything that should be arriving is arriving."
                    else "${dh.problemKeys.size} need attention.",
                // The server's tone when it sends one; never re-derived here.
                color = dh.overview?.let { toneColor(it.tone) }
                    ?: if (dh.ok) NeonMV.Lime else NeonMV.Amber,
                fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(10.dp))
            for (s in dh.streams) {
                Row(Modifier.fillMaxWidth().padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    StatusDot(tone(s.status))
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(s.label, color = NeonMV.Ink, fontSize = 13.sp)
                        if (s.source.isNotBlank()) {
                            Text(
                                if (s.canonicalSourceOnly) "${s.source} · main source only" else s.source,
                                color = NeonMV.Muted, fontSize = 10.sp,
                            )
                        }
                    }
                    Text(
                        if (s.status == "not_configured" && s.lastAt == null) "not set up"
                        else fmtAgeHours(s.ageHours),
                        color = if (s.status == "stale") NeonMV.Amber else NeonMV.Muted, fontSize = 12.sp,
                    )
                }
            }
            if (dh.integrations.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                Text("INTEGRATIONS", color = NeonMV.Muted, fontSize = 10.sp,
                    fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
                for (i in dh.integrations) {
                    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        StatusDot(if (i.configured) tone(i.status) else NeonMV.Muted)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(i.label, color = NeonMV.Ink, fontSize = 13.sp)
                            i.lastError?.let { Text(it.take(120), color = NeonMV.Amber, fontSize = 10.sp) }
                            i.action?.let {
                                Text(it, color = if (i.needsReconnect) NeonMV.Amber else NeonMV.Muted,
                                    fontSize = 10.sp,
                                    fontWeight = if (i.needsReconnect) FontWeight.SemiBold else FontWeight.Normal)
                            }
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(if (i.configured) fmtAgeHours(i.ageHours) else "not connected",
                                color = NeonMV.Muted, fontSize = 12.sp)
                            if (i.importingNothing) {
                                Text("last import ${fmtAgeHours(i.itemAgeHours)}",
                                    color = NeonMV.Muted, fontSize = 10.sp)
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "Grey rows are recorded when you choose to, not on a schedule, so an old " +
                    "reading there is not a fault.",
                color = NeonMV.Muted, fontSize = 10.sp,
            )
        }
    }
}
