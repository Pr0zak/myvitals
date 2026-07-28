package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * CAT-1: small pill badges for an exercise's mechanic (compound / isolation)
 * and force (push / pull / static). Renders nothing when both are absent.
 * Shared by the catalog detail sheet and the active-workout info dialog.
 */
@Composable
fun ExerciseBadges(mechanic: String?, force: String?, tint: Color) {
    val tags = listOfNotNull(
        mechanic?.takeIf { it.isNotBlank() },
        force?.takeIf { it.isNotBlank() },
    )
    if (tags.isEmpty()) return
    Row(
        Modifier.padding(top = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        tags.forEach { tag ->
            Text(
                tag.uppercase(),
                color = tint, fontSize = 10.sp,
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .background(tint.copy(alpha = 0.14f))
                    .padding(horizontal = 8.dp, vertical = 2.dp),
            )
        }
    }
}
