package app.myvitals.snapshots

import app.myvitals.snapshots.SampleDataSettings as S
import app.myvitals.ui.settings.AboutContent
import app.myvitals.ui.settings.ConnectionSyncContent
import app.myvitals.ui.settings.SettingsHomeContent
import app.myvitals.ui.settings.SettingsHomeData
import app.myvitals.ui.settings.SyncPhase
import app.myvitals.ui.settings.YouGoalsContent
import app.myvitals.ui.settings.youGoalsFormFrom
import app.myvitals.update.ApkDownloader
import app.myvitals.update.UpdateChecker
import androidx.compose.foundation.background
import org.junit.Rule
import org.junit.Test

/** The Settings redesign (SETTINGS-C) in the states that matter. */
class SettingsSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    private fun home(data: SettingsHomeData, error: String? = null, loading: Boolean = false,
                     local: app.myvitals.ui.settings.LocalPrefs = S.local) =
        paparazzi.snapshot {
            NeonFrame {
                SettingsHomeContent(
                    data = data, local = local, loading = loading, refreshing = false,
                    error = error, now = S.NOW, onBack = {}, onOpen = {}, onRefresh = {},
                )
            }
        }

    /** Everything arriving: a Lime hero. */
    @Test fun homeOk() = home(S.home)

    /** A stale stream and a broken integration: Amber, never rose, and an
     *  update waiting. */
    @Test fun homeCaution() = home(
        S.home.copy(health = S.healthCaution, update = S.updateAvail),
        local = S.local.copy(permissionsLost = true),
    )

    /** Every request failed, nothing cached: a titled banner and the rows,
     *  each saying it couldn't load — never an empty card. */
    @Test fun homeFailed() = home(SettingsHomeData(), error = "Can't reach the server.")

    /** First open, requests in flight. */
    @Test fun homeLoading() = home(SettingsHomeData(), loading = true)

    private fun you(scroll: Int, dirty: Boolean) = paparazzi.snapshot {
        val base = youGoalsFormFrom(S.profile, S.schedule, imperial = true)
        val draft = if (dirty) base.copy(weightGoal = "170", sleepGoalH = "8") else base
        // The dirty case renders at true viewport height so the sticky bar
        // lands at the bottom of the screen, over the page, as on a phone
        // (NeonFrame's tall canvas would put it 6000dp down).
        ViewportOr(dirty, scroll) {
            YouGoalsContent(
                draft = draft, base = base, schedule = S.schedule, imperial = true,
                estimatedMaxHr = 180, autoRestingHr = 57.4,
                loading = false, refreshing = false, error = null,
                saving = false, saveError = null,
                onChange = {}, onDiscard = {}, onSave = {}, onBack = {}, onRefresh = {},
            )
        }
    }

    @Test fun youClean_1() = you(0, dirty = false)
    @Test fun youClean_2() = you(VIEWPORT_DP - 60, dirty = false)
    @Test fun youClean_3() = you(2 * (VIEWPORT_DP - 60), dirty = false)

    /** Edited: the sticky Save / Discard bar over the page. */
    @Test fun youDirty() = you(0, dirty = true)

    private fun connection(scroll: Int, lost: Boolean) = paparazzi.snapshot {
        NeonFrame(scroll) {
            ConnectionSyncContent(
                url = "https://vitals.example.com", token = "example-ingest-token-0000",
                connDirty = false, savedNote = null, onUrl = {}, onToken = {}, onSaveConnection = {},
                facts = if (lost) S.facts.copy(permissionsLost = true) else S.facts,
                phase = if (lost) SyncPhase.IDLE else SyncPhase.RUNNING,
                configured = true,
                onGrant = {}, onOpenHealthConnect = {}, onSyncNow = {}, onBackfill = {},
                health = if (lost) S.healthCaution else S.healthOk,
                healthLoading = false, healthError = null,
                onOpenLogs = {}, onUploadLogs = {}, onClearBuffer = {},
                now = S.NOW, refreshing = false, onRefresh = {}, onBack = {},
            )
        }
    }

    @Test fun connection_1() = connection(0, lost = false)
    @Test fun connection_2() = connection(VIEWPORT_DP - 60, lost = false)
    @Test fun connectionPermsLost() = connection(0, lost = true)

    @Test fun about() = paparazzi.snapshot {
        NeonFrame {
            AboutContent(
                version = S.version, check = S.updateAvail, cron = S.cron,
                loading = false, refreshing = false, error = null,
                checking = false, checkError = null,
                appVersion = "0.46.1 · build 4601",
                appCheck = UpdateChecker.Result.UpToDate,
                apkState = ApkDownloader.State.Idle,
                applying = false, applyMsg = null, now = S.NOW,
                onCheck = {}, onApply = {}, onDownloadApk = { _, _ -> },
                onCancelApk = {}, onInstallApk = {}, onDismissApk = {},
                onBack = {}, onRefresh = {},
            )
        }
    }
}

@androidx.compose.runtime.Composable
private fun ViewportOr(viewport: Boolean, scroll: Int, content: @androidx.compose.runtime.Composable () -> Unit) {
    if (!viewport) {
        NeonFrame(scroll, content)
        return
    }
    app.myvitals.ui.neon.NeonTheme {
        androidx.compose.foundation.layout.Box(
            androidx.compose.ui.Modifier.background(app.myvitals.ui.neon.NeonMV.Bg),
        ) { content() }
    }
}
