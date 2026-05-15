package app.myvitals.ui

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.gestures.detectTapGestures
import app.myvitals.BuildConfig
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.ProfilePutBody
import app.myvitals.sync.ProfileResponse
import app.myvitals.update.GitHubRelease
import app.myvitals.update.UpdateChecker
import app.myvitals.update.ApkDownloader
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.runtime.collectAsState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(
    settings: SettingsRepository,
    isHealthConnectAvailable: Boolean,
    hasPermissions: () -> Boolean,
    onRequestPermissions: () -> Unit,
    onSyncNow: () -> Unit,
    onSyncLogs: () -> Unit,
    onBackfill: (days: Int) -> Unit,
    onOpenLogs: () -> Unit,
    onClearBuffer: () -> Unit,
) {
    var url by remember { mutableStateOf(settings.backendUrl) }
    var token by remember { mutableStateOf(settings.bearerToken) }
    var updateStatus by remember { mutableStateOf("") }
    var pendingRelease by remember { mutableStateOf<GitHubRelease?>(null) }

    // UPDATE-2: backend release check + apply.
    var backendCheck by remember {
        mutableStateOf<app.myvitals.sync.UpdateCheck?>(null)
    }
    var backendBusy by remember { mutableStateOf(false) }
    var backendApplyMsg by remember { mutableStateOf("") }
    var dirty by remember { mutableStateOf(false) }
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    var reminderEnabled by remember { mutableStateOf(false) }
    var reminderHour by remember { mutableStateOf(8) }
    var showClearBufferConfirm by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val apkState by ApkDownloader.state.collectAsState()

    if (showClearBufferConfirm) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { showClearBufferConfirm = false },
            title = { Text("Clear sync buffer?") },
            text = {
                Text(
                    "Discards every unsynced set log, workout patch and " +
                    "log line currently buffered on this device. Use this " +
                    "only if the buffer is stuck and you don't mind losing " +
                    "the pending writes.",
                )
            },
            confirmButton = {
                androidx.compose.material3.TextButton(
                    onClick = {
                        showClearBufferConfirm = false
                        onClearBuffer()
                        Toast.makeText(context, "Sync buffer cleared", Toast.LENGTH_SHORT).show()
                    },
                ) { Text("Clear", color = MV.Red) }
            },
            dismissButton = {
                androidx.compose.material3.TextButton(
                    onClick = { showClearBufferConfirm = false },
                ) { Text("Cancel") }
            },
        )
    }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) return@LaunchedEffect
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) { api.profile() }
        }.onSuccess { p ->
            profile = p
            reminderEnabled = p.extra?.workoutReminderEnabled == true
            reminderHour = p.extra?.workoutReminderHour ?: 8
        }
    }

    suspend fun saveReminderPrefs(enabled: Boolean, hour: Int) {
        if (!settings.isConfigured()) return
        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
        val newExtra = mutableMapOf<String, Any>()
        profile?.extra?.let { ex ->
            ex.stepsGoal?.let { newExtra["steps_goal"] = it }
            ex.sleepGoalH?.let { newExtra["sleep_goal_h"] = it }
            ex.vitalsOrder?.let { newExtra["vitals_order"] = it }
            ex.vitalsHidden?.let { newExtra["vitals_hidden"] = it }
        }
        newExtra["workout_reminder_enabled"] = enabled
        newExtra["workout_reminder_hour"] = hour
        try {
            withContext(Dispatchers.IO) {
                api.putProfile(ProfilePutBody(
                    birthDate = profile?.birthDate,
                    sex = profile?.sex,
                    heightCm = profile?.heightCm,
                    weightGoalKg = profile?.weightGoalKg,
                    restingHrBaseline = profile?.restingHrBaseline,
                    activityLevel = profile?.activityLevel,
                    extra = newExtra,
                ))
            }
            Timber.i("workout reminder saved: enabled=%s hour=%d", enabled, hour)
        } catch (e: Exception) {
            Timber.w(e, "save workout reminder failed")
            Toast.makeText(context, "Save failed: ${e.message?.take(80)}",
                Toast.LENGTH_SHORT).show()
        }
    }

    fun saveAndToast() {
        settings.backendUrl = url.trim()
        settings.bearerToken = token.trim()
        dirty = false
        Toast.makeText(
            context,
            if (settings.isConfigured()) "Saved — backend configured" else "Saved (URL and/or token blank)",
            Toast.LENGTH_SHORT,
        ).show()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MV.Bg),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = 80.dp),
            contentAlignment = Alignment.TopCenter,
        ) {
            BrandMark(
                dimension = 360.dp,
                heart = MV.BrandRed.copy(alpha = 0.05f),
                trace = MV.OnSurface.copy(alpha = 0.04f),
            )
        }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding(),
        contentPadding = PaddingValues(bottom = 32.dp),
    ) {
        // ── Top brand row — original left layout, slightly larger logo ──
        item {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 24.dp, end = 24.dp, top = 16.dp, bottom = 4.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    BrandMark(dimension = 32.dp)
                    Text(
                        "myvitals",
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = 0.4.sp,
                        color = MV.OnSurfaceVariant,
                    )
                }
                PagerDotsLocal(active = 1)
                Spacer(Modifier.width(48.dp))
            }
        }

        // ── Title ──
        item {
            Text(
                "Settings",
                fontSize = 32.sp,
                fontWeight = FontWeight.Normal,
                letterSpacing = (-0.6).sp,
                color = MV.OnSurface,
                modifier = Modifier.padding(start = 24.dp, end = 24.dp, top = 28.dp, bottom = 12.dp),
            )
        }

        // ── Connection ──
        item {
            Section(title = "Connection") {
                Card {
                    SectionField(label = "Backend URL", value = url, mono = false) {
                        url = it; dirty = (url != settings.backendUrl || token != settings.bearerToken)
                    }
                    Divider()
                    SectionField(label = "Ingest token", value = token, mono = true, isSecret = true) {
                        token = it; dirty = (url != settings.backendUrl || token != settings.bearerToken)
                    }
                    Divider()
                    ActionRow {
                        FilledPill(
                            label = "Save",
                            enabled = dirty,
                            onClick = ::saveAndToast,
                        )
                        Text(
                            text = if (dirty) "Unsaved changes" else "No changes",
                            fontSize = 13.sp,
                            color = MV.OnSurfaceVariant,
                        )
                    }
                }
            }
        }

        // ── Health Connect ──
        item {
            Section(title = "Health Connect") {
                Card {
                    val perms = hasPermissions()
                    StatusListItem(
                        label = "Health Connect",
                        ok = isHealthConnectAvailable,
                        detail = if (isHealthConnectAvailable) "Available on this device"
                                 else "Not available — install/update via Play Store",
                    )
                    Divider()
                    StatusListItem(
                        label = "Read permissions",
                        ok = perms,
                        detail = if (perms) "All required permissions granted"
                                 else "Missing — tap below to grant",
                    )
                    Divider()
                    ActionRow {
                        OutlinedPill(
                            label = if (perms) "Manage permissions" else "Grant permissions",
                            enabled = isHealthConnectAvailable,
                            onClick = onRequestPermissions,
                        )
                    }
                }
            }
        }

        // ── Sync ──
        item {
            Section(title = "Sync") {
                Card {
                    KvRow(
                        label = "Last sync",
                        value = settings.lastSyncInstant()?.let(::formatInstant) ?: "never",
                    )
                    Divider()
                    KvRow(
                        label = "Last success",
                        value = settings.lastSuccessInstant()?.let(::formatInstant) ?: "never",
                        valueColor = if (settings.permissionsLost) MV.Amber else null,
                    )
                    Divider()
                    KvRow(
                        label = "Status",
                        value = if (settings.permissionsLost) "perms revoked"
                                else if (settings.lastSuccessInstant() != null) "ok"
                                else "—",
                        valueColor = when {
                            settings.permissionsLost -> MV.Red
                            settings.lastSuccessInstant() != null -> MV.Green
                            else -> null
                        },
                    )
                    Divider()
                    ActionRow {
                        FilledPill(
                            label = "Sync now",
                            enabled = settings.isConfigured() && hasPermissions(),
                            onClick = {
                                onSyncNow()
                                Toast.makeText(context, "Sync queued", Toast.LENGTH_SHORT).show()
                            },
                        )
                    }
                    // When HC denies reads despite the app showing all
                    // permissions granted (the "permission ghost" state),
                    // the recovery path is in the Health Connect app —
                    // not myvitals' grant-prompt. Surface a deep-link
                    // button so the user can fix it without hunting.
                    if (settings.permissionsLost) {
                        Divider()
                        Column(
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                        ) {
                            Text(
                                "Health Connect is denying reads. The app shows all "
                                    + "permissions granted but HC itself is blocking — "
                                    + "open the Health Connect app, tap myvitals, and "
                                    + "toggle each permission off then back on.",
                                fontSize = 12.sp,
                                color = MV.OnSurfaceVariant,
                                modifier = Modifier.padding(bottom = 10.dp),
                            )
                            FilledPill(
                                label = "Open Health Connect",
                                enabled = true,
                                onClick = {
                                    runCatching {
                                        // Settings → Health Connect app permissions
                                        // (works when the HC app is installed; the
                                        // Settings activity is the official entry
                                        // point for permission management).
                                        val intent = android.content.Intent(
                                            "android.health.connect.action.HEALTH_HOME_SETTINGS",
                                        ).apply {
                                            flags = android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                                        }
                                        context.startActivity(intent)
                                    }.recoverCatching {
                                        // Fallback: open the HC app directly
                                        val pkg = "com.google.android.apps.healthdata"
                                        val intent = context.packageManager
                                            .getLaunchIntentForPackage(pkg)
                                        if (intent != null) {
                                            intent.flags =
                                                android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                                            context.startActivity(intent)
                                        } else {
                                            Toast.makeText(
                                                context,
                                                "Health Connect app not found",
                                                Toast.LENGTH_LONG,
                                            ).show()
                                        }
                                    }
                                },
                            )
                        }
                    }
                    Divider()
                    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp)) {
                        Text(
                            "Backfill historical data",
                            fontSize = 13.sp,
                            color = MV.OnSurfaceVariant,
                            letterSpacing = 0.2.sp,
                            modifier = Modifier.padding(bottom = 10.dp),
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            BackfillChip("7 days") { onBackfill(7); toast(context, "Backfilling 7 days…") }
                            BackfillChip("30 days") { onBackfill(30); toast(context, "Backfilling 30 days…") }
                            BackfillChip("1 year") { onBackfill(365); toast(context, "Backfilling 1 year…") }
                            BackfillChip("All (10y)") { onBackfill(3650); toast(context, "Backfilling ALL — may take a while") }
                        }
                    }
                }
            }
        }

        // ── Workout reminders ──
        item {
            Section(title = "Workout reminders") {
                Card {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 14.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("Daily reminder", fontSize = 15.sp, color = MV.OnSurface)
                            Text(
                                "Notification on workout days with split + first 3 exercises.",
                                fontSize = 12.sp, color = MV.OnSurfaceVariant,
                            )
                        }
                        Switch(
                            checked = reminderEnabled,
                            onCheckedChange = { v ->
                                reminderEnabled = v
                                scope.launch { saveReminderPrefs(v, reminderHour) }
                            },
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = MV.OnSurface,
                                checkedTrackColor = MV.BrandRed,
                            ),
                        )
                    }
                    if (reminderEnabled) {
                        Divider()
                        var menuOpen by remember { mutableStateOf(false) }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .pointerInput(Unit) {
                                    detectTapGestures(onTap = { menuOpen = true })
                                }
                                .padding(horizontal = 16.dp, vertical = 14.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("Time", fontSize = 15.sp, color = MV.OnSurface)
                            Box {
                                Text(
                                    String.format("%02d:00", reminderHour),
                                    fontSize = 14.sp, color = MV.OnSurfaceVariant,
                                    style = androidx.compose.ui.text.TextStyle(
                                        fontFeatureSettings = "tnum"),
                                )
                                DropdownMenu(
                                    expanded = menuOpen,
                                    onDismissRequest = { menuOpen = false },
                                ) {
                                    (5..21).forEach { h ->
                                        DropdownMenuItem(
                                            text = { Text(String.format("%02d:00", h)) },
                                            onClick = {
                                                reminderHour = h
                                                menuOpen = false
                                                scope.launch {
                                                    saveReminderPrefs(reminderEnabled, h)
                                                }
                                            },
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ── Diagnostics ──
        item {
            Section(title = "Diagnostics") {
                Card {
                    ListLinkRow(label = "View on-device logs", onClick = onOpenLogs)
                    Divider()
                    ListLinkRow(label = "Upload logs to backend") {
                        onSyncLogs()
                        Toast.makeText(context, "Log upload queued", Toast.LENGTH_SHORT).show()
                    }
                    Divider()
                    ListLinkRow(label = "Clear sync buffer", destructive = true) {
                        showClearBufferConfirm = true
                    }
                }
            }
        }

        // ── Backend updates (UPDATE-2) ──
        item {
            Section(title = "Backend updates") {
                Card {
                    KvRow(
                        label = "Running",
                        value = backendCheck?.current ?: "—",
                    )
                    Divider()
                    KvRow(
                        label = "Latest release",
                        value = backendCheck?.latest?.let { "v$it" } ?: "—",
                    )
                    backendCheck?.latestPublishedAt?.let { ts ->
                        Divider()
                        val rel = remember(ts) {
                            runCatching {
                                val inst = Instant.parse(ts)
                                DateTimeFormatter.ofPattern("MMM d, HH:mm")
                                    .withZone(ZoneId.systemDefault())
                                    .format(inst)
                            }.getOrDefault(ts)
                        }
                        KvRow(label = "Published", value = rel)
                    }
                    Divider()
                    ListLinkRow(
                        label = if (backendBusy) "Checking…" else "Check for updates",
                    ) {
                        if (backendBusy) return@ListLinkRow
                        backendBusy = true
                        backendApplyMsg = ""
                        scope.launch {
                            try {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                backendCheck = withContext(Dispatchers.IO) { api.updateCheck() }
                            } catch (e: Exception) {
                                Timber.w(e, "backend update check failed")
                                backendApplyMsg = "Check failed: ${e.message?.take(80)}"
                            } finally {
                                backendBusy = false
                            }
                        }
                    }
                    val check = backendCheck
                    if (check?.updateAvailable == true) {
                        Divider()
                        ActionRow {
                            FilledPill(
                                label = "Apply v${check.latest}",
                                onClick = {
                                    if (backendBusy) return@FilledPill
                                    backendBusy = true
                                    backendApplyMsg = ""
                                    scope.launch {
                                        try {
                                            val api = BackendClient.create(
                                                settings.backendUrl, settings.bearerToken,
                                            )
                                            val r = withContext(Dispatchers.IO) {
                                                api.updateApply()
                                            }
                                            backendApplyMsg = if (r.triggered) {
                                                "Update triggered. Backend will restart in ~60s."
                                            } else {
                                                r.hint ?: r.error ?: "Trigger failed."
                                            }
                                            // Wait a beat, re-check
                                            kotlinx.coroutines.delay(30_000)
                                            val again = withContext(Dispatchers.IO) {
                                                runCatching { api.updateCheck() }.getOrNull()
                                            }
                                            if (again != null) backendCheck = again
                                        } catch (e: Exception) {
                                            backendApplyMsg = "Apply failed: ${e.message?.take(80)}"
                                        } finally {
                                            backendBusy = false
                                        }
                                    }
                                },
                            )
                        }
                    }
                    if (backendApplyMsg.isNotBlank()) {
                        Divider()
                        Text(
                            backendApplyMsg,
                            fontSize = 13.sp,
                            color = MV.OnSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                        )
                    }
                    check?.error?.let { err ->
                        Divider()
                        Text(
                            "Couldn't check GitHub: $err",
                            fontSize = 12.sp, color = MV.OnSurfaceDim,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                        )
                    }
                }
            }
        }

        // ── About ──
        item {
            Section(title = "About") {
                Card {
                    KvRow(label = "Version", value = "${BuildConfig.VERSION_NAME} · build ${BuildConfig.VERSION_CODE}")
                    Divider()
                    ListLinkRow(label = "Check for updates") {
                        updateStatus = "Checking…"
                        pendingRelease = null
                        scope.launch {
                            val release = UpdateChecker.checkForUpdate()
                            if (release == null) updateStatus = "Up to date."
                            else {
                                pendingRelease = release
                                updateStatus = "Update ${release.tagName} available."
                            }
                        }
                    }
                    pendingRelease?.let { release ->
                        val asset = release.assets.firstOrNull { it.name.endsWith(".apk") }
                        if (asset != null && apkState is ApkDownloader.State.Idle) {
                            Divider()
                            ActionRow {
                                FilledPill(
                                    label = "Download ${release.tagName}",
                                    onClick = {
                                        ApkDownloader.start(
                                            context, asset.browserDownloadUrl, asset.name,
                                        )
                                    },
                                )
                            }
                        }
                    }
                    // Inline APK download progress — replaces the old
                    // full-screen UpdateInstallerActivity.
                    when (val s = apkState) {
                        is ApkDownloader.State.Pending -> {
                            Divider()
                            ApkProgressRow(
                                label = "Starting download…",
                                progress = 0f, determinate = false,
                            )
                        }
                        is ApkDownloader.State.Downloading -> {
                            Divider()
                            val pct = (s.progress * 100).toInt()
                            val label = if (s.bytesTotal > 0)
                                "Downloading… $pct%  ·  ${fmtMb(s.bytesDownloaded)} / ${fmtMb(s.bytesTotal)}"
                            else
                                "Downloading… ${fmtMb(s.bytesDownloaded)}"
                            ApkProgressRow(
                                label = label,
                                progress = s.progress,
                                determinate = s.bytesTotal > 0,
                            )
                            ActionRow {
                                FilledPill(
                                    label = "Cancel",
                                    onClick = { ApkDownloader.cancelInflight(context) },
                                )
                            }
                        }
                        is ApkDownloader.State.Installing -> {
                            Divider()
                            Text(
                                "Download complete. Tap Install to launch the system installer.",
                                fontSize = 13.sp, color = MV.OnSurfaceVariant,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                            )
                            ActionRow {
                                FilledPill(
                                    label = "Install",
                                    onClick = { ApkDownloader.launchInstaller(context) },
                                )
                            }
                        }
                        is ApkDownloader.State.Failed -> {
                            Divider()
                            Text(
                                s.message,
                                fontSize = 13.sp, color = MV.Red,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                            )
                            ActionRow {
                                FilledPill(
                                    label = "Dismiss",
                                    onClick = { ApkDownloader.dismiss() },
                                )
                            }
                        }
                        else -> { /* idle — show nothing extra */ }
                    }
                    if (updateStatus.isNotBlank() && pendingRelease == null) {
                        Divider()
                        Text(
                            updateStatus,
                            fontSize = 13.sp,
                            color = MV.OnSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                        )
                    }
                }
            }
        }

        // ── Tagline ──
        item {
            Text(
                "self-hosted · personal · health",
                fontSize = 12.sp,
                color = MV.OnSurfaceDim,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 16.dp),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
    }   // Close watermark Box wrapper
}

// ── APK download progress row (inline) ──────────────────────────

@Composable
private fun ApkProgressRow(label: String, progress: Float, determinate: Boolean) {
    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text(label, fontSize = 13.sp, color = MV.OnSurface)
        Spacer(Modifier.height(8.dp))
        if (determinate) {
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier.fillMaxWidth().height(4.dp),
                color = MV.BrandRed,
                trackColor = MV.SurfaceContainer,
            )
        } else {
            LinearProgressIndicator(
                modifier = Modifier.fillMaxWidth().height(4.dp),
                color = MV.BrandRed,
                trackColor = MV.SurfaceContainer,
            )
        }
    }
}

private fun fmtMb(bytes: Long): String {
    if (bytes <= 0) return "0.0 MB"
    return String.format(java.util.Locale.US, "%.1f MB", bytes / 1_048_576.0)
}

// ── Layout primitives ───────────────────────────────────────────

@Composable
private fun Section(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 20.dp)) {
        Text(
            text = title.uppercase(),
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
            letterSpacing = 2.4.sp,
            color = MV.OnSurfaceVariant,
            modifier = Modifier.padding(start = 8.dp, bottom = 10.dp),
        )
        content()
    }
}

@Composable
private fun Card(content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(MV.SurfaceContainerLow)
            .border(1.dp, MV.OutlineVariant, RoundedCornerShape(20.dp)),
        content = content,
    )
}

