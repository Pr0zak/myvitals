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
