package app.myvitals

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.data.SettingsRepository
import app.myvitals.health.HealthConnectGateway
import app.myvitals.sync.SyncWorker
import app.myvitals.ui.SettingsScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val settings = SettingsRepository(applicationContext)
        val gateway = HealthConnectGateway(applicationContext)

        val permissionLauncher = registerForActivityResult(
            gateway.permissionContract()
        ) { /* HC delivers granted set; UI re-checks via gateway.hasAllPermissions() */ }

        setContent {
            MaterialTheme {
                SettingsScreen(
                    settings = settings,
                    isHealthConnectAvailable = gateway.isAvailable(),
                    hasPermissions = { gateway.hasAllPermissions() },
                    onRequestPermissions = {
                        // Health Connect's contract takes the Set<String> directly.
                        permissionLauncher.launch(gateway.requiredPermissions)
                    },
                    onSyncNow = {
                        WorkManager.getInstance(applicationContext)
                            .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
                    },
                )
            }
        }
    }
}
