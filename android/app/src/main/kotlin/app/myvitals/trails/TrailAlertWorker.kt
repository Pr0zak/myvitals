package app.myvitals.trails

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.MarkNotifiedBody
import app.myvitals.update.Notifier
import timber.log.Timber

/**
 * Poll the backend for unnotified trail alerts. For each row, post a
 * system notification on the `trail_status` channel and POST back the
 * id to mark it phone_notified so we don't re-notify next tick.
 *
 * Cadence: every 30 min via WorkManager. Backend itself polls
 * RainoutLine every 15 min, so worst-case latency for a status flip
 * to reach the phone is ~45 min. Good enough for trail status.
 */
class TrailAlertWorker(
    appContext: Context, params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val settings = SettingsRepository(applicationContext)
        if (!settings.isConfigured()) return Result.success()
        return try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val unacked = api.trailAlerts(unackedOnly = true)
            val unnotified = unacked.filter { it.phoneNotifiedAt == null }
            if (unnotified.isEmpty()) {
                return Result.success()
            }
            for (a in unnotified) {
                Notifier.postTrailAlert(
                    context = applicationContext,
                    alertId = a.id,
                    trailName = a.trailName ?: "Trail #${a.trailId}",
                    fromStatus = a.fromStatus,
                    toStatus = a.toStatus,
                )
            }
            api.markTrailAlertsNotified(MarkNotifiedBody(unnotified.map { it.id }))
            Timber.i("Posted %d trail alerts", unnotified.size)
            Result.success()
        } catch (e: Exception) {
            Timber.w(e, "TrailAlertWorker failed")
            Result.retry()
        }
    }

    companion object {
        const val UNIQUE_NAME = "TrailAlertWorker"
    }
}
