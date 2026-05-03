package app.myvitals

import android.app.Application
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.debug.LogUploadWorker
import app.myvitals.debug.RoomLogTree
import app.myvitals.sync.SyncWorker
import app.myvitals.update.Notifier
import app.myvitals.update.UpdateCheckWorker
import timber.log.Timber
import java.util.concurrent.TimeUnit

class MyVitalsApp : Application() {
    override fun onCreate() {
        super.onCreate()

        // Plant logging trees before anything else so onCreate() failures show up.
        Timber.plant(Timber.DebugTree())          // → logcat
        Timber.plant(RoomLogTree(this))           // → Room "logs" table
        Timber.i("App start v=%s code=%d", BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)

        Notifier.ensureChannel(this)
        schedulePeriodicSync()
        scheduleUpdateCheck()
        scheduleLogUpload()
    }

    private fun scheduleLogUpload() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val request = PeriodicWorkRequestBuilder<LogUploadWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            LogUploadWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    private fun schedulePeriodicSync() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            SyncWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
        Timber.d("Periodic sync enqueued (15-min interval)")
    }

    private fun scheduleUpdateCheck() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val request = PeriodicWorkRequestBuilder<UpdateCheckWorker>(24, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            UpdateCheckWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }
}
