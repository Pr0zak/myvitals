package app.myvitals

import android.app.Application
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.debug.LogUploadWorker
import app.myvitals.debug.RoomLogTree
import app.myvitals.strength.WorkoutReminderWorker
import app.myvitals.sync.SyncWorker
import app.myvitals.trails.TrailAlertWorker
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

        // Capture uncaught exceptions so crashes show up in the LogViewer
        // on next sync, rather than disappearing into logcat-only.
        val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            Timber.e(throwable, "UNCAUGHT in %s: %s",
                thread.name, throwable.message ?: throwable::class.simpleName ?: "?")
            // Block briefly so RoomLogTree's coroutine can flush the row
            // before the process dies.
            try { Thread.sleep(200) } catch (_: InterruptedException) {}
            previousHandler?.uncaughtException(thread, throwable)
        }

        Notifier.ensureChannel(this)
        WorkoutReminderWorker.ensureChannel(this)
        schedulePeriodicSync()
        scheduleUpdateCheck()
        scheduleLogUpload()
        scheduleTrailAlertPoll()
        scheduleWorkoutReminder()
    }

    private fun scheduleWorkoutReminder() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<WorkoutReminderWorker>(1, TimeUnit.HOURS)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            WorkoutReminderWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
    }

    private fun scheduleTrailAlertPoll() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<TrailAlertWorker>(30, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            TrailAlertWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            request,
        )
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

        // Tighter cadence so notifications about new builds don't lag a day.
        val periodic = PeriodicWorkRequestBuilder<UpdateCheckWorker>(6, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            UpdateCheckWorker.UNIQUE_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,  // pick up the new 6h period on upgrade
            periodic,
        )

        // One-shot on every app start so users get notified within seconds of
        // opening the app if a release dropped overnight.
        val oneShot = OneTimeWorkRequestBuilder<UpdateCheckWorker>()
            .setConstraints(constraints)
            .build()
        WorkManager.getInstance(this).enqueue(oneShot)
        Timber.d("Update check: 6h periodic + one-shot on launch")
    }
}
