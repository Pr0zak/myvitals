package app.myvitals.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.ui.neon.NeonMV

/** What, if anything, is wrong with Health Connect access. */
enum class HcProblem { NONE, MISSING, DENYING }

/**
 * UX-P9 — the Health Connect permissions banner, moved out of Settings and
 * into the shell (shown above Today). The web shows its equivalent on every
 * page; on the phone it lived only inside Settings, so a revoked grant after
 * an APK upgrade went unnoticed until the numbers went quiet.
 *
 * Reuses the existing handlers: the grant launcher from MainActivity, the
 * same "open Health Connect" path Settings uses, and Sync now (which re-runs
 * the sync and so re-checks whether reads are being denied).
 */
@Composable
fun HealthConnectShellBanner(
    settings: SettingsRepository,
    isHealthConnectAvailable: Boolean,
    hasPermissions: suspend () -> Boolean,
    onRequestPermissions: () -> Unit,
    onSyncNow: () -> Unit,
) {
    val context = LocalContext.current
    var tick by remember { mutableIntStateOf(0) }
    app.myvitals.ui.common.LifecycleResumeEffect(staleAfterMs = 0L) { tick++ }
    // null until the (off-main-thread) permission check answers — the banner
    // stays hidden rather than flashing "missing" on every launch.
    val granted by produceState<Boolean?>(null, isHealthConnectAvailable, tick) {
        value = if (isHealthConnectAvailable) hasPermissions() else null
    }
    val problem = when {
        !settings.isConfigured() || !isHealthConnectAvailable || granted == null -> HcProblem.NONE
        granted == false -> HcProblem.MISSING
        settings.permissionsLost -> HcProblem.DENYING
        else -> HcProblem.NONE
    }
    HealthConnectBannerContent(
        problem = problem,
        onGrant = onRequestPermissions,
        onOpenHealthConnect = { openHealthConnectSettings(context) },
        onSyncNow = { onSyncNow(); tick++ },
    )
}

@Composable
fun HealthConnectBannerContent(
    problem: HcProblem,
    onGrant: () -> Unit,
    onOpenHealthConnect: () -> Unit,
    onSyncNow: () -> Unit,
) {
    if (problem == HcProblem.NONE) return
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .background(NeonMV.Amber.copy(alpha = 0.10f), shape)
            .border(1.dp, NeonMV.Amber.copy(alpha = 0.30f), shape)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(
            if (problem == HcProblem.MISSING) "Health Connect permissions are missing"
            else "Health Connect is denying reads",
            color = NeonMV.Amber, fontSize = 13.sp, fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(2.dp))
        Text(
            if (problem == HcProblem.MISSING)
                "Nothing new can be read from your watch until they're granted again — " +
                    "this often happens after an app update."
            else
                "The app has every permission, but Health Connect is blocking reads. Open it, " +
                    "tap myvitals, and turn each permission off and back on.",
            color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 16.sp,
        )
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (problem == HcProblem.MISSING) {
                NeonButton("Grant permissions", onGrant, accent = NeonMV.Amber)
            } else {
                NeonButton("Open Health Connect", onOpenHealthConnect, accent = NeonMV.Amber)
                NeonButton("Sync now", onSyncNow, filled = false, accent = NeonMV.Amber)
            }
        }
    }
}
