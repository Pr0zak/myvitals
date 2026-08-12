package app.myvitals.ui.common

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.Spring
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.vitals.VitalRange

/**
 * Material 3 Expressive button group for the time-range selector.
 *
 * M3 Expressive replaced the row-of-equal-outlined-chips pattern with button
 * groups, whose defining behaviour is that the **selected item widens and its
 * neighbours yield**. That matters here more than anywhere else in the app:
 * this control sits at the top of every detail screen, it is the most-tapped
 * thing in myvitals, and four identical outlined boxes make the current range
 * something you have to read rather than see.
 *
 * The widening is a spring, not a duration — M3 Expressive replaced the
 * easing/duration model with a motion-physics system, and a spring is what
 * makes the control feel like it has weight rather than like it repainted.
 *
 * Label colour is chosen from the accent's own luminance rather than hard-coded,
 * because the fill is the domain accent: dark ink reads on lime and cyan, and
 * would vanish on a darker accent.
 */
@Composable
fun VitalRangeGroup(
    selected: VitalRange,
    accent: Color,
    modifier: Modifier = Modifier,
    onSelect: (VitalRange) -> Unit,
) {
    val onAccent = if (accent.luminance() > 0.45f) Color(0xFF06222B) else NeonMV.Ink
    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(999.dp))
            // A track one step ABOVE the page, not equal to it. Using the page
            // colour made the unselected labels look like loose text rather
            // than part of one control.
            .background(NeonMV.Card)
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for (r in VitalRange.entries) {
            val isOn = r == selected
            // 2.1 : 1 — enough that the selection is unmistakable at a glance
            // without squeezing the other three labels into ellipses.
            val weight by animateFloatAsState(
                targetValue = if (isOn) 2.1f else 1f,
                animationSpec = spring(
                    dampingRatio = Spring.DampingRatioLowBouncy,
                    stiffness = Spring.StiffnessMediumLow,
                ),
                label = "range-weight",
            )
            Box(
                Modifier
                    .weight(weight)
                    .clip(RoundedCornerShape(999.dp))
                    .background(if (isOn) accent else Color.Transparent)
                    .clickable { onSelect(r) }
                    .padding(vertical = 9.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    r.label,
                    color = if (isOn) onAccent else NeonMV.Muted,
                    fontSize = 13.sp,
                    fontWeight = if (isOn) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1,
                    overflow = TextOverflow.Clip,
                )
            }
        }
    }
}
