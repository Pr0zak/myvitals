package app.myvitals.ui.settings

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.myvitals.data.SettingsRepository
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Units & display (SETTINGS-C). Mirrors web `settings/SettingsDisplay.vue`.
 *
 * Units and the clock format are shared with the web (DISP-1): the server
 * holds them and a change here is pushed as a PARTIAL update, so it cannot
 * clobber a preference set on the other surface. The phone applies a choice
 * locally at once; when the server answers on open, its values win.
 *
 * The colour theme is web-only by declaration: the phone always renders the
 * Vitality Neon palette.
 */
@Composable
fun DisplaySettingsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
    onOpenTileOrder: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var imperial by remember { mutableStateOf(settings.unitsImperial) }
    var timeFormat by remember { mutableStateOf(settings.timeFormat) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }

    suspend fun reconcile() {
        try {
            val server = settings.call { displayPrefs() }
            imperial = server.units != "metric"
            timeFormat = server.timeFormat
            settings.unitsImperial = imperial      // also updates Units
            settings.timeFormat = timeFormat
            error = null
        } catch (e: Exception) {
            Timber.w(e, "display prefs load failed")
            error = e.settingsMessage()
        }
    }

    fun push(key: String, value: String) {
        scope.launch {
            try {
                settings.call { putDisplayPrefs(mapOf(key to value)) }
                error = null
            } catch (e: Exception) {
                // The local value already applied; say it didn't reach the
                // server rather than reverting what the user just tapped.
                Timber.w(e, "display pref push failed")
                error = "Saved on this phone, but not on the server: ${e.settingsMessage()}"
            }
        }
    }

    LaunchedEffect(Unit) { reconcile() }

    DisplaySettingsContent(
        imperial = imperial,
        timeFormat = timeFormat,
        error = error,
        refreshing = refreshing,
        onUnits = { v ->
            imperial = v == "imperial"
            settings.unitsImperial = imperial
            push("units", v)
        },
        onTimeFormat = { v ->
            timeFormat = v
            settings.timeFormat = v
            push("time_format", v)
        },
        onOpenTileOrder = onOpenTileOrder,
        onBack = onBack,
        onRefresh = { scope.launch { refreshing = true; try { reconcile() } finally { refreshing = false } } },
    )
}

@Composable
fun DisplaySettingsContent(
    imperial: Boolean,
    timeFormat: String,
    error: String?,
    refreshing: Boolean,
    onUnits: (String) -> Unit,
    onTimeFormat: (String) -> Unit,
    onOpenTileOrder: () -> Unit,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    NeonScreen(
        title = "Units & display",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (error != null) {
            NeonErrorBanner(error, title = "Couldn't sync display settings with the server") { onRefresh() }
        }
        NeonEyebrow("Units")
        SettingsCard {
            SettingsChoice(
                null,
                listOf("imperial" to "Imperial (lb, mi, °F)", "metric" to "Metric (kg, km, °C)"),
                if (imperial) "imperial" else "metric", onUnits,
            )
        }
        NeonEyebrow("Clock")
        SettingsCard {
            SettingsChoice(
                null,
                listOf("auto" to "Follow phone", "12h" to "12-hour", "24h" to "24-hour"),
                timeFormat, onTimeFormat,
            )
        }
        NeonEyebrow("Home screen")
        SettingsCard {
            SettingsNavRow(
                Icons.Outlined.Dashboard, NeonMV.Cyan, "Key metrics order",
                "Choose which tiles show on Body and in what order",
                onClick = onOpenTileOrder,
            )
        }
        WebOnlyNote("The colour theme is chosen on the web. This app always uses Vitality Neon.")
        Spacer(Modifier.height(24.dp))
    }
}
