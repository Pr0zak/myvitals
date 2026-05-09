package app.myvitals.ui.common

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Phone mirror of frontend/src/components/Skeleton.vue. A muted block
 * with a sweeping gradient that hints at the final layout while data
 * loads.
 *
 * Pass either `width` (fixed dp) or omit it and use `Modifier.fillMaxWidth()`.
 */
@Composable
fun ShimmerBlock(
    modifier: Modifier = Modifier,
    width: Dp? = null,
    height: Dp = 16.dp,
    cornerRadius: Dp = 6.dp,
) {
    val transition = rememberInfiniteTransition(label = "shimmer")
    val shift by transition.animateFloat(
        initialValue = -400f, targetValue = 800f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1400, easing = LinearEasing),
        ),
        label = "shimmer-progress",
    )

    val base = Color(0xFF1F2937).copy(alpha = 0.5f)
    val highlight = Color(0xFF374151).copy(alpha = 0.8f)
    val brush = Brush.linearGradient(
        colors = listOf(base, highlight, base),
        start = androidx.compose.ui.geometry.Offset(shift, 0f),
        end = androidx.compose.ui.geometry.Offset(shift + 400f, 0f),
    )

    val sized = if (width != null) modifier.size(width, height) else modifier.height(height)
    Box(
        modifier = sized
            .clip(RoundedCornerShape(cornerRadius))
            .background(brush),
    )
}
