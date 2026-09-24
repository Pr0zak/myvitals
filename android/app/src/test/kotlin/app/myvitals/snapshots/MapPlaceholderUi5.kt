package app.myvitals.snapshots

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

/**
 * Paparazzi cannot render a WebView, so the UI-5 map slots get this: a
 * dark tile-coloured box with a route squiggle and a few status pins, so
 * the screenshot shows where the map sits and how the scrim reads over it.
 */
@Composable
fun MapPlaceholderUi5(modifier: Modifier, route: Boolean = true, pins: List<Color> = emptyList()) {
    Canvas(
        modifier.background(
            Brush.linearGradient(listOf(Color(0xFF2A2D36), Color(0xFF1B1D24), Color(0xFF23262E))),
        ),
    ) {
        val w = size.width
        val h = size.height
        for (i in 1..5) {
            drawLine(Color(0xFF34373F), Offset(0f, h * i / 6f), Offset(w, h * i / 6f - 30f), strokeWidth = 2f)
            drawLine(Color(0xFF30333B), Offset(w * i / 6f, 0f), Offset(w * i / 6f + 40f, h), strokeWidth = 2f)
        }
        if (route) {
            val p = Path().apply {
                moveTo(w * 0.15f, h * 0.70f)
                cubicTo(w * 0.25f, h * 0.20f, w * 0.45f, h * 0.15f, w * 0.55f, h * 0.35f)
                cubicTo(w * 0.65f, h * 0.55f, w * 0.85f, h * 0.20f, w * 0.88f, h * 0.45f)
                cubicTo(w * 0.90f, h * 0.70f, w * 0.40f, h * 0.80f, w * 0.15f, h * 0.70f)
            }
            drawPath(p, Color(0x5528E6FF), style = Stroke(10.dp.toPx()))
            drawPath(p, Color(0xFF28E6FF), style = Stroke(3.dp.toPx()))
        }
        pins.forEachIndexed { i, c ->
            val x = w * (0.12f + 0.11f * i)
            val y = h * (0.3f + 0.4f * ((i * 37) % 10) / 10f)
            drawCircle(Color.White, 7.dp.toPx(), Offset(x, y))
            drawCircle(c, 5.5.dp.toPx(), Offset(x, y))
        }
    }
}
