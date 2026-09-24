package app.myvitals.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.AiConfigIn
import app.myvitals.sync.AiConfigOut
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * AI (SETTINGS-C). Mirrors web `settings/SettingsAi.vue`.
 *
 * On/off, model, tone, the daily call limit with today's usage, and the
 * weekly digest — each change is one partial POST to `/ai/config`, which
 * leaves every field it is not sent alone. Usage and limit are the server's
 * numbers, rendered verbatim.
 *
 * Declared web-only: entering or clearing the API key / subscription token,
 * choosing the provider, standing instructions, and the payload preview.
 * A secret typed on a phone keyboard, and a JSON preview on a phone screen,
 * are both worse than the same thing in a browser.
 */
@Composable
fun AiSettingsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var cfg by remember { mutableStateOf<AiConfigOut?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var saveError by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        try {
            cfg = settings.call { aiConfig() }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "ai config load failed")
            error = e.settingsMessage()
        } finally {
            loading = false
        }
    }
    LaunchedEffect(Unit) { load() }

    AiSettingsContent(
        cfg = cfg, loading = loading, refreshing = refreshing, error = error,
        saving = saving, saveError = saveError,
        onChange = { patch ->
            scope.launch {
                saving = true; saveError = null
                try {
                    cfg = settings.call { aiUpdateConfig(patch) }
                } catch (e: Exception) {
                    Timber.w(e, "ai config save failed")
                    saveError = e.settingsMessage()
                } finally {
                    saving = false
                }
            }
        },
        onBack = onBack,
        onRefresh = { scope.launch { refreshing = true; try { load() } finally { refreshing = false } } },
    )
}

@Composable
fun AiSettingsContent(
    cfg: AiConfigOut?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    saving: Boolean,
    saveError: String?,
    onChange: (AiConfigIn) -> Unit,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    NeonScreen(
        title = "AI",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (cfg == null) {
            if (error != null && !loading) {
                NeonErrorBanner(error, title = "Couldn't load AI settings") { onRefresh() }
            } else {
                SettingsSkeleton(listOf(110.dp, 150.dp, 120.dp))
            }
            WebOnlyNote(AI_WEB_ONLY)
            return@NeonScreen
        }
        if (error != null) {
            NeonErrorBanner(error, title = "Couldn't refresh — showing the last settings") { onRefresh() }
        }
        if (saveError != null) {
            NeonErrorBanner(saveError, title = "Couldn't save that change", actionLabel = "Tap to reload") { onRefresh() }
        }
        val credentialed = if (cfg.provider == "claude_cli") cfg.cliTokenSet else cfg.apiKeySet ||
            cfg.provider in setOf("openai_compatible", "ollama")

        NeonEyebrow("Status")
        SettingsCard {
            SettingsSwitchRow(
                "AI narration",
                if (credentialed) "Coach cards, summaries and suggestions."
                else "No key is set — add one on the web before turning this on.",
                cfg.enabled, { onChange(AiConfigIn(enabled = it)) }, enabled = !saving,
            )
            SettingsDivider()
            SettingsKv("Provider", providerLabel(cfg.provider))
            SettingsKv(
                if (cfg.provider == "claude_cli") "Subscription token" else "API key",
                if (credentialed) "Set" else "Not set",
                valueColor = if (credentialed) NeonMV.Lime else NeonMV.Amber,
            )
        }

        NeonEyebrow("Model")
        SettingsCard {
            val models = AI_MODELS.toMutableList()
            if (models.none { it.first == cfg.model } && cfg.model.isNotBlank()) models += cfg.model to cfg.model
            SettingsChoice(null, models, cfg.model, { onChange(AiConfigIn(model = it)) },
                accent = NeonMV.Magenta, enabled = !saving)
            SettingsNote("Haiku is plenty for the structured cards this app asks for.")
        }

        NeonEyebrow("Tone")
        SettingsCard {
            SettingsChoice(
                null,
                listOf("supportive" to "Supportive", "blunt" to "Blunt", "data-only" to "Data only"),
                cfg.tone, { onChange(AiConfigIn(tone = it)) }, accent = NeonMV.Magenta, enabled = !saving,
            )
        }

        NeonEyebrow("Usage")
        SettingsCard {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.Bottom) {
                        NeonNumber("${cfg.callsToday}", size = 26)
                        Text(" of ${cfg.dailyCallLimit} calls today", color = NeonMV.Muted,
                            fontSize = 13.sp, modifier = Modifier.padding(bottom = 4.dp))
                    }
                    Text("The daily limit stops a runaway client from running up the bill.",
                        color = NeonMV.Muted, fontSize = 11.sp)
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 14.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Daily limit", color = NeonMV.Ink, fontSize = 14.sp, modifier = Modifier.weight(1f))
                NeonButton("−5", { onChange(AiConfigIn(dailyCallLimit = (cfg.dailyCallLimit - 5).coerceAtLeast(1))) },
                    filled = false, accent = NeonMV.Cyan, enabled = !saving && cfg.dailyCallLimit > 1)
                NeonNumber("${cfg.dailyCallLimit}", size = 20, color = NeonMV.Cyan)
                NeonButton("+5", { onChange(AiConfigIn(dailyCallLimit = (cfg.dailyCallLimit + 5).coerceAtMost(200))) },
                    filled = false, accent = NeonMV.Cyan, enabled = !saving && cfg.dailyCallLimit < 200)
            }
        }

        NeonEyebrow("Digest")
        SettingsCard {
            SettingsSwitchRow(
                "Weekly digest", "A written summary of your week, Sunday evenings.",
                cfg.weeklyDigestEnabled, { onChange(AiConfigIn(weeklyDigestEnabled = it)) },
                enabled = !saving,
            )
        }
        WebOnlyNote(AI_WEB_ONLY)
        Spacer(Modifier.height(24.dp))
    }
}

private const val AI_WEB_ONLY =
    "Adding or removing a key, choosing the provider, standing instructions and the " +
        "payload preview are on the web."

internal fun providerLabel(p: String): String = when (p) {
    "anthropic" -> "Anthropic API"
    "claude_cli" -> "Claude subscription"
    "openai_compatible" -> "OpenAI-compatible"
    "ollama" -> "Ollama"
    else -> p
}
