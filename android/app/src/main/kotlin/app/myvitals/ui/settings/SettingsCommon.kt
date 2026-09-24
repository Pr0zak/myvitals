package app.myvitals.ui.settings

import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowRight
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendApi
import app.myvitals.sync.BackendClient
import app.myvitals.ui.common.ShimmerBlock
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumberFamily
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime

/*
 * SETTINGS-C — the pieces every Settings page shares, so seven pages read as
 * one surface instead of seven hand-rolled lists. Built on the neon kit
 * (NeonMV tokens, NeonCardShape); the classic MV palette the old single
 * Settings screen used is gone from this package entirely.
 *
 * Colour rules, applied everywhere below: Lime = working, Amber = needs
 * attention (a stale feed or a failed request is a caution, not a crisis),
 * Muted = not a fault (not set up, recorded when you choose). Rose
 * (NeonMV.Bad) is not used anywhere in Settings.
 */

/** Nav-graph routes for the Settings pages. */
object SettingsRoutes {
    const val HOME = "settings"
    const val YOU = "settings/you"
    const val DISPLAY = "settings/display"
    const val CONNECTION = "settings/connection"
    const val INTEGRATIONS = "settings/integrations"
    const val AI = "settings/ai"
    const val DATA = "settings/data"
    const val ABOUT = "settings/about"
    const val TILE_ORDER = "settings/tile-order"
}

/** Run one API call on IO against the configured backend. */
internal suspend fun <T> SettingsRepository.call(block: suspend BackendApi.() -> T): T {
    check(isConfigured()) { "No server set — open Connection & sync." }
    val api = BackendClient.create(backendUrl, bearerToken)
    return withContext(Dispatchers.IO) { api.block() }
}

/** A one-line reason a request failed, in words a person can act on. */
internal fun Throwable.settingsMessage(): String {
    val m = message.orEmpty()
    return when {
        this is IllegalStateException && m.startsWith("No server") -> m
        this is retrofit2.HttpException && code() == 401 ->
            "The server rejected the access key (401)."
        this is retrofit2.HttpException -> "The server answered ${code()}."
        this is java.net.UnknownHostException -> "Can't find the server — check the address."
        this is java.net.SocketTimeoutException -> "The server took too long to answer."
        this is java.io.IOException -> "Can't reach the server."
        else -> m.take(120).ifBlank { javaClass.simpleName }
    }
}

// ── Time formatting (presentation of server timestamps only) ──────────

internal fun parseInstant(iso: String?): Instant? = iso?.let {
    runCatching { OffsetDateTime.parse(it).toInstant() }.getOrNull()
        ?: runCatching { Instant.parse(it) }.getOrNull()
}

/** "just now" / "12m ago" / "5h ago" / "3d ago"; null → "never". */
internal fun relAge(at: Instant?, now: Instant): String {
    if (at == null) return "never"
    val s = Duration.between(at, now).seconds.coerceAtLeast(0)
    return when {
        s < 60 -> "just now"
        s < 3600 -> "${s / 60}m ago"
        s < 48 * 3600 -> "${s / 3600}h ago"
        else -> "${s / 86_400}d ago"
    }
}

/** Server-supplied `age_hours` as "12m" / "5h" / "3d"; null → "never". */
internal fun fmtAgeHours(h: Double?): String = when {
    h == null -> "never"
    h < 1 -> "${(h * 60).toInt().coerceAtLeast(1)}m"
    h < 48 -> "${h.toInt()}h"
    else -> "${(h / 24).toInt()}d"
}

// ── Layout ────────────────────────────────────────────────────────────

/** A group of rows on one card. */
@Composable
fun SettingsCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape),
        content = content,
    )
}

@Composable
fun SettingsDivider() {
    HorizontalDivider(color = NeonMV.Line, thickness = 1.dp,
        modifier = Modifier.padding(horizontal = 16.dp))
}

/**
 * One navigable row: icon, title, a live one-line summary, chevron. At
 * least 56dp tall — the old list's 14dp-padded text rows were ~44dp.
 */
@Composable
fun SettingsNavRow(
    icon: ImageVector,
    accent: Color,
    title: String,
    summary: String,
    summaryColor: Color = NeonMV.Muted,
    trailing: @Composable (() -> Unit)? = null,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 64.dp)
            .clickable(onClickLabel = "Open $title", role = Role.Button, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(38.dp).clip(RoundedCornerShape(12.dp))
                .background(accent.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(20.dp))
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            Text(summary, color = summaryColor, fontSize = 12.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
        }
        trailing?.let { Spacer(Modifier.width(8.dp)); it() }
        Icon(Icons.AutoMirrored.Outlined.KeyboardArrowRight, contentDescription = null,
            tint = NeonMV.Muted, modifier = Modifier.size(22.dp))
    }
}

/** A label on the left, a value on the right. */
@Composable
fun SettingsKv(label: String, value: String, valueColor: Color = NeonMV.Muted) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = NeonMV.Ink, fontSize = 14.sp, modifier = Modifier.weight(1f))
        Text(value, color = valueColor, fontSize = 14.sp, fontFamily = NeonNumberFamily)
    }
}

