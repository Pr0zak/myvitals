package app.myvitals.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.CloudSync
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.BuildConfig
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.AiConfigOut
import app.myvitals.sync.DataHealth
import app.myvitals.sync.ImportJob
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.ServerVersion
import app.myvitals.sync.UpdateCheck
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import app.myvitals.ui.neon.NeonStatTile
import com.squareup.moshi.JsonClass
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.time.Instant

/**
 * Settings home (SETTINGS-C). Mirrors web `settings/SettingsHome.vue`.
 *
 *   hero   the server's data-health verdict — tone (Lime ok / Amber
 *          caution, never rose), its headline, and three tiles: last phone
 *          sync, integrations ok/total, server version with an "update
 *          available" chip. Tapping it opens Connection & sync.
 *   rows   seven pages, each with a LIVE one-line summary, in the same
 *          order and under the same names as the web.
 *
 * This replaced one classic-styled list about eleven screens tall that had
 * no back button, rendered failures as empty cards and kept leftover pager
 * dots from a retired two-page layout.
 *
 * Every section remembers whether it actually loaded. A summary that could
 * not be fetched says so ("Couldn't load") rather than falling back to a
 * default that reads as a fact about the user.
 */
@Composable
fun SettingsHomeScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
    onOpen: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf(SettingsHomeData()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "No server set — open Connection & sync to add one."
            loading = false
            return
        }
        coroutineScope {
            val h = async(Dispatchers.IO) { runCatching { settings.call { dataHealth() } } }
            val v = async(Dispatchers.IO) { runCatching { settings.call { serverVersion() } } }
            val u = async(Dispatchers.IO) { runCatching { settings.call { updateCheck() } } }
            val p = async(Dispatchers.IO) { runCatching { settings.call { profile() } } }
            val a = async(Dispatchers.IO) { runCatching { settings.call { aiConfig() } } }
            val j = async(Dispatchers.IO) { runCatching { settings.call { importJobs(1) } } }
            val prev = data
            val results = listOf(h.await(), v.await(), u.await(), p.await(), a.await(), j.await())
            val next = SettingsHomeData(
                health = h.await().getOrNull() ?: prev.health,
                version = v.await().getOrNull() ?: prev.version,
                update = u.await().getOrNull() ?: prev.update,
                profile = p.await().getOrNull() ?: prev.profile,
                ai = a.await().getOrNull() ?: prev.ai,
                lastImport = j.await().getOrNull()?.firstOrNull()
                    ?: if (j.await().isSuccess) null else prev.lastImport,
                jobsKnown = j.await().isSuccess || prev.jobsKnown,
            )
            data = next
            val firstFail = results.firstOrNull { it.isFailure }?.exceptionOrNull()
            error = when {
                results.all { it.isFailure } -> firstFail?.settingsMessage()
                h.await().isFailure -> "Couldn't check data health: ${firstFail?.settingsMessage()}"
                else -> null
            }
            if (results.any { it.isSuccess }) {
                runCatching { JsonCache.write(context, CACHE_KEY, SettingsHomeData::class.java, next) }
            }
        }
        loading = false
    }

    LaunchedEffect(Unit) {
        runCatching {
            JsonCache.read<SettingsHomeData>(context, CACHE_KEY, SettingsHomeData::class.java)
                ?.let { data = it.value; loading = false }
        }
        load()
    }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }

    SettingsHomeContent(
        data = data,
        local = LocalPrefs(
            imperial = settings.unitsImperial,
            timeFormat = settings.timeFormat,
            permissionsLost = settings.permissionsLost,
            lastSuccess = settings.lastSuccessInstant(),
            configured = settings.isConfigured(),
        ),
        loading = loading,
        refreshing = refreshing,
        error = error,
        now = Instant.now(),
        onBack = onBack,
        onOpen = onOpen,
        onRefresh = {
            scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
    )
}

private const val CACHE_KEY = "settings_home"

