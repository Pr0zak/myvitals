package app.myvitals

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import app.myvitals.ui.MyVitalsTheme
import androidx.core.content.ContextCompat
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.data.SettingsRepository
import app.myvitals.debug.LogUploadWorker
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

        // Android 13+ requires runtime permission to post notifications.
        // Request once at app start; user can deny and the app still works.
        val notifLauncher = registerForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { granted -> Timber.i("POST_NOTIFICATIONS granted=%b", granted) }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val state = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            )
            if (state != PackageManager.PERMISSION_GRANTED) {
                Timber.d("Asking for POST_NOTIFICATIONS")
                notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        setContent {
            MyVitalsTheme {
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
                    onSyncLogs = {
                        Timber.i("Manual log upload triggered")
                        WorkManager.getInstance(applicationContext)
                            .enqueue(OneTimeWorkRequestBuilder<LogUploadWorker>().build())
                    },
                    onBackfill = { days ->
                        val newCheckpoint = System.currentTimeMillis() / 1000 - days * 24L * 3600L
                        settings.lastSyncEpochSeconds = newCheckpoint
                        Timber.i("Backfill: reset checkpoint to T-%dd (epoch=%d), enqueueing sync", days, newCheckpoint)
                        WorkManager.getInstance(applicationContext)
                            .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
                    },
                    onOpenLogs = { LogViewerActivity.start(this) },
                )
            }
        }
    }
}
