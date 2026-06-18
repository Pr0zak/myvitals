package app.myvitals.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Inline myvitals brand mark — the "vitality" tri-ring: sleep (magenta),
 * move (lime), recovery (cyan). Same mark as `ic_launcher_foreground.xml`,
 * the dashboard AppLogo, and the favicon. Rendered with Canvas arcs so it
 * scales freely.
 *
 * The legacy `heart` / `trace` color params are kept for source-compat with
 * existing call sites but no longer affect rendering — the mark is always the
 * three brand-colored rings.
 */
@Composable
fun BrandMark(
    dimension: Dp = 28.dp,
    @Suppress("UNUSED_PARAMETER") heart: Color = Color(0xFFFF3AD8),
    @Suppress("UNUSED_PARAMETER") trace: Color = Color(0xFF28E6FF),
) {
    Canvas(modifier = Modifier.size(dimension)) {
        val s = this.size.minDimension
        val w = s * 0.085f
        val stroke = Stroke(width = w, cap = StrokeCap.Round)

        // diameter fraction, sweep fraction (of 360°), color — outer→inner
        data class Ring(val diam: Float, val sweep: Float, val color: Color)
        val rings = listOf(
            Ring(0.78f, 0.76f, Color(0xFFFF3AD8)), // sleep
            Ring(0.54f, 0.70f, Color(0xFF5DFF3B)), // move
            Ring(0.30f, 0.82f, Color(0xFF28E6FF)), // recovery
        )
        for (r in rings) {
            val d = s * r.diam
            val inset = (s - d) / 2f
            drawArc(
                color = r.color,
                startAngle = -90f,
                sweepAngle = r.sweep * 360f,
                useCenter = false,
                topLeft = Offset(inset, inset),
                size = Size(d, d),
                style = stroke,
            )
        }
    }
}
