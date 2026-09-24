package app.myvitals.snapshots

import androidx.compose.runtime.CompositionLocalProvider
import app.myvitals.ui.common.LocalShimmerShift
import app.myvitals.ui.vitals.HrDetailContent
import app.myvitals.ui.vitals.SleepDetailContent
import app.myvitals.ui.vitals.StepsDetailContent
import app.myvitals.ui.vitals.VitalRange
import app.myvitals.ui.vitals.WeightDetailContent
import org.junit.Rule
import org.junit.Test
import app.myvitals.snapshots.SampleDataDetail as D

/*
 * UI-4 — the four metric detail screens, each loaded (two scroll positions),
 * cold loading (the accent shimmer, pinned mid-sweep so the image is stable)
 * and failed with nothing cached.
 */

internal const val DETAIL_FAIL = "Couldn't reach the backend."
internal const val DETAIL_SHIFT = 200f

class StepsDetailSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            StepsDetailContent(
                rows = D.stepRows, stats = D.stepStats, tile = D.stepsTile, hourly = D.hourly,
                selectedDay = D.TODAY, today = D.TODAY,
                loading = false, refreshing = false, error = null, onBack = {}, onRefresh = {},
            )
        }
    }

    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            CompositionLocalProvider(LocalShimmerShift provides DETAIL_SHIFT) {
                StepsDetailContent(
                    rows = emptyList(), stats = null, tile = null, hourly = null,
                    selectedDay = D.TODAY, today = D.TODAY,
                    loading = true, refreshing = false, error = null, onBack = {}, onRefresh = {},
                )
            }
        }
    }

    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            StepsDetailContent(
                rows = emptyList(), stats = null, tile = null, hourly = null,
                selectedDay = D.TODAY, today = D.TODAY,
                loading = false, refreshing = false, error = DETAIL_FAIL, onBack = {}, onRefresh = {},
            )
        }
    }

    /** A refresh failed over a cached render: the banner sits ABOVE the
     *  numbers and nothing cached is hidden. */
    @Test fun failedWithCache() = paparazzi.snapshot {
        NeonFrame {
            StepsDetailContent(
                rows = D.stepRows, stats = D.stepStats, tile = D.stepsTile, hourly = D.hourly,
                selectedDay = D.TODAY, today = D.TODAY,
                loading = false, refreshing = false, error = DETAIL_FAIL, onBack = {}, onRefresh = {},
            )
        }
    }
}
