package app.myvitals.fasting

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import app.myvitals.update.Notifier
import java.util.concurrent.TimeUnit

/**
 * One-shot worker that fires a "you hit X stage" notification when the
 * fast crosses each preset milestone. Scheduled once per stage at
 * fastingStart, cancelled wholesale at fastingEnd.
 *
 * Lives in its own package because the Notifier import + WorkManager
 * scheduling are tightly coupled; the FastingScreen calls
 * `FastingMilestoneWorker.schedule(...)` after a successful start.
 */
class FastingMilestoneWorker(
    appContext: Context, params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val sessionId = inputData.getLong(KEY_SESSION_ID, 0L)
        val stageLabel = inputData.getString(KEY_STAGE_LABEL) ?: "Milestone"
        val elapsedH = inputData.getDouble(KEY_ELAPSED_H, 0.0)
        val targetH = inputData.getDouble(KEY_TARGET_H, 0.0)
        Notifier.postFastingMilestone(
            applicationContext, sessionId, stageLabel, elapsedH, targetH,
        )
        return Result.success()
    }

    companion object {
        const val KEY_SESSION_ID = "session_id"
        const val KEY_STAGE_LABEL = "stage_label"
        const val KEY_ELAPSED_H = "elapsed_h"
        const val KEY_TARGET_H = "target_h"
        const val UNIQUE_PREFIX = "fasting_milestone_"

        /** Stage milestones to alert on, in hours. Mirrors backend
         *  FASTING_STAGES but only fires for the ones a user wants
         *  prominent — gut_rest is too noisy at 4h. */
        private val MILESTONES_H: List<Pair<Double, String>> = listOf(
            12.0 to "Glycogen depleting",
            16.0 to "Ketosis",
            18.0 to "Autophagy",
            24.0 to "Deep autophagy",
            36.0 to "36h territory",
            48.0 to "48h territory",
            72.0 to "72h territory",
        )

        /** Schedule a milestone worker for each stage > elapsed_h, capped
         *  at the fast's target. The user can cancel mid-fast via
         *  cancelAll(sessionId); fast end calls cancelAll regardless. */
        fun schedule(
            context: Context, sessionId: Long,
            startEpochMs: Long, targetH: Double,
        ) {
            val wm = WorkManager.getInstance(context)
            for ((hours, label) in MILESTONES_H) {
                if (hours >= targetH + 0.0001) continue
                val fireAtMs = startEpochMs + (hours * 3_600_000L).toLong()
                val delayMs = fireAtMs - System.currentTimeMillis()
                if (delayMs <= 0L) continue
                val req = OneTimeWorkRequestBuilder<FastingMilestoneWorker>()
                    .setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
                    .setInputData(workDataOf(
                        KEY_SESSION_ID to sessionId,
                        KEY_STAGE_LABEL to label,
                        KEY_ELAPSED_H to hours,
                        KEY_TARGET_H to targetH,
                    ))
                    .build()
                val name = "$UNIQUE_PREFIX${sessionId}_${hours.toInt()}"
                wm.enqueueUniqueWork(name, ExistingWorkPolicy.REPLACE, req)
            }
        }

        /** Cancel every pending milestone for this session id. */
        fun cancelAll(context: Context, sessionId: Long) {
            val wm = WorkManager.getInstance(context)
            for ((hours, _) in MILESTONES_H) {
                wm.cancelUniqueWork("$UNIQUE_PREFIX${sessionId}_${hours.toInt()}")
            }
        }
    }
}

// Helper because androidx.work.Data doesn't ship a getDouble overload.
private fun Data.getDouble(key: String, default: Double): Double {
    val v = keyValueMap[key]
    return when (v) {
        is Double -> v
        is Float -> v.toDouble()
        is Long -> v.toDouble()
        is Int -> v.toDouble()
        is String -> v.toDoubleOrNull() ?: default
        else -> default
    }
}