@Composable
private fun Divider() {
    HorizontalDivider(
        color = MV.OutlineVariant,
        thickness = 1.dp,
        modifier = Modifier.padding(horizontal = 16.dp),
    )
}

@Composable
private fun SectionField(
    label: String,
    value: String,
    mono: Boolean = false,
    isSecret: Boolean = false,
    onChange: (String) -> Unit,
) {
    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp)) {
        Text(
            label,
            fontSize = 12.sp,
            color = MV.OnSurfaceVariant,
            letterSpacing = 0.3.sp,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        OutlinedTextField(
            value = value,
            onValueChange = onChange,
            singleLine = true,
            keyboardOptions = if (isSecret) KeyboardOptions(keyboardType = KeyboardType.Password) else KeyboardOptions.Default,
            colors = TextFieldDefaults.colors(
                focusedContainerColor = Color.Transparent,
                unfocusedContainerColor = Color.Transparent,
                focusedIndicatorColor = MV.Amber,
                unfocusedIndicatorColor = MV.Outline,
            ),
            textStyle = androidx.compose.ui.text.TextStyle(
                color = MV.OnSurface,
                fontSize = 15.sp,
                fontFamily = if (mono) androidx.compose.ui.text.font.FontFamily.Monospace
                             else androidx.compose.ui.text.font.FontFamily.Default,
                letterSpacing = if (mono) 0.2.sp else 0.sp,
            ),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun KvRow(label: String, value: String, valueColor: Color? = null) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, fontSize = 14.sp, color = MV.OnSurface)
        Text(
            value,
            fontSize = 14.sp,
            color = valueColor ?: MV.OnSurfaceVariant,
            style = androidx.compose.ui.text.TextStyle(fontFeatureSettings = "tnum"),
        )
    }
}

