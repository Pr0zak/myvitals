package app.myvitals.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.myvitals.data.SettingsRepository
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    settings: SettingsRepository,
    isHealthConnectAvailable: Boolean,
    hasPermissions: () -> Boolean,
    onRequestPermissions: () -> Unit,
    onSyncNow: () -> Unit,
) {
    var url by remember { mutableStateOf(settings.backendUrl) }
    var token by remember { mutableStateOf(settings.bearerToken) }

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
                label = { Text("Backend URL  (e.g. https://myvitals.example.com)") },
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

            Button(onClick = {
                settings.backendUrl = url
                settings.bearerToken = token
            }) { Text("Save") }

            Spacer(Modifier.height(8.dp))

            Text(
                if (isHealthConnectAvailable) "Health Connect: available"
                else "Health Connect: NOT available — install/update via Play Store"
            )

            Button(
                onClick = onRequestPermissions,
                enabled = isHealthConnectAvailable,
            ) { Text(if (hasPermissions()) "Re-request permissions" else "Grant Health Connect permissions") }

            Button(
                onClick = onSyncNow,
                enabled = settings.isConfigured() && hasPermissions(),
            ) { Text("Sync now") }

            Text("Last sync: " + (settings.lastSyncInstant()?.let(::formatInstant) ?: "never"))
        }
    }
}

private val formatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneId.systemDefault())

private fun formatInstant(instant: Instant): String = formatter.format(instant)
