package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

/**
 * Tiny line chart sized to fit the parent. Auto-scales to data range
 * with a small head-room so the line never hugs the top/bottom edge.
 * Renders a faint baseline and a colored stroke. Used inside metric
 * badges on the Vitals dashboard.
 */
@Composable
fun SparkLine(
    values: List<Float?>,
    color: Color,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    Canvas(modifier = modifier) {
        if (values.size < 2) return@Canvas
        val real = values.mapIndexed { i, v -> i to v }.filter { it.second != null }
        if (real.size < 2) return@Canvas

        val minV = real.minOf { it.second!! }
        val maxV = real.maxOf { it.second!! }
        val span = (maxV - minV).coerceAtLeast(1f)
        val padY = size.height * 0.12f
        val plotH = size.height - 2 * padY
        val stepX = size.width / (values.size - 1).coerceAtLeast(1).toFloat()

        // Baseline at 25% from bottom for visual anchor
        drawLine(
            color = color.copy(alpha = 0.15f),
            start = Offset(0f, size.height - padY),
            end = Offset(size.width, size.height - padY),
            strokeWidth = 1.dp.toPx(),
        )

        val path = Path()
        var started = false
        for ((idx, v) in real) {
            val x = idx * stepX
            val y = size.height - padY - ((v!! - minV) / span) * plotH
            if (!started) { path.moveTo(x, y); started = true } else path.lineTo(x, y)
        }
        drawPath(
            path = path, color = color,
            style = Stroke(width = 1.5.dp.toPx()),
        )
    }
}
