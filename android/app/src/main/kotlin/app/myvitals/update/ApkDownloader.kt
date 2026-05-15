package app.myvitals.update

import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import timber.log.Timber
import java.io.File

/**
 * Replaces UpdateInstallerActivity — owns DownloadManager + state for
 * the active APK download. The Settings screen reads `state` to render
 * inline progress; an Application-scope BroadcastReceiver triggers the
 * install intent when ACTION_DOWNLOAD_COMPLETE fires. Single instance:
 * we only ever have one APK update in flight.
 */
object ApkDownloader {

    sealed class State {
        object Idle : State()
        data class Pending(val name: String) : State()
        data class Downloading(
            val name: String,
            val bytesDownloaded: Long,
            val bytesTotal: Long,
        ) : State() {
            val progress: Float
                get() = if (bytesTotal > 0)
                    (bytesDownloaded.toFloat() / bytesTotal.toFloat()).coerceIn(0f, 1f)
                else 0f
        }
        data class Installing(val name: String, val file: File) : State()
        data class Failed(val message: String) : State()
    }

    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state.asStateFlow()

    private var downloadId: Long = -1
    private var apkFile: File? = null
    private var apkName: String = "myvitals.apk"
    private var pollJob: Job? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Kick off a new APK download. Replaces any in-flight one. */
    fun start(context: Context, url: String, name: String) {
        if (!canInstallPackages(context)) {
            _state.value = State.Failed(
                "Allow myvitals to install apps, then tap Apply again.",
            )
            // Bounce user to the system settings page so they can grant it.
            val settings = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                .setData(Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(settings)
            return
        }
        cancelInflight(context)

        apkName = name
        val targetDir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
        val file = File(targetDir, name).also {
            if (it.exists()) it.delete()
        }
        apkFile = file
        _state.value = State.Pending(name)

        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val req = DownloadManager.Request(Uri.parse(url))
            .setTitle("myvitals update")
            .setDescription(name)
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationUri(Uri.fromFile(file))
        downloadId = dm.enqueue(req)
        Timber.i("ApkDownloader: enqueued id=%d name=%s", downloadId, name)

        pollJob = scope.launch {
            while (downloadId != -1L) {
                pollOnce(dm)
                val s = _state.value
                if (s is State.Installing || s is State.Idle || s is State.Failed) break
                delay(500)
            }
        }
    }

    private fun pollOnce(dm: DownloadManager) {
        val q = DownloadManager.Query().setFilterById(downloadId)
        dm.query(q)?.use { c ->
            if (!c.moveToFirst()) return
            val status = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
            val soFar = c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
            val total = c.getLong(c.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
            val reason = c.getInt(c.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON))
            when (status) {
                DownloadManager.STATUS_PENDING ->
                    _state.value = State.Pending(apkName)
                DownloadManager.STATUS_PAUSED ->
                    _state.value = State.Failed("Paused (${pauseReason(reason)})")
                DownloadManager.STATUS_RUNNING ->
                    _state.value = State.Downloading(apkName, soFar, total)
                DownloadManager.STATUS_SUCCESSFUL ->
                    finalizeSuccess()
                DownloadManager.STATUS_FAILED -> {
                    _state.value = State.Failed("Download failed (code $reason)")
                    downloadId = -1
                }
            }
        }
    }

    /** Called from the poll loop AND the broadcast receiver — both
     *  paths converge here, idempotent via downloadId == -1 guard. */
    private fun finalizeSuccess() {
        val f = apkFile
        if (f == null || !f.exists() || f.length() == 0L) {
            _state.value = State.Failed("Download finished but APK is missing.")
            downloadId = -1
            return
        }
        downloadId = -1
        _state.value = State.Installing(apkName, f)
    }

    /** Called from the app-scope BroadcastReceiver in MyVitalsApp. */
    internal fun onDownloadComplete(broadcastId: Long) {
        if (broadcastId != downloadId) return
        finalizeSuccess()
    }

    /** Launch the install intent. Called by Settings UI when the user
     *  taps "Install" on the Installing state — keeps the OS install
     *  prompt user-initiated rather than auto-firing from a background
     *  broadcast (some OEMs block the latter). */
    fun launchInstaller(context: Context) {
        val s = _state.value
        if (s !is State.Installing) return
        val uri = FileProvider.getUriForFile(
            context, "${context.packageName}.fileprovider", s.file,
        )
        val install = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
        }
        context.startActivity(install)
        _state.value = State.Idle
    }

    fun dismiss() {
        _state.value = State.Idle
    }

    fun cancelInflight(context: Context) {
        if (downloadId != -1L) {
            try {
                (context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager)
                    .remove(downloadId)
            } catch (_: Exception) {}
        }
        pollJob?.cancel()
        pollJob = null
        downloadId = -1
        _state.value = State.Idle
    }

    private fun canInstallPackages(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            context.packageManager.canRequestPackageInstalls()
        else true

    private fun pauseReason(code: Int): String = when (code) {
        DownloadManager.PAUSED_WAITING_FOR_NETWORK -> "no network"
        DownloadManager.PAUSED_WAITING_TO_RETRY -> "retrying"
        DownloadManager.PAUSED_QUEUED_FOR_WIFI -> "waiting for Wi-Fi"
        DownloadManager.PAUSED_UNKNOWN -> "unknown"
        else -> "code $code"
    }
}


/**
 * App-scope receiver for ACTION_DOWNLOAD_COMPLETE. Registered in
 * MyVitalsApp.onCreate so it survives activity lifecycle.
 */
class ApkDownloadCompleteReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1)
        if (id != -1L) ApkDownloader.onDownloadComplete(id)
    }

    companion object {
        fun register(context: Context): ApkDownloadCompleteReceiver {
            val r = ApkDownloadCompleteReceiver()
            val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.registerReceiver(r, filter, Context.RECEIVER_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                context.registerReceiver(r, filter)
            }
            return r
        }
    }
}
