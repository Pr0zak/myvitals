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
fun NeonErrorBanner(message: String, onRetry: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .background(NeonMV.Bad.copy(alpha = 0.10f), RoundedCornerShape(14.dp))
            .border(1.dp, NeonMV.Bad.copy(alpha = 0.28f), RoundedCornerShape(14.dp))
            .clickable(onClick = onRetry)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(
            "Couldn't load today",
            color = NeonMV.Bad, fontSize = 13.sp, fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(2.dp))
        Text(message, color = NeonMV.Muted, fontSize = 12.sp)
        Spacer(Modifier.height(4.dp))
        Text("Tap to retry", color = NeonMV.Cyan, fontSize = 12.sp,
            fontWeight = FontWeight.SemiBold)
    }
}
