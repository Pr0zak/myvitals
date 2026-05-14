package app.myvitals.update

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

object Notifier {

    private const val CHANNEL_ID = "updates"
    private const val NOTIF_ID = 1001
    const val TRAIL_CHANNEL_ID = "trail_status"
    private const val TRAIL_NOTIF_BASE = 2000
    const val REST_TIMER_CHANNEL_ID = "rest_timer"
    private const val REST_TIMER_NOTIF_ID = 3001
    const val FASTING_CHANNEL_ID = "fasting"
    private const val FASTING_NOTIF_BASE = 4000

    fun ensureChannel(context: Context) {
        val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "App updates",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply { description = "New release available for sideload" }
            )
        }
        if (mgr.getNotificationChannel(TRAIL_CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    TRAIL_CHANNEL_ID,
                    "Trail status",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply { description = "Subscribed trails opened or closed" }
            )
        }
        if (mgr.getNotificationChannel(REST_TIMER_CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    REST_TIMER_CHANNEL_ID,
                    "Rest timer",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "Cue when an inter-set rest period finishes"
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 200, 80, 200)
                }
            )
        }
        if (mgr.getNotificationChannel(FASTING_CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    FASTING_CHANNEL_ID,
                    "Fasting milestones",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "Pings as you hit each fasting stage (ketosis, autophagy, …)"
                }
            )
        }
    }

    /** Fire a fasting-stage milestone notification.
     *  notifKey makes the id stable per (session, stage) so re-posting
     *  (rare; e.g. the worker fires twice on a deferred wake-up) replaces
     *  rather than stacks. */
    fun postFastingMilestone(
        context: Context, sessionId: Long, stageLabel: String,
        elapsedH: Double, targetH: Double,
    ) {
        ensureChannel(context)
        val title = "Fasting: $stageLabel"
        val body = "${"%.0f".format(elapsedH)}h in — ${"%.0f".format(targetH - elapsedH)}h to your target."
        val notif = NotificationCompat.Builder(context, FASTING_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .build()
        // Bucket id by session+stageLabel so different stages of one fast
        // stack cleanly; a future fast won't collide.
        val notifId = FASTING_NOTIF_BASE + (sessionId.toInt() and 0xff) * 16 +
            (stageLabel.hashCode() and 0xf)
        try {
            NotificationManagerCompat.from(context).notify(notifId, notif)
        } catch (_: SecurityException) { /* permission revoked */ }
    }

    /** Vibrate + chime when a yoga / mobility hold timer reaches 0.
     *  No notification card — the user is looking at the timer in the
     *  foreground, but their phone may be face-down on the mat so the
     *  haptic + sound are what they actually need.  */
    fun postHoldDone(context: Context) {
        val vib = context.getSystemService(Context.VIBRATOR_SERVICE) as? android.os.Vibrator
        try {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                vib?.vibrate(android.os.VibrationEffect.createWaveform(
                    longArrayOf(0, 200, 80, 200), -1,
                ))
            } else {
                @Suppress("DEPRECATION")
                vib?.vibrate(longArrayOf(0, 200, 80, 200), -1)
            }
        } catch (_: SecurityException) { /* no haptic permission */ }
        try {
            val uri = android.media.RingtoneManager.getDefaultUri(
                android.media.RingtoneManager.TYPE_NOTIFICATION
            )
            android.media.RingtoneManager.getRingtone(context, uri)?.also { rt ->
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
                    rt.audioAttributes = android.media.AudioAttributes.Builder()
                        .setUsage(android.media.AudioAttributes.USAGE_NOTIFICATION)
                        .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                }
                rt.play()
            }
        } catch (_: Exception) { /* sound failed — non-critical */ }
    }

    /** Briefly vibrate + post a heads-up notification when rest hits 0. */
    fun postRestTimerDone(context: Context, secondsRested: Int) {
        ensureChannel(context)
        // Vibrate explicitly — heads-up channel will vibrate on its own but
        // this also fires when the channel is muted
        val vib = context.getSystemService(Context.VIBRATOR_SERVICE) as? android.os.Vibrator
        try {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                vib?.vibrate(android.os.VibrationEffect.createWaveform(
                    longArrayOf(0, 200, 80, 200), -1,
                ))
            } else {
                @Suppress("DEPRECATION")
                vib?.vibrate(longArrayOf(0, 200, 80, 200), -1)
            }
        } catch (_: SecurityException) { /* no haptic permission */ }

        // Audible chime — uses the system default notification tone so it
        // respects the user's volume / DND. Plays whether or not the
        // notification itself fires.
        try {
            val uri = android.media.RingtoneManager.getDefaultUri(
                android.media.RingtoneManager.TYPE_NOTIFICATION
            )
            android.media.RingtoneManager.getRingtone(context, uri)?.also { rt ->
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
                    rt.audioAttributes = android.media.AudioAttributes.Builder()
                        .setUsage(android.media.AudioAttributes.USAGE_NOTIFICATION)
                        .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                }
                rt.play()
            }
        } catch (e: Exception) { /* sound failed — non-critical */ }

        val notif = NotificationCompat.Builder(context, REST_TIMER_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("Rest done")
            .setContentText("${secondsRested}s rest complete — start your next set.")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setTimeoutAfter(15_000)   // self-dismiss after 15s
            .build()
        try {
            NotificationManagerCompat.from(context).notify(REST_TIMER_NOTIF_ID, notif)
        } catch (_: SecurityException) { /* permission revoked */ }
    }

    /** Post a single trail-status flip notification. Stable per alert id
     * so re-posting (rare) replaces rather than stacks. */
    fun postTrailAlert(
        context: Context, alertId: Long, trailName: String,
        fromStatus: String?, toStatus: String, comment: String? = null,
    ) {
        ensureChannel(context)
        val title = if (toStatus == "open") "$trailName is OPEN"
                    else if (toStatus == "closed") "$trailName closed"
                    else "$trailName: $toStatus"
        val body = comment ?: when {
            fromStatus == null -> "Status: $toStatus"
            else -> "Was $fromStatus, now $toStatus"
        }
        val notif = NotificationCompat.Builder(context, TRAIL_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_notification_overlay)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context)
                .notify(TRAIL_NOTIF_BASE + alertId.toInt(), notif)
        } catch (_: SecurityException) { /* permission revoked */ }
    }

    fun postUpdateAvailable(context: Context, release: GitHubRelease) {
        ensureChannel(context)

        val asset = release.assets.firstOrNull { it.name.endsWith(".apk") } ?: return

        val intent = Intent(context, UpdateInstallerActivity::class.java).apply {
            putExtra(UpdateInstallerActivity.EXTRA_URL, asset.browserDownloadUrl)
            putExtra(UpdateInstallerActivity.EXTRA_NAME, asset.name)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }

        val pi = PendingIntent.getActivity(
            context,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notif = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("myvitals ${release.tagName} available")
            .setContentText("Tap to download and install")
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()

        // POST_NOTIFICATIONS check: if user revoked, this no-ops silently.
        try {
            NotificationManagerCompat.from(context).notify(NOTIF_ID, notif)
        } catch (_: SecurityException) { /* permission revoked */ }
    }
}
