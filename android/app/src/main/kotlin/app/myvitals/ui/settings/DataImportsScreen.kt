package app.myvitals.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.ImportJob
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.Instant

/**
 * Data & imports (SETTINGS-C). Mirrors web `settings/SettingsData.vue`.
 *
 * Read-only on the phone by declaration: imports upload archives of up to
 * several gigabytes and exports download them, which a browser does better
 * than this app. What the phone CAN usefully show is whether the import you
 * started on the web has finished — hence the recent jobs, read through the
 * `require_any` twin `/query/import-jobs` (the import router itself wants
 * the dashboard's token).
 */
@Composable
fun DataImportsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var jobs by remember { mutableStateOf<List<ImportJob>?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        try {
            jobs = settings.call { importJobs(10) }
            error = null
        } catch (e: Exception) {
            Timber.w(e, "import jobs load failed")
            error = e.settingsMessage()
        } finally {
            loading = false
        }
    }
    LaunchedEffect(Unit) { load() }

    DataImportsContent(
        jobs = jobs, loading = loading, refreshing = refreshing, error = error,
        now = Instant.now(), onBack = onBack,
        onRefresh = { scope.launch { refreshing = true; try { load() } finally { refreshing = false } } },
    )
}

@Composable
fun DataImportsContent(
    jobs: List<ImportJob>?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    now: Instant,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    NeonScreen(
        title = "Data & imports",
        contentPadding = contentPadding,
        onBack = onBack,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        WebOnlyNote(
            "Imports and exports are on the web — they upload or download large archives, " +
                "which a browser handles better than this app. Their progress shows here.",
        )
        NeonEyebrow("Recent imports")
        when {
            jobs == null && error != null && !loading ->
                NeonErrorBanner(error, title = "Couldn't load recent imports") { onRefresh() }
            jobs == null -> SettingsSkeleton(listOf(72.dp, 72.dp, 72.dp))
            else -> {
                if (error != null) {
                    NeonErrorBanner(error, title = "Couldn't refresh — showing the last list") { onRefresh() }
                }
                if (jobs.isEmpty()) {
                    SettingsCard { SettingsNote("No imports yet.") }
                } else {
                    SettingsCard {
                        jobs.forEachIndexed { idx, j ->
                            if (idx > 0) SettingsDivider()
                            JobRow(j, now)
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun JobRow(j: ImportJob, now: Instant) {
    val (pill, color) = jobPill(j.status)
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(importKindLabel(j.kind), color = NeonMV.Ink, fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold)
            Text(
                listOfNotNull(
                    j.filename,
                    relAge(parseInstant(j.startedAt), now),
                    if (j.totalRows > 0) "%,d rows".format(j.totalRows) else null,
                ).joinToString(" · "),
                color = NeonMV.Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            j.error?.let {
                Text(it.lineSequence().firstOrNull().orEmpty().take(140), color = NeonMV.Amber,
                    fontSize = 11.sp, maxLines = 2)
            }
        }
        Spacer(Modifier.width(10.dp))
        StatusPill(pill, color)
    }
}

internal fun jobPill(status: String): Pair<String, Color> = when (status) {
    "running" -> "Running" to NeonMV.Cyan
    "done", "completed" -> "Done" to NeonMV.Lime
    "failed", "error" -> "Failed" to NeonMV.Amber
    else -> status.replaceFirstChar { it.uppercase() } to NeonMV.Muted
}
