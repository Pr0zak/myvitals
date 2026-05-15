package app.myvitals.widget

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Single periodic worker that repaints every widget instance across
 * the family. Cadence: 15 min — below Android's 30-min
 * `updatePeriodMillis` floor for AppWidgetProvider, which is why we
 * schedule via WorkManager instead of the manifest-declared period.
 */
class WidgetsRefreshWorker(
    appContext: Context, params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        Widgets.refreshAll(applicationContext)
        return Result.success()
    }

    companion object {
        const val UNIQUE_NAME = "widgets_refresh"

        fun schedulePeriodicRefresh(context: Context) {
            val req = PeriodicWorkRequestBuilder<WidgetsRefreshWorker>(
                15, TimeUnit.MINUTES,
            ).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                UNIQUE_NAME, ExistingPeriodicWorkPolicy.KEEP, req,
            )
        }
    }
}
