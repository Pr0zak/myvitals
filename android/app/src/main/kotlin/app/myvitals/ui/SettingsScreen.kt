package app.myvitals.ui

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
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

    Scaffold(topBar = { TopAppBar(title = { Text("myvitals") }) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Backend URL  (e.g. http://your-server:8000)") },
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

            Button(onClick = ::saveAndToast) { Text("Save") }

            Spacer(Modifier.height(8.dp))
            HorizontalDivider()

            Text(
                if (isHealthConnectAvailable) "Health Connect: available"
                else "Health Connect: NOT available — install/update via Play Store"
            )

            Button(
                onClick = onRequestPermissions,
                enabled = isHealthConnectAvailable,
            ) {
                Text(if (hasPermissions()) "Re-request permissions" else "Grant Health Connect permissions")
            }

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(
                    onClick = {
                        onSyncNow()
                        Toast.makeText(context, "Sync queued — see Logs for outcome", Toast.LENGTH_SHORT).show()
                    },
                    enabled = settings.isConfigured() && hasPermissions(),
                ) { Text("Sync now") }
                OutlinedButton(
                    onClick = {
                        onBackfill(7)
                        Toast.makeText(context, "Backfilling last 7 days…", Toast.LENGTH_SHORT).show()
                    },
                    enabled = settings.isConfigured() && hasPermissions(),
                ) { Text("Backfill 7d") }
                OutlinedButton(
                    onClick = {
                        onBackfill(30)
                        Toast.makeText(context, "Backfilling last 30 days…", Toast.LENGTH_LONG).show()
                    },
                    enabled = settings.isConfigured() && hasPermissions(),
                ) { Text("Backfill 30d") }
                OutlinedButton(
                    onClick = {
                        onClearBuffer()
                        Toast.makeText(context, "Sync buffer cleared", Toast.LENGTH_SHORT).show()
                    },
                ) { Text("Clear buffer") }
            }

            Text("Last sync: " + (settings.lastSyncInstant()?.let(::formatInstant) ?: "never"))

            Spacer(Modifier.height(8.dp))
            HorizontalDivider()

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(onClick = onOpenLogs) { Text("View logs") }
                OutlinedButton(
                    onClick = {
                        onSyncLogs()
                        Toast.makeText(context, "Log upload queued", Toast.LENGTH_SHORT).show()
                    },
                    enabled = settings.isConfigured(),
                ) { Text("Sync logs now") }
                OutlinedButton(onClick = {
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
                }) { Text("Check for updates") }
            }

            // Inline install button — appears when an update was found.
            pendingRelease?.let { release ->
                val asset = release.assets.firstOrNull { it.name.endsWith(".apk") }
                if (asset != null) {
                    Button(onClick = {
                        UpdateInstallerActivity.start(context, asset.browserDownloadUrl, asset.name)
                    }) {
                        Text("Install ${release.tagName}")
                    }
                }
            }

            Text(
                "Version ${BuildConfig.VERSION_NAME} (build ${BuildConfig.VERSION_CODE})",
                style = MaterialTheme.typography.bodySmall,
            )

            if (updateStatus.isNotBlank()) {
                Text(updateStatus, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

private val formatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneId.systemDefault())

private fun formatInstant(instant: Instant): String = formatter.format(instant)
