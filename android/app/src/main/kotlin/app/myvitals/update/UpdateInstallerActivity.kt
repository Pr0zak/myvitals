package app.myvitals.update

import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.content.FileProvider
import java.io.File

/**
 * Headless activity: downloads the APK via DownloadManager, then launches the
 * system package installer when the download completes. The user is shown the
 * standard "Install / Cancel" Android install dialog.
 *
 * Requires `REQUEST_INSTALL_PACKAGES` permission and the user to have enabled
 * "Install unknown apps" for myvitals in system settings.
 */
class UpdateInstallerActivity : ComponentActivity() {

    private var downloadId: Long = -1
    private lateinit var receiver: BroadcastReceiver
    private lateinit var apkFile: File

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = intent.getStringExtra(EXTRA_URL) ?: run { finish(); return }
        val name = intent.getStringExtra(EXTRA_NAME) ?: "myvitals.apk"

        apkFile = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), name)
        if (apkFile.exists()) apkFile.delete()

        Toast.makeText(this, "Downloading $name…", Toast.LENGTH_SHORT).show()

        val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
        val req = DownloadManager.Request(Uri.parse(url))
            .setTitle("myvitals update")
            .setDescription(name)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationUri(Uri.fromFile(apkFile))
        downloadId = dm.enqueue(req)

        receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                if (intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1) != downloadId) return
                onDownloadComplete()
            }
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(
                receiver,
                IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
                RECEIVER_NOT_EXPORTED,
            )
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(receiver, IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE))
        }
    }

    private fun onDownloadComplete() {
        if (!apkFile.exists() || apkFile.length() == 0L) {
            Toast.makeText(this, "Download failed", Toast.LENGTH_LONG).show()
            cleanupAndFinish()
            return
        }

        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", apkFile)
        val install = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
        }
        startActivity(install)
        cleanupAndFinish()
    }

    private fun cleanupAndFinish() {
        try { unregisterReceiver(receiver) } catch (_: Exception) {}
        finish()
    }

    companion object {
        const val EXTRA_URL = "url"
        const val EXTRA_NAME = "name"
    }
}
