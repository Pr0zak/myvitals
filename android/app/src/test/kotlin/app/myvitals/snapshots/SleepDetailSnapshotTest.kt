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


class SleepDetailSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            SleepDetailContent(
                nights = D.sleepNights, stats = D.sleepStats, tile = D.sleepTile, raw = D.sleepRaw,
                selectedDay = D.TODAY, today = D.TODAY,
                loading = false, refreshing = false, error = null, onBack = {}, onRefresh = {},
            )
        }
    }

    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            CompositionLocalProvider(LocalShimmerShift provides DETAIL_SHIFT) {
                SleepDetailContent(
                    nights = emptyList(), stats = null, tile = null, raw = emptyList(),
                    selectedDay = D.TODAY, today = D.TODAY,
                    loading = true, refreshing = false, error = null, onBack = {}, onRefresh = {},
                )
            }
        }
    }

    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            SleepDetailContent(
                nights = emptyList(), stats = null, tile = null, raw = emptyList(),
                selectedDay = D.TODAY, today = D.TODAY,
                loading = false, refreshing = false, error = DETAIL_FAIL, onBack = {}, onRefresh = {},
            )
        }
    }
}