/** A toggle with a title and an optional one-line explanation. */
@Composable
fun SettingsSwitchRow(
    title: String,
    subtitle: String?,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
    enabled: Boolean = true,
) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .clickable(enabled = enabled, role = Role.Switch) { onChange(!checked) }
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, color = if (enabled) NeonMV.Ink else NeonMV.Muted, fontSize = 15.sp)
            subtitle?.let { Text(it, color = NeonMV.Muted, fontSize = 12.sp) }
        }
        Switch(
            checked = checked, onCheckedChange = onChange, enabled = enabled,
            colors = SwitchDefaults.colors(
                checkedThumbColor = NeonMV.OnAccent,
                checkedTrackColor = NeonMV.Lime,
                uncheckedThumbColor = NeonMV.Muted,
                uncheckedTrackColor = NeonMV.Track,
                uncheckedBorderColor = NeonMV.Line,
            ),
        )
    }
}

/** A labelled single-choice chip group. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsChoice(
    label: String?,
    options: List<Pair<String, String>>,
    selected: String?,
    onSelect: (String) -> Unit,
    accent: Color = NeonMV.Cyan,
    enabled: Boolean = true,
) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        label?.let {
            Text(it, color = NeonMV.Ink, fontSize = 14.sp)
            Spacer(Modifier.height(8.dp))
        }
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            for ((value, text) in options) {
                NeonChip(text, on = value == selected, accent = accent, enabled = enabled) {
                    if (value != selected) onSelect(value)
                }
            }
        }
    }
}

@Composable
fun NeonChip(
    text: String,
    on: Boolean,
    accent: Color = NeonMV.Cyan,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(999.dp)
    Box(
        Modifier
            .heightIn(min = 40.dp)
            .clip(shape)
            .background(if (on) accent.copy(alpha = 0.18f) else NeonMV.CardHigh)
            .border(1.dp, if (on) accent.copy(alpha = 0.6f) else NeonMV.Line, shape)
            .clickable(enabled = enabled, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 9.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, color = if (on) accent else if (enabled) NeonMV.Ink else NeonMV.Muted,
            fontSize = 13.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/** Filled (primary) or outlined button, ≥44dp. */
@Composable
fun NeonButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    filled: Boolean = true,
    accent: Color = NeonMV.Lime,
) {
    val shape = RoundedCornerShape(999.dp)
    Box(
        modifier
            .heightIn(min = 44.dp)
            .clip(shape)
            .then(
                if (filled) Modifier.background(if (enabled) accent else NeonMV.Track)
                else Modifier.border(1.dp, if (enabled) accent.copy(alpha = 0.7f) else NeonMV.Line, shape)
            )
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = 18.dp, vertical = 11.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = when {
                !enabled -> NeonMV.Muted
                filled -> NeonMV.OnAccent
                else -> accent
            },
            fontSize = 14.sp, fontWeight = FontWeight.Bold, maxLines = 1,
        )
    }
}

/** Small rounded status label. */
@Composable
fun StatusPill(text: String, color: Color) {
    Box(
        Modifier.clip(RoundedCornerShape(999.dp)).background(color.copy(alpha = 0.16f))
            .border(1.dp, color.copy(alpha = 0.45f), RoundedCornerShape(999.dp))
            .padding(horizontal = 9.dp, vertical = 3.dp),
    ) {
        Text(text, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold, maxLines = 1)
    }
}

/** Muted explanatory text inside a card. */
@Composable
fun SettingsNote(text: String, modifier: Modifier = Modifier, color: Color = NeonMV.Muted) {
    Text(text, color = color, fontSize = 12.sp, lineHeight = 17.sp,
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp))
}

/**
 * A declared web-only capability. Said once, plainly, where the missing
 * control would be — so its absence reads as a decision, not a bug.
 */
@Composable
fun WebOnlyNote(text: String) {
    Row(
        Modifier.fillMaxWidth().padding(bottom = 12.dp)
            .clip(NeonCardShape).background(NeonMV.Periwinkle.copy(alpha = 0.08f))
            .border(1.dp, NeonMV.Periwinkle.copy(alpha = 0.25f), NeonCardShape)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(Icons.Outlined.Language, contentDescription = null, tint = NeonMV.Periwinkle,
            modifier = Modifier.size(18.dp).padding(top = 1.dp))
        Spacer(Modifier.width(10.dp))
        Text(text, color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 17.sp)
    }
}

/**
 * A labelled text field on the neon palette. [secret] masks the value
 * and adds a reveal toggle with a proper content description — the old
 * token field set KeyboardType.Password but never masked, so the key sat
 * on screen in plain text.
 */
