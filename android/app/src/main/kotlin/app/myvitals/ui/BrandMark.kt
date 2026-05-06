package app.myvitals.ui

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Inline myvitals brand mark — red heart with a white EKG trace running
 * through it. Same SVG path data as `ic_launcher_foreground.xml`, but
 * rendered inline via PathParser so the icon scales freely. Path
 * coordinates are in the original 108×108 launcher viewport.
 */
@Composable
fun BrandMark(
    size: Dp = 28.dp,
    heart: Color = Color(0xFFEF4444),
    trace: Color = Color(0xFFFFFFFF),
) {
    val heartPath = remember {
        PathParser().parsePathString(
            "M54,76 C 54,76 30,60 30,46 C 30,38 36,33 43,33 " +
            "C 49,33 52,36 54,40 C 56,36 59,33 65,33 " +
            "C 72,33 78,38 78,46 C 78,60 54,76 54,76 Z"
        ).toPath()
    }
    val tracePath = remember {
        PathParser().parsePathString(
            "M30,52 L42,52 L46,46 L50,58 L54,40 L58,58 L62,46 L66,52 L78,52 " +
            "L78,55 L66,55 L62,49 L58,61 L54,43 L50,61 L46,49 L42,55 L30,55 Z"
        ).toPath()
    }

    Canvas(modifier = Modifier.size(size)) {
        val s = this.size.minDimension / 108f
        scale(s, s, pivot = androidx.compose.ui.geometry.Offset.Zero) {
            drawPath(heartPath, heart)
            drawPath(tracePath, trace)
        }
    }
}
