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
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import app.myvitals.ui.MyVitalsTheme
import timber.log.Timber
import java.io.File

/**
 * Foreground activity that downloads the APK via DownloadManager and shows a
 * brand-styled progress UI while the bytes come down. We poll DownloadManager
 * every 500 ms for bytes-downloaded / total-bytes and render a determinate
 * progress bar — much friendlier than the previous translucent activity that
 * showed only a Toast and relied on the system download notification.
 *
 * On completion: kick off the standard PackageInstaller intent.
 * On failure: surface the DownloadManager reason and a Retry button.
 */
class UpdateInstallerActivity : ComponentActivity() {

    private var downloadId: Long = -1
    private var receiver: BroadcastReceiver? = null
    private lateinit var apkFile: File
    private var apkName: String = "myvitals.apk"
    private val poll = Handler(Looper.getMainLooper())

    private var stateLabel by mutableStateOf("Preparing download…")
    private var stateError by mutableStateOf<String?>(null)
    private var stateDone by mutableStateOf(false)
    private var bytesDownloaded by mutableStateOf(0L)
    private var bytesTotal by mutableStateOf(0L)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = intent.getStringExtra(EXTRA_URL) ?: run {
            Timber.w("UpdateInstaller called without URL")
            finish(); return
        }
        apkName = intent.getStringExtra(EXTRA_NAME) ?: "myvitals.apk"
        Timber.i("UpdateInstaller: url=%s", url)