@Composable
fun SettingsTextField(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String? = null,
    suffix: String? = null,
    help: String? = null,
    error: String? = null,
    keyboardType: KeyboardType = KeyboardType.Text,
    mono: Boolean = false,
    secret: Boolean = false,
    secretName: String = label,
    horizontalPadding: Dp = 16.dp,
) {
    var revealed by remember { mutableStateOf(false) }
    Column(modifier.padding(horizontal = horizontalPadding, vertical = 8.dp)) {
        Text(label, color = NeonMV.Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(bottom = 4.dp))
        OutlinedTextField(
            value = value,
            onValueChange = onChange,
            singleLine = true,
            isError = error != null,
            placeholder = placeholder?.let { { Text(it, color = NeonMV.Muted, fontSize = 14.sp) } },
            suffix = suffix?.let { { Text(it, color = NeonMV.Muted, fontSize = 13.sp) } },
            keyboardOptions = KeyboardOptions(
                keyboardType = if (secret) KeyboardType.Password else keyboardType,
                autoCorrectEnabled = false,
            ),
            visualTransformation = if (secret && !revealed)
                androidx.compose.ui.text.input.PasswordVisualTransformation()
            else androidx.compose.ui.text.input.VisualTransformation.None,
            trailingIcon = if (secret) {
                {
                    androidx.compose.material3.IconButton(onClick = { revealed = !revealed }) {
                        Icon(
                            if (revealed) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility,
                            contentDescription = if (revealed) "Hide $secretName" else "Show $secretName",
                            tint = NeonMV.Muted,
                        )
                    }
                }
            } else null,
            textStyle = androidx.compose.ui.text.TextStyle(
                color = NeonMV.Ink, fontSize = 15.sp,
                fontFamily = if (mono) androidx.compose.ui.text.font.FontFamily.Monospace
                else androidx.compose.ui.text.font.FontFamily.Default,
            ),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = NeonMV.Cyan,
                unfocusedBorderColor = NeonMV.Line,
                errorBorderColor = NeonMV.Amber,
                cursorColor = NeonMV.Cyan,
                focusedContainerColor = NeonMV.CardHigh,
                unfocusedContainerColor = NeonMV.CardHigh,
                errorContainerColor = NeonMV.CardHigh,
            ),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth(),
        )
        when {
            error != null -> Text(error, color = NeonMV.Amber, fontSize = 11.sp,
                modifier = Modifier.padding(top = 3.dp))
            help != null -> Text(help, color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 15.sp,
                modifier = Modifier.padding(top = 3.dp))
        }
    }
}

/** Hour-of-day dropdown ("08:00"). */
@Composable
fun HourPicker(
    label: String,
    hour: Int,
    hours: IntRange,
    onPick: (Int) -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
) {
    var open by remember { mutableStateOf(false) }
    Row(
        modifier.fillMaxWidth().heightIn(min = 52.dp)
            .clickable(enabled = enabled, onClickLabel = "Choose $label") { open = true }
            .padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = if (enabled) NeonMV.Ink else NeonMV.Muted, fontSize = 14.sp)
        Box {
            Text("%02d:00".format(hour), color = if (enabled) NeonMV.Cyan else NeonMV.Muted,
                fontSize = 14.sp, fontFamily = NeonNumberFamily, fontWeight = FontWeight.Bold)
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                for (h in hours) {
                    DropdownMenuItem(
                        text = { Text("%02d:00".format(h)) },
                        onClick = { open = false; onPick(h) },
                    )
                }
            }
        }
    }
}

/** Confirmation dialog for anything slow, destructive or disruptive. */
@Composable
fun SettingsConfirm(
    title: String,
    text: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = NeonMV.CardHigh,
        titleContentColor = NeonMV.Ink,
        textContentColor = NeonMV.Muted,
        title = { Text(title, fontWeight = FontWeight.Bold) },
        text = { Text(text, lineHeight = 19.sp) },
        confirmButton = {
            TextButton(onClick = { onDismiss(); onConfirm() }) {
                Text(confirmLabel, color = NeonMV.Amber, fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = NeonMV.Ink) }
        },
    )
}

/** Loading placeholder: a stack of shimmering card-shaped blocks. */
@Composable
fun SettingsSkeleton(heights: List<Dp> = listOf(120.dp, 64.dp, 64.dp, 64.dp)) {
    for (h in heights) {
        ShimmerBlock(Modifier.fillMaxWidth(), height = h, cornerRadius = 18.dp)
        Spacer(Modifier.height(12.dp))
    }
}

/** Coloured dot used in status lists. */
@Composable
fun StatusDot(color: Color) {
    Box(Modifier.size(8.dp).clip(CircleShape).background(color))
}

/**
 * Open Health Connect's own permission screen. When HC denies reads while
 * the app believes every permission is granted (the "permission ghost"),
 * the fix is there, not in this app's grant prompt.
 */
fun openHealthConnectSettings(context: Context) {
    runCatching {
        context.startActivity(
            Intent("android.health.connect.action.HEALTH_HOME_SETTINGS")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }.recoverCatching {
        val launch = context.packageManager
            .getLaunchIntentForPackage("com.google.android.apps.healthdata")
            ?: error("Health Connect app not found")
        context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }.onFailure {
        Toast.makeText(context, "Health Connect app not found", Toast.LENGTH_LONG).show()
    }
}
