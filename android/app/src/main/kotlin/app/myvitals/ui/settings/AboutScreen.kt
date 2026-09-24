package app.myvitals.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.BuildConfig
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ServerVersion
import app.myvitals.sync.UpdateCheck
import app.myvitals.sync.UpdateCronStatus
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import app.myvitals.update.ApkDownloader
import app.myvitals.update.UpdateChecker
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant

/**
 * About & updates (SETTINGS-C). Mirrors web `settings/SettingsAbout.vue`.
 *
 * Server version, the release check, Apply (which now asks first — it
 * restarts the server), and the auto-update cron's log; then the phone app's
 * version and its APK update. The old screen had two separate "Check for
 * updates" rows, one per half; there is one button now and it checks both.
 */
@Composable
fun AboutScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var version by remember { mutableStateOf<ServerVersion?>(null) }
    var check by remember { mutableStateOf<UpdateCheck?>(null) }
    var cron by remember { mutableStateOf<UpdateCronStatus?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var checking by remember { mutableStateOf(false) }
    var checkError by remember { mutableStateOf<String?>(null) }
    var appCheck by remember { mutableStateOf<UpdateChecker.Result?>(null) }
    var applying by remember { mutableStateOf(false) }
    var applyMsg by remember { mutableStateOf<String?>(null) }
    val apkState by ApkDownloader.state.collectAsState()

    suspend fun load() {
        coroutineScope {
            val v = async { runCatching { settings.call { serverVersion() } } }
            val c = async { runCatching { settings.call { updateCronStatus() } } }
            v.await().onSuccess { version = it }
            c.await().onSuccess { cron = it }
            val fail = v.await().exceptionOrNull() ?: c.await().exceptionOrNull()
            error = fail?.settingsMessage()
        }
        loading = false
    }

    suspend fun checkBoth() {
        checking = true; checkError = null
        coroutineScope {
            val s = async { runCatching { settings.call { updateCheck() } } }
            val a = async { UpdateChecker.check() }
            s.await().onSuccess { check = it }.onFailure {
                Timber.w(it, "server update check failed")
                checkError = it.settingsMessage()
            }
            appCheck = a.await()
        }
        checking = false
    }

    LaunchedEffect(Unit) { load() }

    AboutContent(
        version = version, check = check, cron = cron,
        loading = loading, refreshing = refreshing, error = error,
        checking = checking, checkError = checkError,
        appVersion = "${BuildConfig.VERSION_NAME} · build ${BuildConfig.VERSION_CODE}",
        appCheck = appCheck, apkState = apkState,
        applying = applying, applyMsg = applyMsg,
        now = Instant.now(),
        onCheck = { scope.launch { checkBoth() } },
        onApply = {
            scope.launch {
                applying = true; applyMsg = null
                try {
                    val r = settings.call { updateApply() }
                    applyMsg = if (r.triggered) "Update started. The server restarts in about a minute."
                    else r.hint ?: r.error ?: "The server didn't start the update."
                    if (r.triggered) {
                        delay(30_000)
                        runCatching { settings.call { updateCheck() } }.onSuccess { check = it }
                        load()
                    }
                } catch (e: Exception) {
                    applyMsg = "Couldn't start the update: ${e.settingsMessage()}"
                } finally {
                    applying = false
                }
            }
        },
        onDownloadApk = { url, name -> ApkDownloader.start(context, url, name) },
        onCancelApk = { ApkDownloader.cancelInflight(context) },
        onInstallApk = { ApkDownloader.launchInstaller(context) },
        onDismissApk = { ApkDownloader.dismiss() },
        onBack = onBack,
        onRefresh = { scope.launch { refreshing = true; try { load() } finally { refreshing = false } } },
    )
}

