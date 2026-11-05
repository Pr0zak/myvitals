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
 *   NeonHeroCard   the one focal block a screen leads with (on the page ground)
 *   NeonRing       progress ring, optional stage ticks / milestone dots
 *   NeonEyebrow    sentence-case section heading
 *   NeonStatTile   a number over a label, for stat rows
 *
 * A screen reached from another one (detail screens, Meals, Fasting, Sober)
 * uses NeonScreen with `onBack`, so it gets the same gradient, title and
 * scroll as the tabs instead of a flat back-arrow header.
 */

val NeonHeroShape = RoundedCornerShape(22.dp)

/**
 * The focal block a screen leads with. It sits on the page ground — no card
 * surface, border or glow — matching the Today brief: the hero is the one
 * thing on the screen that is NOT boxed, which is what makes it read as the
 * hero. [accent] is kept for API compatibility; colour now lives in the
 * hero's own data marks (rings, legend bars), not in a frame around it.
 */
@Suppress("UNUSED_PARAMETER")
@Composable
fun NeonHeroCard(
    accent: Color,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(top = 4.dp, bottom = 20.dp),
        content = content,
    )
}

/**
 * Section heading, sentence case. Call sites written for the old tracked-caps
 * style sometimes pass "THIS WEEK'S VOLUME"; an all-caps string is folded to
 * sentence case here so every caller changes without being touched.
 */
@Composable
fun NeonEyebrow(text: String, modifier: Modifier = Modifier) {
    Text(
        sentenceCase(text),
        color = NeonMV.Ink,
        fontSize = 17.sp,
        fontWeight = FontWeight.Medium,
        modifier = modifier.padding(top = 18.dp, bottom = 10.dp),
    )
}

/** "THIS WEEK'S VOLUME" -> "This week's volume". Mixed-case input is left
 *  alone (it may hold a proper noun or a unit like "HRV"). */
fun sentenceCase(text: String): String {
    val letters = text.filter { it.isLetter() }
    if (letters.isEmpty() || letters.any { it.isLowerCase() }) return text
    val lower = text.lowercase()
    return lower.replaceFirstChar { it.uppercase() }
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
                // Soft edge: a slightly wider faint pass under the arc. Kept
                // narrow so it never bleeds into a neighbouring ring.
                drawArc(color.copy(alpha = 0.12f), -90f, 360f * f, false, tl, arcSize,
                    style = Stroke(sw + 4.dp.toPx(), cap = StrokeCap.Round))
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

/** Small caption under a ring value ("of 16h", "sets"). */
@Composable
fun NeonRingCaption(text: String) {
    // A caption continues the number above it ("14.3h of 16h"), so an
    // all-caps caption folds to lower case rather than sentence case.
    val shown = if (text.any { it.isLowerCase() }) text else text.lowercase()
    Text(shown, color = NeonMV.Muted, fontSize = 11.sp)
}
