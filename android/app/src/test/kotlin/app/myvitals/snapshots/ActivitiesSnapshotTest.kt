package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import app.myvitals.ui.activities.ActivitiesContent
import org.junit.Rule
import org.junit.Test

/** The Activities feed (UI-5): server YTD hero, week headers, rows; plus
 *  UI-F2's period stats row, personal-records card and month headers. */
class ActivitiesSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = paparazzi.snapshot { NeonFrame(0) { content(error = null) } }
    @Test fun loaded_2() = paparazzi.snapshot { NeonFrame(VIEWPORT_DP - 60) { content(error = null) } }

    /** The refresh failed but a feed is cached: an amber banner above the
     *  saved rows — the rows do not disappear. */
    @Test fun failedWithCache() = paparazzi.snapshot {
        NeonFrame { content(error = "Couldn't reach the backend.") }
    }

    /** UI-F2: period totals ("—" for kcal nothing carried) and records
     *  (the null suffer-score record is left out, not shown as 0). */
    @Test fun periodAndRecords() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP - 260) { content(error = null, summary = true) }
    }

    /** UI-F2: group-by-month headers carry the server's month totals. */
    @Test fun groupedByMonth() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP + 330) { content(error = null, summary = true, byMonth = true) }
    }

    /** UI-F2: the period request failed — an amber note, the last figures
     *  stay, nothing renders as an empty period. */
    @Test fun summaryFailed() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP - 260) { content(error = null, summary = true, summaryFailed = true) }
    }

    @Composable
    private fun content(
        error: String?,
        summary: Boolean = false,
        byMonth: Boolean = false,
        summaryFailed: Boolean = false,
    ) = ActivitiesContent(
        rows = SampleDataUi5.rows, workouts = SampleDataUi5.workouts,
        ytd = if (summary) SampleDataUiF2.ytd else SampleDataUi5.ytd,
        loading = false, refreshing = false, error = error,
        nowMs = SampleDataUi5.NOW_MS, today = SampleDataUi5.TODAY, zone = SampleDataUi5.ZONE,
        contentPadding = PaddingValues(0.dp),
        onRefresh = {}, onOpenActivity = { _, _ -> }, onOpenStrengthDay = {}, onOpenMap = {},
        onBack = {},
        periodStats = if (summary) SampleDataUiF2.stats else null,
        records = if (summary) SampleDataUiF2.records else null,
        summaryFailed = summaryFailed,
        initialGroupByMonth = byMonth,
    )
}
