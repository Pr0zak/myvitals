package app.myvitals.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.DirectionsBike
import androidx.compose.material.icons.outlined.EditNote
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.Landscape
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.ui.neon.NeonMV

/**
 * "Focus areas" — phone twin of `FocusAreas.vue`.
 *
 * Replaces the neon home's pill list (Fasting / Sober / Steps / Workout),
 * which was another card style and mixed live values into what is really
 * navigation. The home stops trying to be both a dashboard and a menu.
 */
@Composable
fun FocusAreas(
    onOpen: (String) -> Unit,
    modifier: Modifier = Modifier,
    /** "N tracked" per area, counted server-side from the tiles that have a
     *  value today — a constant subtitle would be decoration. */
    counts: Map<String, app.myvitals.sync.FocusCount> = emptyMap(),
) {
    Column(modifier.fillMaxWidth()) {
        Text(
            "Focus areas", color = Color(0xFFE9EDF2),
            fontSize = 21.sp,
        )
        Spacer(Modifier.height(12.dp))
        AREAS.chunked(2).forEach { pair ->
            Row(
                Modifier.fillMaxWidth().padding(bottom = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                pair.forEach { a ->
                    Box(Modifier.weight(1f)) {
                        val c = counts[a.key]
                        AreaTile(
                            a,
                            if (c != null) "${c.tracked} tracked" else "Open",
                        ) { onOpen(a.route) }
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

private data class Area(
    val key: String, val label: String, val icon: ImageVector,
    val route: String, val tone: Color,
)

// Tones follow the shell's domain palette (see `Vital.accent`) so the tiles
// agree with the chart you land on when you tap them. They were a separate
// hand-picked set left over from the classic theme, which put a salmon heart
// above a cyan heart-rate chart.
private val AREAS = listOf(
    Area("heart", "Heart", Icons.Outlined.FavoriteBorder, "vitals/HR", NeonMV.Cyan),
    Area("sleep", "Sleep", Icons.Outlined.Bedtime, "vitals/SLEEP", NeonMV.Magenta),
    Area("fitness", "Fitness", Icons.Outlined.DirectionsBike, "activities", NeonMV.Cyan),
    Area("strength", "Training", Icons.Outlined.FitnessCenter, "workout/today", NeonMV.Bad),
    Area("vitals", "Vitals", Icons.Outlined.MonitorHeart, "vitals/HRV", NeonMV.Cyan),
    Area("habits", "Habits", Icons.Outlined.Timer, "fasting", NeonMV.Amber),
    Area("trails", "Trails", Icons.Outlined.Landscape, "trails", NeonMV.Lime),
    Area("journal", "Journal", Icons.Outlined.EditNote, "journal", NeonMV.Muted),
)

@Composable
private fun AreaTile(a: Area, sub: String, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(Color(0xFF1B1C1F), RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(a.icon, contentDescription = null, tint = a.tone,
            modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(10.dp))
        Column {
            Text(a.label, color = Color(0xFFE9EDF2), fontSize = 14.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(sub, color = Color(0xFF8D949D), fontSize = 11.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}
