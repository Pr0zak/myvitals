package app.myvitals.ui

import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Phone parity for components/YogaPoseIcon.vue. Each pose maps to one
 * or more SVG path-strings (24×24 viewBox); we feed them through
 * addPathNodes() and build an ImageVector once per pose. Rendered via
 * the standard Material Icon Composable so colour + size behave like
 * any other vector.
 */
private val POSE_PATHS: Map<String, List<String>> = mapOf(
    "Downward_Dog" to listOf(
        "M3 20 L12 5 L21 20",
        "M3 20 h3", "M18 20 h3",
    ),
    "Childs_Pose" to listOf(
        "M4 20 h16",
        "M6 20 c0 -3 3 -8 9 -8",
        "M15 12 c2 0 3 1 4 2",
        "M5 20 a1.5 1.5 0 0 1 -2 0",
    ),
    "Cat_Cow" to listOf(
        "M4 13 c2 -4 6 -4 8 0 c2 4 6 4 8 0",
        "M4 13 v3", "M20 13 v3",
        "M4 16 h2", "M18 16 h2",
    ),
    "Cobra_Pose" to listOf(
        "M3 20 h18",
        "M21 20 c-4 0 -8 -2 -10 -4 c-2 -2 -4 -3 -8 -3",
        "M3 20 v-3",
    ),
    "Pigeon_Pose" to listOf(
        "M3 20 h18",
        "M6 20 l4 -8 l8 8",
        "M10 12 c0 -3 1 -5 3 -6",
    ),
    "Forward_Fold" to listOf(
        "M12 4 v8",
        "M12 12 c-2 1 -4 3 -5 7",
        "M12 12 c2 1 4 3 5 7",
        "M5 20 h14",
    ),
    "Warrior_2" to listOf(
        "M3 20 h18",
        "M9 20 v-7",
        "M16 20 l-2 -8",
        "M9 13 a2 2 0 1 1 0.1 0",
        "M3 12 h12",
    ),
    "Triangle_Pose" to listOf(
        "M4 20 L20 20 L12 4 Z",
        "M12 4 v3",
    ),
    "Seated_Forward_Bend" to listOf(
        "M3 20 h18",
        "M3 20 c4 -1 8 -2 14 -4",
        "M17 16 c0 -2 -1 -3 -3 -3",
    ),
    "Reclined_Spinal_Twist" to listOf(
        "M3 17 h18",
        "M5 17 c2 -3 6 -3 8 -1",
        "M13 16 c1 -3 4 -4 6 -3",
        "M19 13 a1.5 1.5 0 1 1 0.1 0",
    ),
    "Bridge_Pose" to listOf(
        "M3 20 h18",
        "M5 20 c2 -8 12 -8 14 0",
        "M5 20 v-3", "M19 20 v-3",
    ),
    "Lizard_Pose" to listOf(
        "M3 20 h18",
        "M7 20 l3 -7",
        "M16 20 l-3 -10",
        "M10 13 c0 -2 2 -3 3 -3",
    ),
    "Half_Pigeon_Forward_Fold" to listOf(
        "M3 20 h18",
        "M5 20 l5 -6 l8 6",
        "M10 14 c-2 1 -3 3 -3 5",
    ),
    "Thread_The_Needle" to listOf(
        "M3 17 h18",
        "M7 17 v-5", "M16 17 v-5",
        "M7 12 h9",
        "M9 12 c-1 2 -3 3 -5 4",
    ),
    "Happy_Baby" to listOf(
        "M3 18 h18",
        "M6 18 c0 -2 1 -4 3 -4 c0 -3 2 -5 4 -5",
        "M18 18 c0 -2 -1 -4 -3 -4 c0 -3 -2 -5 -4 -5",
    ),
)

private fun buildVector(paths: List<String>, color: Color): ImageVector =
    ImageVector.Builder(
        defaultWidth = 24.dp, defaultHeight = 24.dp,
        viewportWidth = 24f, viewportHeight = 24f,
    ).run {
        for (d in paths) {
            addPath(
                pathData = addPathNodes(d),
                fill = null,
                stroke = SolidColor(color),
                strokeLineWidth = 1.6f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            )
        }
        build()
    }

@Composable
fun YogaPoseIcon(
    id: String,
    modifier: Modifier = Modifier,
    size: Dp = 24.dp,
    tint: Color = Color(0xFFA78BFA),
) {
    val vector = remember(id, tint) {
        val paths = POSE_PATHS[id]
        if (paths != null) buildVector(paths, tint) else null
    }
    if (vector != null) {
        Icon(
            imageVector = vector,
            contentDescription = id.replace('_', ' '),
            modifier = modifier.size(size),
            tint = tint,
        )
    }
}

fun hasYogaPoseIcon(id: String): Boolean = id in POSE_PATHS
