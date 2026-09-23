package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.unit.dp
import app.myvitals.ui.common.LocalShimmerShift
import app.myvitals.ui.neon.RingsContent
import org.junit.Rule
import org.junit.Test

/**
 * Frames of Today's loading placeholders across one shimmer sweep, for an
 * animated preview. Paparazzi's clock offset does not advance an infinite
 * transition, so the sweep position is pinned per frame through
 * [LocalShimmerShift] instead.
 *
 * Not a regression check — an animation is not something a golden should
 * pin — so it only runs with `-PanimFrames`.
 */
class TodayLoadingAnimationTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun frames() {
        if (System.getProperty("animFrames") == null) return
        val steps = 16
        for (i in 0 until steps) {
            val shift = -400f + 1200f * i / steps
            paparazzi.snapshot(name = "loading_f%02d".format(i)) {
                CompositionLocalProvider(LocalShimmerShift provides shift) {
                    NeonFrame {
                        RingsContent(
                            summary = null, readiness = null, rollup = null,
                            vitalTiles = emptyList(), week = null, tilePrefs = null,
                            groupOrder = emptyList(), narrativeEvents = emptyList(),
                            focusCounts = emptyMap(),
                            error = null, loading = true, refreshing = false,
                            contentPadding = PaddingValues(0.dp),
                            onOpen = {}, weeklyLoad = {}, onRefresh = {}, onVote = { _, _ -> },
                        )
                    }
                }
            }
        }
    }
}
