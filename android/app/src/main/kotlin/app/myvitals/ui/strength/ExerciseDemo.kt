package app.myvitals.ui.strength

import android.provider.Settings
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import coil.compose.AsyncImage

/**
 * ANIM-1: crossfade an exercise's two catalog frames (0.jpg start, 1.jpg
 * end/contracted) into a subtle pseudo-animation. The front frame is the
 * always-opaque base — a graceful fallback if the back frame is slow or 404s —
 * and the back frame's alpha loops over it (~2.5s each way). Degrades to a
 * single static frame when backUrl is null (the .png icon case) or the user
 * has animations turned off (ANIMATOR_DURATION_SCALE == 0). The caller sizes
 * the box; both frames Crop-fill it so they register exactly.
 */
@Composable
fun ExerciseDemo(
    frontUrl: String,
    backUrl: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val reduceMotion = remember {
        Settings.Global.getFloat(
            context.contentResolver,
            Settings.Global.ANIMATOR_DURATION_SCALE, 1f,
        ) == 0f
    }
    Box(modifier, contentAlignment = Alignment.Center) {
        AsyncImage(
            model = frontUrl,
            contentDescription = contentDescription,
            contentScale = ContentScale.Crop,
            modifier = Modifier.matchParentSize(),
        )
        if (backUrl != null && !reduceMotion) {
            val transition = rememberInfiniteTransition(label = "exercise-demo")
            val alpha by transition.animateFloat(
                initialValue = 0f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(2500, easing = FastOutSlowInEasing),
                    repeatMode = RepeatMode.Reverse,
                ),
                label = "exercise-demo-alpha",
            )
            AsyncImage(
                model = backUrl,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                alpha = alpha,
                modifier = Modifier.matchParentSize(),
            )
        }
    }
}
