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
 * Inline myvitals brand mark — "orbit markers": three quiet tracks with a fat
 * endpoint bead riding each, sleep (magenta) / move (lime) / recovery (cyan).
 * The bead is the same "today" marker the charts draw, so the mark is built
 * from the app's own vocabulary rather than a generic ring gauge.
 *
 * The beads sit at three different radii AND angles. That asymmetry is what
 * stops it reading as a bullseye, and it is what carries the mark through the
 * monochrome themed-icon variant where colour is gone.
 *
 * Same mark as `ic_launcher_foreground.xml`, the dashboard AppLogo and the
 * favicon. Rendered with Canvas arcs so it scales freely.
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
        // Geometry mirrors the 108-unit vector so every surface draws the same
        // mark; 0.87 is the same scale the launcher icon uses to clear the
        // 66dp adaptive-icon safe circle.
        val u = this.size.minDimension / 108f
        fun p(x: Float, y: Float) =
            Offset((54f + (x - 54f) * 0.87f) * u, (54f + (y - 54f) * 0.87f) * u)

        val stroke = Stroke(width = 4f * 0.87f * u, cap = StrokeCap.Round)

        // orbit radius, sweep start/extent (deg), bead radius, colour
        data class Orbit(
            val r: Float, val start: Float, val sweep: Float,
            val bead: Float, val bx: Float, val by: Float, val color: Color,
        )
        val orbits = listOf(
            Orbit(29f, -111f, 288f, 6.0f, 26.75f, 63.92f,
                Color(0xFFFF3AD8).copy(alpha = tint)),   // sleep
            Orbit(19.5f, 130f, 280f, 5.5f, 68.94f, 66.53f,
                Color(0xFF5DFF3B).copy(alpha = tint)),   // move
            Orbit(10f, 20f, 295f, 5.0f, 55.74f, 44.15f,
                Color(0xFF28E6FF).copy(alpha = tint)),   // recovery
        )
        for (o in orbits) {
            val rr = o.r * 0.87f * u
            val c = p(54f, 54f)
            drawArc(
                color = o.color.copy(alpha = o.color.alpha * 0.9f),
                startAngle = o.start,
                sweepAngle = o.sweep,
                useCenter = false,
                topLeft = Offset(c.x - rr, c.y - rr),
                size = Size(rr * 2, rr * 2),
                style = stroke,
            )
        }
        // Beads last so they sit over the tracks, each with the same soft halo
        // the charts give the latest reading.
        for (o in orbits) {
            val centre = p(o.bx, o.by)
            drawCircle(o.color.copy(alpha = o.color.alpha * 0.16f),
                radius = (o.bead + 2.6f) * 0.87f * u, center = centre)
            drawCircle(o.color, radius = o.bead * 0.87f * u, center = centre)
        }
    }
}
