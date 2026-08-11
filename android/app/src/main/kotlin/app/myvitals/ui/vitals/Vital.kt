package app.myvitals.ui.vitals

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.automirrored.outlined.DirectionsRun
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.HourglassEmpty
import androidx.compose.material.icons.outlined.MonitorWeight
import androidx.compose.material.icons.outlined.Note
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Speed
import androidx.compose.material.icons.outlined.Terrain
import androidx.compose.material.icons.outlined.Thermostat
import androidx.compose.material.icons.outlined.Timeline
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import app.myvitals.sync.TimePoint
import app.myvitals.ui.neon.NeonMV

/**
 * The metrics a detail screen can open onto.
 *
 * Lived inside the classic home screen until that screen was retired; it is
 * the routing vocabulary for `vitals/{key}` and six detail screens depend on
 * it, so it belongs in its own file rather than inside any one screen.
 */
enum class Vital(val label: String, val icon: ImageVector, val color: Color) {
    HR("Heart rate", Icons.Outlined.FavoriteBorder, Color(0xFFEF4444)),
    HRV("HRV", Icons.Outlined.Speed, Color(0xFFA855F7)),
    SLEEP("Sleep", Icons.Outlined.Bedtime, Color(0xFF60A5FA)),
    STEPS("Steps", Icons.AutoMirrored.Outlined.DirectionsRun, Color(0xFF22C55E)),
    WEIGHT("Weight", Icons.Outlined.MonitorWeight, Color(0xFFF59E0B)),
    MEASUREMENTS("Measurements", Icons.Outlined.Timeline, Color(0xFF38BDF8)),
    BP("Blood pressure", Icons.Outlined.FavoriteBorder, Color(0xFFEC4899)),
    SOBER("Sober", Icons.Outlined.Timer, Color(0xFF84CC16)),
    FASTING("Fasting", Icons.Outlined.HourglassEmpty, Color(0xFF38BDF8)),
    COACH("Coach", Icons.Outlined.Psychology, Color(0xFFA78BFA)),
    WORKOUT("Workout", Icons.Outlined.FitnessCenter, Color(0xFFEF4444)),
    ACTIVITY("Last activity", Icons.AutoMirrored.Outlined.DirectionsBike,
        Color(0xFF38BDF8)),
    TRAILS("Trails", Icons.Outlined.Terrain, Color(0xFF22C55E)),
    JOURNAL("Journal", Icons.Outlined.Note, Color(0xFF94A3B8)),
    // The neon shell emits vitals/SKIN_TEMP and vitals/RECOVERY. Without
    // these members Vital.valueOf() threw and the route fell back to HR —
    // tapping "Skin temp" showed you your pulse. Both render through the
    // generic series path off daily_summary.
    SKIN_TEMP("Skin temp", Icons.Outlined.Thermostat, Color(0xFFF97316)),
    RECOVERY("Recovery", Icons.Outlined.Bolt, Color(0xFF22D3EE)),
}

/**
 * The domain accent to paint a chart, icon or chip with.
 *
 * [Vital.color] is the **classic** palette. The Classic/Neon split was retired
 * — `SettingsRepository.neonShellEnabled` is now a constant `true` — so a
 * screen reading `.color` paints a tailwind-red HR chart inside a cyan neon
 * shell. Every dedicated detail screen (HR, Steps, Weight, BP, Sleep) was
 * doing exactly that, which is why their charts looked like they belonged to
 * a different app than the nav bar under them.
 *
 * The mapping is the one `VitalsDetailScreen` already used privately, hoisted
 * here so the dedicated screens share it: heart family → cyan, sleep/sober →
 * magenta, move → lime, weight/temp → amber.
 */
val Vital.accent: Color
    get() = when (this) {
        Vital.HR, Vital.HRV, Vital.BP, Vital.RECOVERY, Vital.FASTING -> NeonMV.Cyan
        Vital.SLEEP, Vital.SOBER -> NeonMV.Magenta
        Vital.STEPS, Vital.TRAILS -> NeonMV.Lime
        Vital.WEIGHT, Vital.SKIN_TEMP -> NeonMV.Amber
        Vital.WORKOUT -> NeonMV.Bad
        Vital.ACTIVITY, Vital.MEASUREMENTS -> NeonMV.Cyan
        Vital.COACH -> NeonMV.Magenta
        Vital.JOURNAL -> NeonMV.Muted
    }

/** Lightweight wrappers for live series + their freshness. */
data class HrSnapshot(val points: List<TimePoint>, val latest: Double?, val lastIso: String?)
data class WeightSnapshot(
    val points: List<Pair<Long, Double>>, val latestKg: Double?, val lastIso: String?,
)
data class BpSnapshot(val latestSys: Int?, val latestDia: Int?, val lastIso: String?)
