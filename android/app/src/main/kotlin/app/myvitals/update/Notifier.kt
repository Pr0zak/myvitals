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
