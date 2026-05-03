package app.myvitals

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.data.SettingsRepository
import app.myvitals.debug.LogViewerActivity
import app.myvitals.health.HealthConnectGateway
import app.myvitals.sync.SyncWorker
import app.myvitals.ui.SettingsScreen
import timber.log.Timber

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val settings = SettingsRepository(applicationContext)
        val gateway = HealthConnectGateway(applicationContext)

        val permissionLauncher = registerForActivityResult(
            gateway.permissionContract()
        ) { granted ->
            Timber.i("HC permissions returned; granted=%d/%d", granted.size, gateway.requiredPermissions.size)
        }

        setContent {
            MaterialTheme {
                SettingsScreen(
                    settings = settings,
                    isHealthConnectAvailable = gateway.isAvailable(),
                    hasPermissions = { gateway.hasAllPermissions() },
                    onRequestPermissions = {
                        Timber.d("Requesting HC permissions: %s", gateway.requiredPermissions)
                        permissionLauncher.launch(gateway.requiredPermissions)
                    },
                    onSyncNow = {
                        Timber.i("Manual sync triggered")
                        WorkManager.getInstance(applicationContext)
                            .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
                    },
                    onOpenLogs = { LogViewerActivity.start(this) },
                )
            }
        }
    }
}
