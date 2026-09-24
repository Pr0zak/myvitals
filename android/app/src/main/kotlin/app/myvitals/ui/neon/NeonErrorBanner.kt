package app.myvitals.ui.neon

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Failure banner for the neon home screens.
 *
 * These screens previously swallowed every error: a dead backend, an expired
 * token and "no data yet" all rendered as an empty ring reading "—", so there
 * was no way to tell a broken connection from a quiet day. Tapping retries.
 */
@Composable
fun NeonErrorBanner(
    message: String,
    /** What failed, in the user's words. It was hard-coded "Couldn't load
     *  today", which read wrongly on the Sleep, Weight and Train screens
     *  that now share this banner. */
    title: String = "Couldn't load",
    /** Amber by default: a failed request is a caution, not a crisis, and
     *  rose (NeonMV.Bad) is reserved for the crisis surfaces. It was rose on
     *  every screen until the UI refresh; UI-2 made the workout amber first. */
    accent: Color = NeonMV.Amber,
    actionLabel: String = "Tap to retry",
    onRetry: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .background(accent.copy(alpha = 0.10f), RoundedCornerShape(14.dp))
            .border(1.dp, accent.copy(alpha = 0.28f), RoundedCornerShape(14.dp))
            .clickable(onClick = onRetry)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(
            title,
            color = accent, fontSize = 13.sp, fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(2.dp))
        Text(message, color = NeonMV.Muted, fontSize = 12.sp)
        Spacer(Modifier.height(4.dp))
        Text(actionLabel, color = NeonMV.Cyan, fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold)
    }
}
