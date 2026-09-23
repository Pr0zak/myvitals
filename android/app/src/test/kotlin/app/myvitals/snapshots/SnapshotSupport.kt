package app.myvitals.snapshots

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.requiredHeight
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonTheme

/**
 * Paparazzi shrinks every image to 1000 px on its long side, so one very
 * tall capture of a scrolling screen comes out a few hundred pixels wide and
 * unreadable. Instead each test renders a normal phone viewport and shifts
 * the page up by [scrollDp] — one image per scroll position, which is also
 * what a person actually sees.
 */
fun screenshotRule() = Paparazzi(
    deviceConfig = DeviceConfig.PIXEL_5,
    theme = "android:Theme.Material.NoActionBar",
    maxPercentDifference = 0.1,
)

/** Pixel 5 viewport height in dp (2340 px at 440 dpi). */
const val VIEWPORT_DP = 851

@Composable
fun NeonFrame(scrollDp: Int = 0, content: @Composable () -> Unit) {
    NeonTheme {
        Box(Modifier.background(NeonMV.Bg), contentAlignment = Alignment.TopStart) {
            // Give the screen far more height than the viewport so its own
            // scroll column lays everything out, then slide it up.
            Box(
                Modifier
                    .fillMaxWidth()
                    // Anchor the oversized box to the TOP; a bare
                    // requiredHeight taller than its parent is centred.
                    .wrapContentHeight(Alignment.Top, unbounded = true)
                    .requiredHeight(6000.dp)
                    .offset(y = (-scrollDp).dp),
                contentAlignment = Alignment.TopStart,
            ) { content() }
        }
    }
}