@Composable
fun AboutContent(
    version: ServerVersion?,
    check: UpdateCheck?,
    cron: UpdateCronStatus?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    checking: Boolean,
    checkError: String?,
    appVersion: String,
    appCheck: UpdateChecker.Result?,
    apkState: ApkDownloader.State,
    applying: Boolean,
    applyMsg: String?,
    now: Instant,
    onCheck: () -> Unit,
    onApply: () -> Unit,
    onDownloadApk: (url: String, name: String) -> Unit,
    onCancelApk: () -> Unit,
    onInstallApk: () -> Unit,
    onDismissApk: () -> Unit,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    var confirmApply by remember { mutableStateOf(false) }
    var showFullLog by remember { mutableStateOf(false) }
    if (confirmApply && check?.latest != null) {
        SettingsConfirm(
            title = "Update the server to v${check.latest}?",
            text = "The server downloads the new version and restarts. The app and the " +
                "dashboard can't reach it for about a minute; nothing is lost.",
            confirmLabel = "Update server",
            onConfirm = onApply,
            onDismiss = { confirmApply = false },
        )
    }

    NeonScreen(
        title = "About & updates",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (error != null && !loading) {
            NeonErrorBanner(error, title = "Couldn't read the server's version") { onRefresh() }
        }

        NeonEyebrow("Check")
        SettingsCard {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    when {
                        checking -> "Checking the server and this app…"
                        check == null && appCheck == null -> "Looks for new releases of both the server and this app."
                        else -> "Checked just now."
                    },
                    color = NeonMV.Muted, fontSize = 12.sp, modifier = Modifier.weight(1f),
                )
                NeonButton(if (checking) "Checking…" else "Check for updates", onCheck, enabled = !checking)
            }
        }

        NeonEyebrow("Server")
        SettingsCard {
            when {
                version != null -> SettingsKv("Running", "v${version.version}")
                loading -> SettingsSkeleton(listOf(40.dp))
                else -> SettingsKv("Running", "unknown", valueColor = NeonMV.Amber)
            }
            version?.gitSha?.takeIf { it != "unknown" && it.isNotBlank() }?.let {
                SettingsKv("Build", it.take(7))
            }
            check?.let { c ->
                SettingsKv(
                    "Latest release", c.latest?.let { "v$it" } ?: "—",
                    valueColor = if (c.updateAvailable) NeonMV.Lime else NeonMV.Muted,
                )
                c.error?.let { SettingsNote("Couldn't check GitHub: $it", color = NeonMV.Amber) }
                if (c.updateAvailable) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        StatusPill("Update available", NeonMV.Lime)
                        Spacer(Modifier.weight(1f))
                        NeonButton(if (applying) "Starting…" else "Apply v${c.latest}",
                            { confirmApply = true }, enabled = !applying)
                    }
                } else if (c.error == null) {
                    SettingsNote("The server is up to date.")
                }
            }
            checkError?.let { SettingsNote("Couldn't check for a server update: $it", color = NeonMV.Amber) }
            applyMsg?.let { SettingsNote(it, color = NeonMV.Ink) }
        }

        NeonEyebrow("Auto-update")
        when {
            cron != null -> SettingsCard {
                SettingsKv(
                    "Update job",
                    when {
                        !cron.logPresent -> "no log yet"
                        cron.cronHealthy -> "running"
                        else -> "not running"
                    },
                    valueColor = if (cron.cronHealthy) NeonMV.Lime else NeonMV.Amber,
                )
                SettingsKv("Last run", relAge(parseInstant(cron.logModifiedAt), now))
                if (cron.triggerPending) SettingsNote("An update you started is waiting for the next run.", color = NeonMV.Cyan)
                if (cron.tail.isNotEmpty()) {
                    val lines = if (showFullLog) cron.tail else cron.tail.takeLast(6)
                    Column(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)
                            .background(NeonMV.Bg, RoundedCornerShape(10.dp))
                            .padding(10.dp),
                    ) {
                        for (l in lines) {
                            Text(l, color = NeonMV.Muted, fontSize = 10.sp, fontFamily = FontFamily.Monospace,
                                lineHeight = 13.sp, maxLines = 2)
                        }
                    }
                    if (cron.tail.size > 6) {
                        Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                            NeonChip(if (showFullLog) "Show less" else "Show full log (${cron.tail.size} lines)",
                                false) { showFullLog = !showFullLog }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
            loading -> SettingsSkeleton(listOf(120.dp))
            else -> SettingsCard { SettingsNote("The auto-update log couldn't be read.", color = NeonMV.Amber) }
        }

        NeonEyebrow("This app")
        SettingsCard {
            SettingsKv("Version", appVersion)
            when (appCheck) {
                null -> {}
                is UpdateChecker.Result.UpToDate -> SettingsNote("This app is up to date.")
                is UpdateChecker.Result.Failed ->
                    SettingsNote("Couldn't check GitHub for a new app: ${appCheck.message}", color = NeonMV.Amber)
                is UpdateChecker.Result.Available -> {
                    val asset = appCheck.release.assets.firstOrNull { it.name.endsWith(".apk") }
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        StatusPill("${appCheck.release.tagName} available", NeonMV.Lime)
                        Spacer(Modifier.weight(1f))
                        if (asset != null && apkState is ApkDownloader.State.Idle) {
                            NeonButton("Download", { onDownloadApk(asset.browserDownloadUrl, asset.name) })
                        }
                    }
                }
            }
            ApkProgress(apkState, onCancelApk, onInstallApk, onDismissApk)
        }
        Spacer(Modifier.height(24.dp))
    }
}

