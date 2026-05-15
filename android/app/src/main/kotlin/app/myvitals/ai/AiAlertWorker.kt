package app.myvitals.ai

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.update.Notifier
import timber.log.Timber

/**
 * Poll the backend for unacked AI alerts (anomalies, goal milestones,
 * streak events). For each row whose `phone_notified_at` is null,
 * post a system notification on the `ai_alerts` channel and POST back
 * the ids so we don't re-notify on the next tick.
 *
 * Independent worker (not driven from SyncWorker) for the same reason
 * TrailAlertWorker is — keeps SyncWorker single-purpose and lets the
 * cadence be tuned independently. Scheduled every ~30 min by
 * MainActivity (next to TrailAlertWorker's schedule).
 */
class AiAlertWorker(
    appContext: Context, params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val settings = SettingsRepository(applicationContext)
        if (!settings.isConfigured()) return Result.success()
        return try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val unacked = api.aiAlerts(unackedOnly = true, limit = 20)
            val unnotified = unacked.filter { it.phoneNotifiedAt == null }
            if (unnotified.isEmpty()) return Result.success()

            for (a in unnotified) {
                Notifier.postAiAlert(
                    context = applicationContext,
                    alertId = a.id,
                    severity = a.severity,
                    title = a.title,
                    body = a.body,
                    backendBaseUrl = settings.backendUrl,
                )
            }
            api.markAiAlertsNotified(unnotified.map { it.id })
            Timber.i("Posted %d AI alerts", unnotified.size)
            Result.success()
        } catch (e: Exception) {
            Timber.w(e, "AiAlertWorker failed")
            Result.retry()
        }
    }

    companion object {
        const val UNIQUE_NAME = "AiAlertWorker"
    }
}