/** Everything the home renders, cached as one unit. Null = never loaded. */
@JsonClass(generateAdapter = true)
data class SettingsHomeData(
    val health: DataHealth? = null,
    val version: ServerVersion? = null,
    val update: UpdateCheck? = null,
    val profile: ProfileResponse? = null,
    val ai: AiConfigOut? = null,
    val lastImport: ImportJob? = null,
    /** The jobs list loaded at least once — so "No imports yet" is an
     *  answer, not a failed request. */
    val jobsKnown: Boolean = false,
)

/** Phone-local settings the summaries read. */
data class LocalPrefs(
    val imperial: Boolean,
    val timeFormat: String,
    val permissionsLost: Boolean,
    val lastSuccess: Instant?,
    val configured: Boolean,
)

@Composable
fun SettingsHomeContent(
    data: SettingsHomeData,
    local: LocalPrefs,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    now: Instant,
    onBack: () -> Unit,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    NeonScreen(
        title = "Settings",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (error != null && !loading) {
            NeonErrorBanner(
                error,
                title = if (data.health == null) "Couldn't load your settings status"
                else "Couldn't refresh — showing the last status",
            ) { onRefresh() }
        }
        val health = data.health
        when {
            health != null -> StatusHero(data, now) { onOpen(SettingsRoutes.CONNECTION) }
            loading -> SettingsSkeleton(listOf(168.dp))
        }

        NeonEyebrow("Settings")
        val failed = error != null && !loading
        fun pending(v: Any?) = if (v != null) null else if (failed) "Couldn't load" else "Loading…"

        SettingsCard {
            SettingsNavRow(
                Icons.Outlined.Person, NeonMV.Cyan, "You & goals",
                pending(data.profile) ?: youSummary(data.profile!!),
            ) { onOpen(SettingsRoutes.YOU) }
            SettingsDivider()
            SettingsNavRow(
                Icons.Outlined.Tune, NeonMV.Periwinkle, "Units & display",
                "${if (local.imperial) "Imperial" else "Metric"} · " + when (local.timeFormat) {
                    "12h" -> "12-hour clock"; "24h" -> "24-hour clock"; else -> "Clock follows phone"
                },
            ) { onOpen(SettingsRoutes.DISPLAY) }
            SettingsDivider()
            val connProblem = local.permissionsLost || !local.configured
            SettingsNavRow(
                Icons.Outlined.CloudSync, NeonMV.Lime, "Connection & sync",
                when {
                    !local.configured -> "No server set"
                    local.permissionsLost -> "Health Connect is denying reads"
                    else -> "Last synced ${relAge(local.lastSuccess, now)}"
                },
                summaryColor = if (connProblem) NeonMV.Amber else NeonMV.Muted,
            ) { onOpen(SettingsRoutes.CONNECTION) }
            SettingsDivider()
            val ov = health?.overview
            val brokenIntegration = health?.integrations
                ?.firstOrNull { it.key in health.problemKeys }
            SettingsNavRow(
                Icons.Outlined.Extension, NeonMV.Amber, "Integrations",
                when {
                    ov == null -> pending(null)!!
                    ov.integrationsTotal == 0 -> "None connected"
                    brokenIntegration != null ->
                        "${ov.integrationsOk} of ${ov.integrationsTotal} working · ${brokenIntegration.label} needs attention"
                    else -> "${ov.integrationsOk} of ${ov.integrationsTotal} working"
                },
                summaryColor = if (brokenIntegration != null) NeonMV.Amber else NeonMV.Muted,
            ) { onOpen(SettingsRoutes.INTEGRATIONS) }
            SettingsDivider()
            SettingsNavRow(
                Icons.Outlined.AutoAwesome, NeonMV.Magenta, "AI",
                pending(data.ai) ?: aiSummary(data.ai!!),
            ) { onOpen(SettingsRoutes.AI) }
            SettingsDivider()
            val job = data.lastImport
            SettingsNavRow(
                Icons.Outlined.Storage, NeonMV.Cyan, "Data & imports",
                when {
                    job != null -> "Last import: ${importKindLabel(job.kind)} · " +
                        relAge(parseInstant(job.startedAt), now)
                    data.jobsKnown -> "No imports yet · imports run on the web"
                    else -> pending(null)!!
                },
            ) { onOpen(SettingsRoutes.DATA) }
            SettingsDivider()
            val updateAvail = data.update?.updateAvailable == true
            SettingsNavRow(
                Icons.Outlined.Info, NeonMV.Periwinkle, "About & updates",
                buildString {
                    append(data.version?.version?.let { "Server v$it" } ?: "Server —")
                    append(" · App ${BuildConfig.VERSION_NAME}")
                },
                trailing = if (updateAvail) {
                    { StatusPill("Update", NeonMV.Lime) }
                } else null,
            ) { onOpen(SettingsRoutes.ABOUT) }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun StatusHero(data: SettingsHomeData, now: Instant, onClick: () -> Unit) {
    val health = data.health ?: return
    val ov = health.overview
    // The TONE is the server's. An older server without `overview` gets a
    // neutral card that says so rather than a green one.
    val accent = when (ov?.tone) {
        "positive" -> NeonMV.Lime
        "caution" -> NeonMV.Amber
        else -> NeonMV.Periwinkle
    }
    NeonHeroCard(
        accent = accent,
        modifier = Modifier.clickable(
            onClickLabel = "Open Connection & sync", role = Role.Button, onClick = onClick,
        ),
    ) {
        Text("STATUS", color = accent, fontSize = 11.sp, fontWeight = FontWeight.Bold,
            letterSpacing = 1.4.sp)
        Spacer(Modifier.height(4.dp))
        Text(
            ov?.headline ?: "Update the server to see a status summary",
            color = NeonMV.Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold,
            lineHeight = 23.sp,
        )
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NeonStatTile(
                value = relAge(parseInstant(ov?.lastPhoneSyncAt), now).removeSuffix(" ago"),
                label = "Phone sync",
                modifier = Modifier.weight(1f),
            )
            NeonStatTile(
                value = ov?.let { "${it.integrationsOk}/${it.integrationsTotal}" } ?: "—",
                label = "Integrations ok",
                modifier = Modifier.weight(1f),
                accent = if (ov != null && ov.integrationsOk < ov.integrationsTotal) NeonMV.Amber else null,
            )
            NeonStatTile(
                value = data.version?.version?.let { "v$it" } ?: "—",
                label = "Server",
                modifier = Modifier.weight(1f),
            )
        }
        if (data.update?.updateAvailable == true) {
            Spacer(Modifier.height(10.dp))
            Row {
                StatusPill("Update available: v${data.update.latest}", NeonMV.Lime)
            }
        }
    }
}

/** "Age 41 · 10,000 steps · 8 h sleep" — age is the server's, not derived here. */
internal fun youSummary(p: ProfileResponse): String {
    val parts = mutableListOf<String>()
    p.derived?.age?.let { parts += "Age $it" }
    parts += "%,d steps".format(p.stepsGoal())
    p.extra?.sleepGoalH?.let { parts += "${trim(it)} h sleep" }
    if (p.birthDate == null && p.heightCm == null) parts += "profile incomplete"
    return parts.joinToString(" · ")
}

internal fun aiSummary(a: AiConfigOut): String {
    if (!a.enabled) return "Off"
    val model = AI_MODELS.firstOrNull { it.first == a.model }?.second ?: a.model
    return "On · $model · ${a.callsToday} of ${a.dailyCallLimit} today"
}

internal fun importKindLabel(kind: String): String = when (kind) {
    "google_takeout" -> "Google Takeout"
    "fitbit_gps_tracks" -> "Fitbit GPS tracks"
    "garmin_fit_tracks" -> "Garmin FIT tracks"
    else -> kind.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

private fun trim(d: Double): String =
    if (d == Math.floor(d)) d.toInt().toString() else "%.1f".format(d)

/** Same ids and labels as the web picker. */
internal val AI_MODELS = listOf(
    "claude-haiku-4-5-20251001" to "Haiku 4.5",
    "claude-sonnet-4-6" to "Sonnet 4.6",
    "claude-opus-4-7" to "Opus 4.7",
)

internal fun toneColor(tone: String?): Color = when (tone) {
    "positive" -> NeonMV.Lime
    "caution" -> NeonMV.Amber
    else -> NeonMV.Muted
}
