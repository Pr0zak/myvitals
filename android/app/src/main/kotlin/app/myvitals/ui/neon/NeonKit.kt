package app.myvitals.ui.neon

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.cos
import kotlin.math.sin

/*
 * The UI-refresh kit: the handful of pieces every redesigned screen shares,
 * so "one look everywhere" is one implementation rather than ten copies that
 * drift. Mirrors the components in frontend/src/components/neon on the web.
 *
 *   NeonHeroCard   the one focal card a screen leads with
 *   NeonRing       glowing progress ring, optional stage ticks / milestone dots
 *   NeonEyebrow    small tracked caps section label (replaces 21sp captions)
 *   NeonStatTile   a number over a label, for stat rows
 *
 * A screen reached from another one (detail screens, Meals, Fasting, Sober)
 * uses NeonScreen with `onBack`, so it gets the same gradient, title and
 * scroll as the tabs instead of a flat back-arrow header.
 */

val NeonHeroShape = RoundedCornerShape(22.dp)

/** The focal card: CardHigh, accent border and a soft accent glow. */
@Composable
fun NeonHeroCard(
    accent: Color,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(bottom = 14.dp)
            .shadow(18.dp, NeonHeroShape, ambientColor = accent, spotColor = accent)
            .clip(NeonHeroShape)
            .background(NeonMV.CardHigh)
            .border(1.dp, accent.copy(alpha = 0.40f), NeonHeroShape)
            .padding(16.dp),
        content = content,
    )
}

/** Small tracked caps label introducing a section. */
@Composable
fun NeonEyebrow(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        color = NeonMV.Muted,
        fontFamily = NeonNumberFamily,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.4.sp,
        modifier = modifier.padding(top = 14.dp, bottom = 8.dp),
    )
}

/** A number over a label. `accent` null keeps the number in Ink. */
@Composable
fun NeonStatTile(
    value: String,
    label: String,
    modifier: Modifier = Modifier,
    accent: Color? = null,
) {
    Column(
        modifier
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(vertical = 12.dp, horizontal = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        NeonNumber(value, color = accent ?: NeonMV.Ink, size = 22)
        Text(label, color = NeonMV.Muted, fontSize = 11.sp)
    }
}

/**
 * Glowing progress ring. [fraction] is clamped to 0..1 — the caller decides
 * what it means; a null value should be drawn by passing 0 and saying so in
 * [content], never by inventing a fraction.
 *
 * [ticks] mark thresholds on the track (fasting stages); [dots] mark
 * milestones and fill once reached (sober). Both are fractions of a turn.
 * [outerFraction] draws a thin second arc outside the main one.
 */
@Composable
fun NeonRing(
    fraction: Float,
    color: Color,
    size: Dp,
    stroke: Dp = 10.dp,
    modifier: Modifier = Modifier,
    ticks: List<Float> = emptyList(),
    dots: List<Pair<Float, Boolean>> = emptyList(),
    outerFraction: Float? = null,
    outerColor: Color = NeonMV.Cyan,
    content: @Composable () -> Unit = {},
) {
    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(size)) {
            val sw = stroke.toPx()
            val outerGap = if (outerFraction != null) 7.dp.toPx() else 0f
            val inset = sw / 2 + outerGap + 2.dp.toPx()
            val arcSize = Size(this.size.width - inset * 2, this.size.height - inset * 2)
            val tl = Offset(inset, inset)
            drawArc(NeonMV.Track, 0f, 360f, false, tl, arcSize, style = Stroke(sw))
            val f = fraction.coerceIn(0f, 1f)
            if (f > 0f) {
                // Glow: a wider translucent pass under the arc.
                drawArc(color.copy(alpha = 0.22f), -90f, 360f * f, false, tl, arcSize,
                    style = Stroke(sw * 2.1f, cap = StrokeCap.Round))
                drawArc(color, -90f, 360f * f, false, tl, arcSize,
                    style = Stroke(sw, cap = StrokeCap.Round))
            }
            if (outerFraction != null) {
                val ow = 3.dp.toPx()
                val oi = ow / 2 + 1.dp.toPx()
                val os = Size(this.size.width - oi * 2, this.size.height - oi * 2)
                val ot = Offset(oi, oi)
                drawArc(NeonMV.Track, 0f, 360f, false, ot, os, style = Stroke(ow))
                val of = outerFraction.coerceIn(0f, 1f)
                if (of > 0f) drawArc(outerColor, -90f, 360f * of, false, ot, os,
                    style = Stroke(ow, cap = StrokeCap.Round))
            }
            val r = arcSize.width / 2
            val c = Offset(this.size.width / 2, this.size.height / 2)
            for (t in ticks) {
                val a = Math.toRadians((t * 360.0) - 90.0)
                val p1 = Offset(c.x + (r - sw) * cos(a).toFloat(), c.y + (r - sw) * sin(a).toFloat())
                val p2 = Offset(c.x + (r + sw) * cos(a).toFloat(), c.y + (r + sw) * sin(a).toFloat())
                drawLine(NeonMV.Ink.copy(alpha = 0.7f), p1, p2, strokeWidth = 2.dp.toPx())
            }
            for ((t, reached) in dots) {
                val a = Math.toRadians((t * 360.0) - 90.0)
                val p = Offset(c.x + r * cos(a).toFloat(), c.y + r * sin(a).toFloat())
                drawCircle(if (reached) color else NeonMV.Bg, 5.dp.toPx(), p)
                drawCircle(color, 5.dp.toPx(), p, style = Stroke(2.dp.toPx()))
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center) { content() }
    }
}

/** Tiny caption under a ring value ("OF 16H", "SETS"). */
@Composable
fun NeonRingCaption(text: String) {
    Text(text.uppercase(), color = NeonMV.Muted, fontSize = 9.sp,
        fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
}
