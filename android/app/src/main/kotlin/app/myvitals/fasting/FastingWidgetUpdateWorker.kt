package app.myvitals.fasting

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

/**
 * Periodic worker that repaints every FastingWidgetProvider instance.
 * Scheduled by the provider's onEnabled (and a one-time enqueue on
 * app start). Cadence: 15 min — below the system updatePeriodMillis
 * floor for AppWidgetProvider (30 min), which is why we use
 * WorkManager instead of the manifest-declared period.
 */
class FastingWidgetUpdateWorker(
    appContext: Context, params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        FastingWidgetProvider.refreshAll(applicationContext)
        return Result.success()
    }
}
