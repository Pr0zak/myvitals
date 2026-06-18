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
 * The legacy `heart` / `trace` color params no longer pick the mark's colors
 * (it is always the three brand rings), but the **alpha** of `heart` is still
 * honoured so existing call sites that fade the mark — e.g. the 360dp Settings
 * watermark passes `heart = …copy(alpha = 0.05f)` — stay faint instead of
 * blasting full-colour rings over the content.
 */
@Composable
fun BrandMark(
    dimension: Dp = 28.dp,
    heart: Color = Color(0xFFFF3AD8),
    @Suppress("UNUSED_PARAMETER") trace: Color = Color(0xFF28E6FF),
) {
    val tint = heart.alpha
    Canvas(modifier = Modifier.size(dimension)) {
        val s = this.size.minDimension
        val w = s * 0.085f
        val stroke = Stroke(width = w, cap = StrokeCap.Round)

        // diameter fraction, sweep fraction (of 360°), color — outer→inner.
        // `tint` carries the caller's requested opacity (1f for the normal mark,
        // ~0.05f for the faint Settings watermark).
        data class Ring(val diam: Float, val sweep: Float, val color: Color)
        val rings = listOf(
            Ring(0.78f, 0.76f, Color(0xFFFF3AD8).copy(alpha = tint)), // sleep
            Ring(0.54f, 0.70f, Color(0xFF5DFF3B).copy(alpha = tint)), // move
            Ring(0.30f, 0.82f, Color(0xFF28E6FF).copy(alpha = tint)), // recovery
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
