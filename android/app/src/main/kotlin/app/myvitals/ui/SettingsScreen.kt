package app.myvitals.ui

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.size
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.BuildConfig
import app.myvitals.data.SettingsRepository
import app.myvitals.update.GitHubRelease
import app.myvitals.update.UpdateChecker
import app.myvitals.update.UpdateInstallerActivity
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(
    settings: SettingsRepository,
    isHealthConnectAvailable: Boolean,
    hasPermissions: () -> Boolean,
    onRequestPermissions: () -> Unit,
    onSyncNow: () -> Unit,
    onSyncLogs: () -> Unit,
    onBackfill: (days: Int) -> Unit,
    onOpenLogs: () -> Unit,
    onClearBuffer: () -> Unit,
) {
    var url by remember { mutableStateOf(settings.backendUrl) }
    var token by remember { mutableStateOf(settings.bearerToken) }
    var updateStatus by remember { mutableStateOf("") }
    var pendingRelease by remember { mutableStateOf<GitHubRelease?>(null) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    fun saveAndToast() {
        settings.backendUrl = url.trim()
        settings.bearerToken = token.trim()
        Toast.makeText(
            context,
            if (settings.isConfigured()) "Saved — backend configured" else "Saved (URL and/or token blank)",
            Toast.LENGTH_SHORT,
        ).show()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "Settings",
                        style = MaterialTheme.typography.titleLarge,
                    )
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(
                start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp,
            ),
        ) {
            // ────────── Connection ──────────
            item { SectionHeader("Connection") }
            item {
                SectionCard {
                    OutlinedTextField(
                        value = url,
                        onValueChange = { url = it },
                        label = { Text("Backend URL") },
                        placeholder = { Text("http://your-server:8000") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    OutlinedTextField(
                        value = token,
                        onValueChange = { token = it },
                        label = { Text("Ingest bearer token") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                    )
                    Button(
                        onClick = ::saveAndToast,
                        modifier = Modifier.align(Alignment.End),
                    ) { Text("Save") }
                }
            }

            // ────────── Health Connect ──────────
            item { SectionHeader("Health Connect") }
            item {
                SectionCard {
                    StatusRow(
                        title = "Health Connect",
                        ok = isHealthConnectAvailable,
                        okText = "Available on this device",
                        notOkText = "Not available — install/update via Play Store",
                    )
                    val perms = hasPermissions()
                    StatusRow(
                        title = "Read permissions",
                        ok = perms,
                        okText = "All required permissions granted",
                        notOkText = "Missing — tap below to grant",
                    )
                    Button(
                        onClick = onRequestPermissions,
                        enabled = isHealthConnectAvailable,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (perms) "Re-request permissions" else "Grant Health Connect permissions")
                    }
                }
            }

            // ────────── Sync ──────────
            item { SectionHeader("Sync") }
            item {
                SectionCard {
                    KeyValueRow(
                        label = "Last sync",
                        value = settings.lastSyncInstant()?.let(::formatInstant) ?: "never",
                    )
                    KeyValueRow(
                        label = "Last success",
                        value = settings.lastSuccessInstant()?.let(::formatInstant) ?: "never",
                    )
                    Button(
                        onClick = {
                            onSyncNow()
                            Toast.makeText(context, "Sync queued", Toast.LENGTH_SHORT).show()
                        },
                        enabled = settings.isConfigured() && hasPermissions(),
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Sync now") }

                    Text(
                        "Backfill",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        BackfillChip("7 days") { onBackfill(7); toast(context, "Backfilling 7 days…") }
                        BackfillChip("30 days") { onBackfill(30); toast(context, "Backfilling 30 days…") }
                        BackfillChip("1 year")  { onBackfill(365); toast(context, "Backfilling 1 year…") }
                        BackfillChip("All (10y)") { onBackfill(3650); toast(context, "Backfilling ALL — may take a while") }
                    }
                }
            }

            // ────────── Diagnostics ──────────
            item { SectionHeader("Diagnostics") }
            item {
                SectionCard {
                    OutlinedButton(
                        onClick = onOpenLogs,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("View on-device logs") }
                    OutlinedButton(
                        onClick = {
                            onSyncLogs()
                            Toast.makeText(context, "Log upload queued", Toast.LENGTH_SHORT).show()
                        },
                        enabled = settings.isConfigured(),
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Upload logs to backend") }
                    OutlinedButton(
                        onClick = {
                            onClearBuffer()
                            Toast.makeText(context, "Sync buffer cleared", Toast.LENGTH_SHORT).show()
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Clear sync buffer") }
                }
            }

            // ────────── About ──────────
            item { SectionHeader("About") }
            item {
                SectionCard {
                    KeyValueRow(
                        label = "Version",
                        value = "${BuildConfig.VERSION_NAME} (build ${BuildConfig.VERSION_CODE})",
                    )
                    OutlinedButton(
                        onClick = {
                            updateStatus = "Checking…"
                            pendingRelease = null
                            scope.launch {
                                val release = UpdateChecker.checkForUpdate()
                                if (release == null) {
                                    updateStatus = "Up to date."
                                } else {
                                    pendingRelease = release
                                    updateStatus = "Update ${release.tagName} available."
                                }
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Check for updates") }

                    pendingRelease?.let { release ->
                        val asset = release.assets.firstOrNull { it.name.endsWith(".apk") }
                        if (asset != null) {
                            Button(
                                onClick = {
                                    UpdateInstallerActivity.start(
                                        context, asset.browserDownloadUrl, asset.name,
                                    )
                                },
                                modifier = Modifier.fillMaxWidth(),
                            ) { Text("Install ${release.tagName}") }
                        }
                    }

                    if (updateStatus.isNotBlank()) {
                        Text(
                            updateStatus,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

// ─── Building blocks ────────────────────────────────────────

@Composable
private fun SectionHeader(text: String) {
    Text(
        text = text.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.primary,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.sp,
        modifier = Modifier.padding(start = 8.dp, top = 12.dp, bottom = 4.dp),
    )
}

@Composable
private fun SectionCard(content: @Composable ColumnScope.() -> Unit) {
    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            content = content,
        )
    }
}

@Composable
private fun KeyValueRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun StatusRow(title: String, ok: Boolean, okText: String, notOkText: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .clip(RoundedCornerShape(50))
                .background(if (ok) Color(0xFF22C55E) else Color(0xFFEF4444)),
        )
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
            )
            Text(
                text = if (ok) okText else notOkText,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun BackfillChip(label: String, onClick: () -> Unit) {
    AssistChip(
        onClick = onClick,
        label = { Text(label) },
        colors = AssistChipDefaults.assistChipColors(),
    )
}

private fun toast(ctx: android.content.Context, msg: String) {
    Toast.makeText(ctx, msg, Toast.LENGTH_SHORT).show()
}

private val formatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("yyyy-MM-dd h:mm:ss a").withZone(ZoneId.systemDefault())

private fun formatInstant(instant: Instant): String = formatter.format(instant)
