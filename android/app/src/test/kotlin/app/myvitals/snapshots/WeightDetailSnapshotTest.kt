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


class WeightDetailSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    private val winEnd = D.NOW_MS
    private val winStart = D.TODAY.minusDays(29)
        .atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            WeightDetailContent(
                range = VitalRange.MONTH, data = D.weight, tile = D.weightTile,
                winStart = winStart, winEnd = winEnd,
                loading = false, refreshing = false, error = null,
                onBack = {}, onRange = {}, onRefresh = {},
            )
        }
    }

    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            CompositionLocalProvider(LocalShimmerShift provides DETAIL_SHIFT) {
                WeightDetailContent(
                    range = VitalRange.MONTH, data = null, tile = null,
                    winStart = winStart, winEnd = winEnd,
                    loading = true, refreshing = false, error = null,
                    onBack = {}, onRange = {}, onRefresh = {},
                )
            }
        }
    }

    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            WeightDetailContent(
                range = VitalRange.MONTH, data = null, tile = null,
                winStart = winStart, winEnd = winEnd,
                loading = false, refreshing = false, error = DETAIL_FAIL,
                onBack = {}, onRange = {}, onRefresh = {},
            )
        }
    }

    /** The old screen replaced a cached chart with the error text. */
    @Test fun failedWithCache() = paparazzi.snapshot {
        NeonFrame {
            WeightDetailContent(
                range = VitalRange.MONTH, data = D.weight, tile = D.weightTile,
                winStart = winStart, winEnd = winEnd,
                loading = false, refreshing = false, error = DETAIL_FAIL,
                onBack = {}, onRange = {}, onRefresh = {},
            )
        }
    }
}