@Composable
private fun ListLinkRow(
    label: String,
    destructive: Boolean = false,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .pointerInput(Unit) { detectTapGestures(onTap = { onClick() }) }
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, fontSize = 15.sp,
            color = if (destructive) MV.Red else MV.OnSurface)
        Text("›", fontSize = 18.sp, color = MV.OnSurfaceDim)
    }
}

@Composable
private fun StatusListItem(label: String, ok: Boolean, detail: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .clip(RoundedCornerShape(50))
                .background(if (ok) MV.Green else MV.Red),
        )
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(label, fontSize = 15.sp, color = MV.OnSurface)
            Text(
                detail,
                fontSize = 13.sp,
                color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
    }
}

@Composable
private fun ActionRow(content: @Composable () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) { content() }
}

@Composable
private fun FilledPill(
    label: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(if (enabled) MV.BrandRed else MV.SurfaceContainerHigh)
            .pointerInput(enabled) { if (enabled) detectTapGestures(onTap = { onClick() }) }
            .padding(horizontal = 22.dp, vertical = 10.dp),
    ) {
        Text(
            label,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = if (enabled) Color.White else MV.OnSurfaceDim,
            letterSpacing = 0.3.sp,
        )
    }
}

@Composable
private fun OutlinedPill(
    label: String,
    enabled: Boolean = true,
    danger: Boolean = false,
    onClick: () -> Unit,
) {
    val color = if (!enabled) MV.OnSurfaceDim else if (danger) MV.Amber else MV.OnSurface
    val borderColor = if (!enabled) MV.OutlineVariant else if (danger) MV.Amber else MV.Outline
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .border(1.dp, borderColor, RoundedCornerShape(50))
            .pointerInput(enabled) { if (enabled) detectTapGestures(onTap = { onClick() }) }
            .padding(horizontal = 18.dp, vertical = 9.dp),
    ) {
        Text(
            label,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = color,
            letterSpacing = 0.2.sp,
        )
    }
}

@Composable
private fun BackfillChip(label: String, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .border(1.dp, MV.Outline, RoundedCornerShape(50))
            .pointerInput(Unit) { detectTapGestures(onTap = { onClick() }) }
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text(
            label,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
            color = MV.OnSurfaceVariant,
            letterSpacing = 0.2.sp,
        )
    }
}

@Composable
private fun PagerDotsLocal(active: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        for (i in 0..1) {
            val isActive = i == active
            Box(
                modifier = Modifier
                    .height(6.dp)
                    .width(if (isActive) 18.dp else 6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(
                        if (isActive) MV.OnSurface.copy(alpha = 0.95f)
                        else MV.OnSurfaceDim.copy(alpha = 0.5f),
                    ),
            )
        }
    }
}

private fun toast(ctx: android.content.Context, msg: String) {
    Toast.makeText(ctx, msg, Toast.LENGTH_SHORT).show()
}

private val formatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("MMM d, h:mm a").withZone(ZoneId.systemDefault())

private fun formatInstant(instant: Instant): String = formatter.format(instant)
