package app.myvitals.strength

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.myvitals.MainActivity
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import timber.log.Timber
import java.time.LocalDate
import java.time.ZoneId

/**
 * Once per workout day, post a reminder notification with the split focus
 * + first 3 exercises. Reads `profile.extra.workout_reminder_enabled`
 * and `workout_reminder_hour` (0–23, local time). Schedule cadence is
 * hourly; worker no-ops outside the user's chosen hour and dedupes
 * within a day via SharedPreferences.
 */
class WorkoutReminderWorker(
    appContext: Context, params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val settings = SettingsRepository(applicationContext)
        if (!settings.isConfigured()) return Result.success()

        return try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val profile = api.profile()
            val enabled = profile.extra?.workoutReminderEnabled == true
            if (!enabled) return Result.success()

            val targetHour = (profile.extra?.workoutReminderHour ?: 8).coerceIn(0, 23)
            val now = java.time.LocalDateTime.now(ZoneId.systemDefault())
            // Fire at the first hourly check at or AFTER the target hour
            // (was: exact-hour match — too brittle since WorkManager
            // periodic jobs drift, and a missed 8 AM window meant no
            // notification at all that day).
            if (now.hour < targetHour) return Result.success()

            val today = LocalDate.now(ZoneId.systemDefault()).toString()
            val prefs = applicationContext.getSharedPreferences(
                "workout_reminder", Context.MODE_PRIVATE,
            )
            if (prefs.getString("last_posted_date", null) == today) {
                return Result.success()
            }

            val resp = api.strengthToday()
            if (!resp.isSuccessful) return Result.success()
            val plan = resp.body() ?: return Result.success()
            if (plan.status == "skipped" || plan.status == "completed") {
                return Result.success()
            }

            val split = plan.splitFocus.replace('_', ' ')
                .replaceFirstChar(Char::titlecase)
            val sets = plan.exercises.flatMap { it.sets }.size
            val firstThree = plan.exercises.take(3).joinToString("\n") { wex ->
                val name = wex.exerciseId.replace('_', ' ')
                    .replaceFirstChar(Char::titlecase)
                "• $name — ${wex.targetSets}×${wex.targetRepsLow}-${wex.targetRepsHigh}"
            }
            val title = "$split workout today"
            val body = "$sets sets · ${plan.exercises.size} exercises\n$firstThree"

            ensureChannel(applicationContext)
            val intent = Intent(applicationContext, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pi = PendingIntent.getActivity(
                applicationContext, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val notif = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_menu_today)
                .setContentTitle(title)
                .setContentText("$sets sets · ${plan.exercises.size} exercises")
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(pi)
                .setAutoCancel(true)
                .build()
            try {
                NotificationManagerCompat.from(applicationContext).notify(NOTIF_ID, notif)
                prefs.edit().putString("last_posted_date", today).apply()
                Timber.i("Posted workout reminder: %s (%d ex)", split, plan.exercises.size)
            } catch (_: SecurityException) { /* notification permission revoked */ }

            Result.success()
        } catch (e: java.net.SocketTimeoutException) {
            // Backend unreachable (off-Tailscale, cellular without VPN,
            // CT down). Don't retry-storm; let the next hourly fire try
            // again — by then we may be back on Wi-Fi / Tailscale.
            Timber.i("WorkoutReminderWorker: backend unreachable, will try next hour")
            Result.success()
        } catch (e: java.net.UnknownHostException) {
            Timber.i("WorkoutReminderWorker: DNS / no network, will try next hour")
            Result.success()
        } catch (e: Exception) {
            Timber.w(e, "WorkoutReminderWorker failed")
            Result.retry()
        }
    }

    companion object {
        const val UNIQUE_NAME = "WorkoutReminderWorker"
        const val CHANNEL_ID = "workout_reminders"
        private const val NOTIF_ID = 4001

        fun ensureChannel(context: Context) {
            val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager
            if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
                mgr.createNotificationChannel(
                    NotificationChannel(
                        CHANNEL_ID,
                        "Workout reminders",
                        NotificationManager.IMPORTANCE_DEFAULT,
                    ).apply { description = "Daily reminder on workout days" }
                )
            }
        }
    }
}
