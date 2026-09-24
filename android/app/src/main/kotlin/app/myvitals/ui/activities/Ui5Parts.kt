package app.myvitals.ui.activities

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumberFamily

/*
 * UI-5 — small pieces the Activities feed, Activity detail and Trails
 * share. Kept here rather than in the neon kit so this slice cannot collide
 * with the others editing the kit in parallel.
 */

/**
 * "Couldn't refresh" banner that sits ABOVE whatever is cached.
 *
 * Amber, not rose: a failed refresh with yesterday's rows still on screen is
 * a caution about freshness, not a crisis. Before this, all three screens
 * replaced the whole list with a line of red text, so a flaky connection
 * made a season of cached rides vanish.
 */
@Composable
fun StaleBanner(
    title: String,
    message: String?,
    modifier: Modifier = Modifier,
    onRetry: (() -> Unit)? = null,
) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(NeonMV.Amber.copy(alpha = 0.10f))
            .border(1.dp, NeonMV.Amber.copy(alpha = 0.32f), RoundedCornerShape(14.dp))
            .then(if (onRetry != null) Modifier.clickable(onClick = onRetry) else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(title, color = NeonMV.Amber, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        if (!message.isNullOrBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(message, color = NeonMV.Muted, fontSize = 12.sp)
        }
        if (onRetry != null) {
            Spacer(Modifier.height(4.dp))
            Text("Tap to retry", color = NeonMV.Cyan, fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold)
        }
    }
}

/** A tinted pill ("This week · 3", "synced 4m ago"). */
@Composable
fun NeonPill(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = NeonMV.Cyan,
    onClick: (() -> Unit)? = null,
) {
    val shape = RoundedCornerShape(50)
    Box(
        modifier
            .clip(shape)
            .background(color.copy(alpha = 0.12f))
            .border(1.dp, color.copy(alpha = 0.40f), shape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text, color = color, fontFamily = NeonNumberFamily,
            fontSize = 12.sp, fontWeight = FontWeight.Bold,
        )
    }
}

/**
 * 42dp tinted circular action (48dp touch target with its padding). The
 * Vitality Neon header-button language the Trails header already used.
 */
@Composable
fun NeonIconButton(
    icon: ImageVector,
    contentDescription: String,
    modifier: Modifier = Modifier,
    accent: Color = NeonMV.Cyan,
    spinning: Boolean = false,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val rotation = if (spinning) {
        rememberInfiniteTransition(label = "ui5-spin").animateFloat(
            initialValue = 0f, targetValue = 360f,
            animationSpec = infiniteRepeatable(tween(800, easing = LinearEasing)),
            label = "ui5-rot",
        ).value
    } else 0f
    Box(
        modifier
            .padding(3.dp)
            .size(42.dp)
            .clip(CircleShape)
            .background(accent.copy(alpha = if (enabled) 0.14f else 0.06f))
            .border(1.dp, accent.copy(alpha = if (enabled) 0.45f else 0.20f), CircleShape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon, contentDescription = contentDescription,
            tint = accent.copy(alpha = if (enabled) 1f else 0.5f),
            modifier = Modifier.size(20.dp).graphicsLayer { rotationZ = rotation },
        )
    }
}

/** Colour for a server `tone` (compare.py / activity_ytd.py). Never rose:
 *  a shortfall is amber, and "cannot judge" is muted. */
fun toneColor(tone: String?): Color = when (tone) {
    "positive" -> NeonMV.Lime
    "caution" -> NeonMV.Amber
    else -> NeonMV.Muted
}

/** A compact value over its label, for the quiet stat line. */
@Composable
fun QuietStat(label: String, value: String, modifier: Modifier = Modifier, color: Color = NeonMV.Ink) {
    Column(modifier) {
        Text(value, color = color, fontFamily = NeonNumberFamily,
            fontSize = 15.sp, fontWeight = FontWeight.Bold, maxLines = 1)
        Text(label.uppercase(), color = NeonMV.Muted, fontFamily = NeonNumberFamily,
            fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
    }
}