        setContent {
            MyVitalsTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = Color(0xFF0F172A)) {
                    InstallerScreen(
                        apkName = apkName,
                        label = stateLabel,
                        bytesDownloaded = bytesDownloaded,
                        bytesTotal = bytesTotal,
                        error = stateError,
                        done = stateDone,
                        onCancel = {
                            cancelDownload(); finish()
                        },
                        onRetry = {
                            stateError = null
                            startDownload(url)
                        },
                        onClose = { finish() },
                    )
                }
            }
        }

        if (!canInstallPackages()) {
            Timber.w("REQUEST_INSTALL_PACKAGES not granted — sending to system settings")
            stateError =
                "Allow myvitals to install apps, then tap the update again."
            val settings = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                .setData(Uri.parse("package:$packageName"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(settings)
            return
        }

        startDownload(url)
    }

    private fun startDownload(url: String) {
        apkFile = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), apkName)
        if (apkFile.exists()) apkFile.delete()

        stateLabel = "Downloading $apkName…"
        bytesDownloaded = 0
        bytesTotal = 0

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

        poll.post(pollRunner)
    }

    private val pollRunner = object : Runnable {
        override fun run() {
            if (downloadId == -1L || stateDone || stateError != null) return
            val dm = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            val q = DownloadManager.Query().setFilterById(downloadId)
            dm.query(q)?.use { c ->
                if (c.moveToFirst()) {
                    val statusCol = c.getColumnIndex(DownloadManager.COLUMN_STATUS)
                    val soFarCol = c.getColumnIndex(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)
                    val totalCol = c.getColumnIndex(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)
                    val reasonCol = c.getColumnIndex(DownloadManager.COLUMN_REASON)
                    val status = if (statusCol >= 0) c.getInt(statusCol) else -1
                    val soFar = if (soFarCol >= 0) c.getLong(soFarCol) else 0L
                    val total = if (totalCol >= 0) c.getLong(totalCol) else 0L
                    val reason = if (reasonCol >= 0) c.getInt(reasonCol) else 0

                    bytesDownloaded = soFar
                    bytesTotal = total
                    when (status) {
                        DownloadManager.STATUS_PENDING -> stateLabel = "Waiting to start…"
                        DownloadManager.STATUS_PAUSED -> stateLabel = "Paused — ${pauseReason(reason)}"
                        DownloadManager.STATUS_RUNNING -> stateLabel = "Downloading $apkName…"
                        DownloadManager.STATUS_SUCCESSFUL -> { /* receiver will handle */ }
                        DownloadManager.STATUS_FAILED -> {
                            stateError = "Download failed (code $reason)."
                            return
                        }
                    }
                }
            }
            poll.postDelayed(this, 500)
        }
    }

    private fun pauseReason(code: Int): String = when (code) {
        DownloadManager.PAUSED_WAITING_FOR_NETWORK -> "no network"
        DownloadManager.PAUSED_WAITING_TO_RETRY -> "retrying"
        DownloadManager.PAUSED_QUEUED_FOR_WIFI -> "waiting for Wi-Fi"
        DownloadManager.PAUSED_UNKNOWN -> "unknown"
        else -> "code $code"
    }

    private fun canInstallPackages(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            packageManager.canRequestPackageInstalls()
        } else {
            true
        }
    }

    private fun cancelDownload() {
        if (downloadId == -1L) return
        try {
            (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).remove(downloadId)
        } catch (_: Exception) {}
        downloadId = -1
        poll.removeCallbacks(pollRunner)
    }

    private fun onDownloadComplete() {
        poll.removeCallbacks(pollRunner)
        if (!apkFile.exists() || apkFile.length() == 0L) {
            Timber.e("Download finished but file is missing/empty: %s", apkFile.absolutePath)
            stateError = "Download finished but the APK file is missing."
            return
        }
        stateLabel = "Launching installer…"
        stateDone = true

        Timber.i("Launching install intent for %s (%d bytes)", apkFile.name, apkFile.length())
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", apkFile)
        val install = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
        }
        startActivity(install)
        // Don't auto-finish — the system installer dialog steals focus, and
        // when the user comes back we want this progress screen to still be
        // here so they have a clear "done" indicator. They can tap Close.
    }

    override fun onDestroy() {
        super.onDestroy()
        poll.removeCallbacks(pollRunner)
        try { receiver?.let { unregisterReceiver(it) } } catch (_: Exception) {}
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

@Composable
private fun InstallerScreen(
    apkName: String,
    label: String,
    bytesDownloaded: Long,
    bytesTotal: Long,
    error: String?,
    done: Boolean,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
    onClose: () -> Unit,
) {
    val progress = remember(bytesDownloaded, bytesTotal) {
        if (bytesTotal > 0) (bytesDownloaded.toFloat() / bytesTotal.toFloat()).coerceIn(0f, 1f)
        else 0f
    }
    val knownTotal = bytesTotal > 0
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0F172A))
            .padding(24.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().align(Alignment.Center),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "Updating myvitals",
                fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold,
                color = Color(0xFFE2E8F0),
            )
            Spacer(Modifier.height(8.dp))
            Text(
                apkName,
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = Color(0xFF64748B),
            )
            Spacer(Modifier.height(28.dp))

            if (error != null) {
                Text(
                    error,
                    color = Color(0xFFEF4444),
                    fontSize = 13.sp,
                )
            } else {
                Text(
                    label,
                    color = Color(0xFF94A3B8),
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(14.dp))
                if (knownTotal) {
                    LinearProgressIndicator(
                        progress = { progress },
                        modifier = Modifier.fillMaxWidth().height(6.dp),
                        color = Color(0xFF38BDF8),
                        trackColor = Color(0xFF1E293B),
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "${fmtMB(bytesDownloaded)} / ${fmtMB(bytesTotal)}  ·  ${(progress * 100).toInt()}%",
                        color = Color(0xFFE2E8F0),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.sp,
                    )
                } else {
                    LinearProgressIndicator(
                        modifier = Modifier.fillMaxWidth().height(6.dp),
                        color = Color(0xFF38BDF8),
                        trackColor = Color(0xFF1E293B),
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        if (bytesDownloaded > 0) fmtMB(bytesDownloaded) else "—",
                        color = Color(0xFF94A3B8),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.sp,
                    )
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().align(Alignment.BottomCenter),
            horizontalArrangement = Arrangement.Center,
        ) {
            when {
                done -> Button(
                    onClick = onClose,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF38BDF8)),
                ) { Text("Close") }
                error != null -> {
                    Button(
                        onClick = onRetry,
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF38BDF8)),
                    ) { Text("Retry") }
                    Spacer(Modifier.width(12.dp))
                    Button(
                        onClick = onClose,
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF334155)),
                    ) { Text("Close") }
                }
                else -> Button(
                    onClick = onCancel,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF334155)),
                ) { Text("Cancel") }
            }
        }
    }
}

private fun fmtMB(bytes: Long): String {
    if (bytes <= 0) return "0.0 MB"
    val mb = bytes / 1_048_576.0
    return String.format(java.util.Locale.US, "%.1f MB", mb)
}
