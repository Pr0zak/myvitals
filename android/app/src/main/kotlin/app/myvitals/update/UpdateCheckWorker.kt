package app.myvitals.update

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class UpdateCheckWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val release = UpdateChecker.checkForUpdate() ?: return Result.success()
        Notifier.postUpdateAvailable(applicationContext, release)
        return Result.success()
    }

    companion object {
        const val UNIQUE_NAME = "myvitals_update_check"
    }
}
