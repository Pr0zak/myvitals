package app.myvitals.ui.common

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.ui.neon.NeonMV

/** One row of the menu. */
private data class LogItem(
    val label: String,
    val route: String,
    val tone: Color,
)

/**
 * Material 3 Expressive FAB menu, replacing the flat "+ Log" text button.
 *
 * M3 Expressive replaced the speed dial with an FAB menu whose items are larger
 * and higher-contrast, and whose FAB **morphs its corner radius** as it opens.
 * The point here is not decoration: logging anything was previously two or three
 * taps deep behind a single button labelled "Log", and the things you can
 * actually record were spread across four unrelated screens.
 *
 * Every entry routes somewhere that already exists and where a reading can
 * genuinely be recorded. Weight and blood pressure are deliberately absent:
 * their detail screens have no entry form, so listing them here would promise
 * a flow the app does not have.
 */
@Composable
fun LogFabMenu(
    modifier: Modifier = Modifier,
    onOpen: (String) -> Unit,
) {
    var open by remember { mutableStateOf(false) }

    val items = listOf(
        LogItem("Note", "journal", NeonMV.Magenta),
        LogItem("Measurements", "vitals/MEASUREMENTS", NeonMV.Cyan),
        LogItem("Fast", "fasting", NeonMV.Amber),
        LogItem("Sober", "sober", NeonMV.Magenta),
    )

    // Full pill when open, 20dp squircle when closed — the morph is the M3
    // signal that the button became a menu rather than navigating away.
    val corner by animateDpAsState(
        targetValue = if (open) 999.dp else 20.dp,
        animationSpec = spring(
            dampingRatio = Spring.DampingRatioLowBouncy,
            stiffness = Spring.StiffnessMediumLow,
        ),
        label = "fab-corner",
    )

    Column(modifier, horizontalAlignment = Alignment.Start) {
        items.forEachIndexed { i, item ->
            AnimatedVisibility(
                visible = open,
                // Staggered so the menu unfurls rather than appearing at once.
                enter = fadeIn(tween(160, delayMillis = i * 34)) +
                    scaleIn(
                        spring(
                            dampingRatio = Spring.DampingRatioLowBouncy,
                            stiffness = Spring.StiffnessMedium,
                        ),
                        initialScale = 0.88f,
                    ),
                exit = fadeOut(tween(90)) + scaleOut(tween(90), targetScale = 0.9f),
            ) {
                Row(
                    Modifier
                        .padding(bottom = 8.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .background(NeonMV.Card)
                        .border(1.dp, item.tone.copy(alpha = 0.45f), RoundedCornerShape(999.dp))
                        .clickable { open = false; onOpen(item.route) }
                        .padding(horizontal = 14.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier.size(9.dp).clip(RoundedCornerShape(999.dp))
                            .background(item.tone),
                    )
                    Spacer(Modifier.width(9.dp))
                    Text(item.label, color = NeonMV.Ink, fontSize = 13.sp)
                }
            }
        }

        Row(
            Modifier
                .clip(RoundedCornerShape(corner))
                .background(NeonMV.Cyan)
                .clickable { open = !open }
                .padding(horizontal = 20.dp, vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Text(
                if (open) "✕  Close" else "＋  Log",
                color = Color(0xFF06222B), fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}