/** Inline APK download progress (replaced the old full-screen installer). */
@Composable
private fun ApkProgress(
    state: ApkDownloader.State,
    onCancel: () -> Unit,
    onInstall: () -> Unit,
    onDismiss: () -> Unit,
) {
    when (state) {
        is ApkDownloader.State.Idle -> {}
        is ApkDownloader.State.Pending -> Column(Modifier.padding(16.dp)) {
            Text("Starting download…", color = NeonMV.Ink, fontSize = 13.sp)
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(Modifier.fillMaxWidth(), color = NeonMV.Lime, trackColor = NeonMV.Track)
        }
        is ApkDownloader.State.Downloading -> Column(Modifier.padding(16.dp)) {
            val pct = (state.progress * 100).toInt()
            Text(
                if (state.bytesTotal > 0) "Downloading… $pct% · ${mb(state.bytesDownloaded)} of ${mb(state.bytesTotal)}"
                else "Downloading… ${mb(state.bytesDownloaded)}",
                color = NeonMV.Ink, fontSize = 13.sp,
            )
            Spacer(Modifier.height(8.dp))
            if (state.bytesTotal > 0) {
                LinearProgressIndicator(progress = { state.progress }, modifier = Modifier.fillMaxWidth(),
                    color = NeonMV.Lime, trackColor = NeonMV.Track)
            } else {
                LinearProgressIndicator(Modifier.fillMaxWidth(), color = NeonMV.Lime, trackColor = NeonMV.Track)
            }
            Spacer(Modifier.height(10.dp))
            NeonButton("Cancel", onCancel, filled = false, accent = NeonMV.Muted)
        }
        is ApkDownloader.State.Installing -> Column(Modifier.padding(16.dp)) {
            Text("Downloaded. Tap Install to open the system installer.", color = NeonMV.Ink, fontSize = 13.sp)
            Spacer(Modifier.height(10.dp))
            NeonButton("Install", onInstall)
        }
        is ApkDownloader.State.Failed -> Column(Modifier.padding(16.dp)) {
            Text(state.message, color = NeonMV.Amber, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(10.dp))
            NeonButton("Dismiss", onDismiss, filled = false, accent = NeonMV.Muted)
        }
    }
}

private fun mb(bytes: Long): String =
    if (bytes <= 0) "0.0 MB" else String.format(java.util.Locale.US, "%.1f MB", bytes / 1_048_576.0)
