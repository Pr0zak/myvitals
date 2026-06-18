package app.myvitals.ui.neon

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Shared neon chrome for the six top-level screens. The radial obsidian
 * gradient + big Jakarta title mirror the web views' `.head h1` + bg so the
 * surfaces match. Screens compose their content as the trailing lambda.
 */

/** Obsidian radial-gradient background, matching the web `radial-gradient(...)`. */
val NeonBackgroundBrush: Brush
    @Composable get() = Brush.radialGradient(
        colors = listOf(NeonMV.BgElevated, NeonMV.Bg),
        radius = 1600f,
    )

/** Standard rounded card shape used across the neon surfaces (18dp). */
val NeonCardShape = RoundedCornerShape(18.dp)
val NeonPillShape = RoundedCornerShape(22.dp)

/**
 * Full-screen neon scaffold: obsidian gradient, a large title header, and a
 * vertically-scrolling content column. `contentPadding` is supplied by the
 * shell so content clears the bottom nav bar.
 */
@Composable
fun NeonScreen(
    title: String,
    contentPadding: PaddingValues,
    modifier: Modifier = Modifier,
    headerTrailing: @Composable (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(NeonBackgroundBrush),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp),
        ) {
            NeonTitle(title, trailing = headerTrailing)
            content()
        }
    }
}

@Composable
fun NeonTitle(title: String, trailing: @Composable (() -> Unit)? = null) {
    androidx.compose.foundation.layout.Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 16.dp, bottom = 14.dp),
        horizontalArrangement = androidx.compose.foundation.layout.Arrangement.SpaceBetween,
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        Text(
            text = title,
            color = NeonMV.Ink,
            fontSize = 30.sp,
            fontWeight = FontWeight.ExtraBold,
            letterSpacing = (-0.5).sp,
        )
        trailing?.invoke()
    }
}

/** Monospace numeric readout in Space Grotesk — the web `.big` stat style. */
@Composable
fun NeonNumber(
    text: String,
    color: Color = NeonMV.Ink,
    size: Int = 26,
    weight: FontWeight = FontWeight.Bold,
    modifier: Modifier = Modifier,
) {
    Text(
        text = text,
        color = color,
        fontFamily = NeonNumberFamily,
        fontSize = size.sp,
        fontWeight = weight,
        letterSpacing = (-0.5).sp,
        modifier = modifier,
    )
}
