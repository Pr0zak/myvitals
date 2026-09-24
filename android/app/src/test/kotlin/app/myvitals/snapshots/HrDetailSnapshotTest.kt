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
import app.myvitals.snapshots.SampleDataUiF1 as F

/*
 * UI-4 — the four metric detail screens, each loaded (two scroll positions),
 * cold loading (the accent shimmer, pinned mid-sweep so the image is stable)
 * and failed with nothing cached.
 */


class HrDetailSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = day(0)
    @Test fun loaded_2() = day(VIEWPORT_DP - 60)

    private fun day(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            HrDetailContent(
                range = VitalRange.DAY, live = D.hrLive, rows = emptyList(), rangeStats = null,
                restingTile = D.restingTile, bands = emptyList(), markers = emptyList(),
                selectedDay = D.TODAY, today = D.TODAY, nowMs = D.NOW_MS,
                loading = false, refreshing = false, error = null,
                onBack = {}, onRange = {}, onRefresh = {},
            )
        }
    }

    /** 30-day view: resting HR trend, server window stats, weekday means.
     *  UI-F1: month_2 scrolls to the vs-previous-window card (amber — resting
     *  HR rose) and the HR-by-activity bars with a too-few-to-average line. */
    @Test fun month() = month(0)
    @Test fun month_2() = month(VIEWPORT_DP - 60)

    private fun month(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            HrDetailContent(
                range = VitalRange.MONTH, live = null, rows = D.stepRows, rangeStats = F.restingStats,
                restingTile = D.restingTile, bands = emptyList(), markers = emptyList(),
                selectedDay = D.TODAY, today = D.TODAY, nowMs = D.NOW_MS,
                loading = false, refreshing = false, error = null,
                onBack = {}, onRange = {}, onRefresh = {},
                hrByActivity = F.hrByActivity,
            )
        }
    }

    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            CompositionLocalProvider(LocalShimmerShift provides DETAIL_SHIFT) {
                HrDetailContent(
                    range = VitalRange.DAY, live = null, rows = emptyList(), rangeStats = null,
                    restingTile = null, bands = emptyList(), markers = emptyList(),
                    selectedDay = D.TODAY, today = D.TODAY, nowMs = D.NOW_MS,
                    loading = true, refreshing = false, error = null,
                    onBack = {}, onRange = {}, onRefresh = {},
                )
            }
        }
    }

    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            HrDetailContent(
                range = VitalRange.DAY, live = null, rows = emptyList(), rangeStats = null,
                restingTile = null, bands = emptyList(), markers = emptyList(),
                selectedDay = D.TODAY, today = D.TODAY, nowMs = D.NOW_MS,
                loading = false, refreshing = false, error = DETAIL_FAIL,
                onBack = {}, onRange = {}, onRefresh = {},
            )
        }
    }
}
