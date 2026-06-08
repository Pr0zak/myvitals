package app.myvitals.strength

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.myvitals.data.SettingsRepository
import app.myvitals.update.Notifier
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * WP-14 — handles the Resume / Complete action buttons on the "workout
 * paused" notification. Runs even when no Activity is in the foreground
 * (the user may have tapped Pause and switched away). The repository
 * calls buffer to Room on network failure, so an offline tap still
 * queues and replays on the next sync. The notification is always
 * cancelled afterwards so it can't linger in a stale "paused" state.
 */
class WorkoutActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        val workoutId = intent.getLongExtra("workout_id", -1L)
        if (workoutId < 0L) return
        val appCtx = context.applicationContext
        val pending = goAsync()
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val repo = StrengthRepository(appCtx, SettingsRepository(appCtx))
                when (action) {
                    Notifier.WORKOUT_RESUME -> repo.resumeWorkout(workoutId)
                    Notifier.WORKOUT_COMPLETE -> repo.completeWorkout(workoutId)
                    else -> Unit
                }
            } catch (e: Exception) {
                Timber.w(e, "workout action %s failed for %d", action, workoutId)
            } finally {
                Notifier.cancelWorkoutPaused(appCtx)
                pending.finish()
            }
        }
    }
}
