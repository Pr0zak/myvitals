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
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.core.content.FileProvider
import timber.log.Timber
import java.io.File

/**
 * Headless activity: downloads the APK via DownloadManager, then launches the
 * system package installer when the download completes. The user is shown the
 * standard "Install / Cancel" Android install dialog.
 *
 * If the app isn't allowed to install packages yet, bounce the user to the
 * system "install unknown apps" settings page first; they retap the install
 * action when they come back.
 */
class UpdateInstallerActivity : ComponentActivity() {

    private var downloadId: Long = -1
    private var receiver: BroadcastReceiver? = null
    private lateinit var apkFile: File
    private var apkName: String = "myvitals.apk"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = intent.getStringExtra(EXTRA_URL) ?: run {
            Timber.w("UpdateInstaller called without URL")
            finish(); return
        }
        apkName = intent.getStringExtra(EXTRA_NAME) ?: "myvitals.apk"
        Timber.i("UpdateInstaller: url=%s", url)

        if (!canInstallPackages()) {
            Timber.w("REQUEST_INSTALL_PACKAGES not granted — sending to system settings")
            Toast.makeText(
                this,
                "Allow myvitals to install apps, then tap the update again",
                Toast.LENGTH_LONG,
            ).show()
            val settings = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                .setData(Uri.parse("package:$packageName"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(settings)
            finish()
            return
        }

        apkFile = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), apkName)
        if (apkFile.exists()) apkFile.delete()

        Toast.makeText(this, "Downloading $apkName…", Toast.LENGTH_SHORT).show()

        val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
        val req = DownloadManager.Request(Uri.parse(url))
            .setTitle("myvitals update")
            .setDescription(apkName)
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

    private fun canInstallPackages(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            packageManager.canRequestPackageInstalls()
        } else {
            true
        }
    }

    private fun onDownloadComplete() {
        if (!apkFile.exists() || apkFile.length() == 0L) {
            Timber.e("Download finished but file is missing/empty: %s", apkFile.absolutePath)
            Toast.makeText(this, "Download failed", Toast.LENGTH_LONG).show()
            cleanupAndFinish()
            return
        }

        Timber.i("Launching install intent for %s (%d bytes)", apkFile.name, apkFile.length())
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", apkFile)
        val install = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
        }
        startActivity(install)
        cleanupAndFinish()
    }

    private fun cleanupAndFinish() {
        try { receiver?.let { unregisterReceiver(it) } } catch (_: Exception) {}
        finish()
    }

    companion object {
        const val EXTRA_URL = "url"
        const val EXTRA_NAME = "name"

        fun start(context: Context, url: String, name: String) {
            context.startActivity(
                Intent(context, UpdateInstallerActivity::class.java).apply {
                    putExtra(EXTRA_URL, url)
                    putExtra(EXTRA_NAME, name)
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
            )
        }
    }
}
