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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
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
import app.myvitals.update.GitHubRelease
import app.myvitals.update.UpdateChecker
import app.myvitals.update.UpdateInstallerActivity
import kotlinx.coroutines.launch
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
    var dirty by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

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
                    ActionRow {
                        OutlinedPill(label = "Clear sync buffer", danger = true) {
                            onClearBuffer()
                            Toast.makeText(context, "Sync buffer cleared", Toast.LENGTH_SHORT).show()
                        }
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
                        if (asset != null) {
                            Divider()
                            ActionRow {
                                FilledPill(
                                    label = "Install ${release.tagName}",
                                    onClick = { UpdateInstallerActivity.start(context, asset.browserDownloadUrl, asset.name) },
                                )
                            }
                        }
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
private fun ListLinkRow(label: String, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .pointerInput(Unit) { detectTapGestures(onTap = { onClick() }) }
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, fontSize = 15.sp, color = MV.OnSurface)
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
