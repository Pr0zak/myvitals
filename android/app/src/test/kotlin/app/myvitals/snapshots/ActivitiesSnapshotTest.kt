package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import app.myvitals.ui.activities.ActivitiesContent
import org.junit.Rule
import org.junit.Test

/** The Activities feed (UI-5): server YTD hero, week headers, rows. */
class ActivitiesSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = paparazzi.snapshot { NeonFrame(0) { content(error = null) } }
    @Test fun loaded_2() = paparazzi.snapshot { NeonFrame(VIEWPORT_DP - 60) { content(error = null) } }

    /** The refresh failed but a feed is cached: an amber banner above the
     *  saved rows — the rows do not disappear. */
    @Test fun failedWithCache() = paparazzi.snapshot {
        NeonFrame { content(error = "Couldn't reach the backend.") }
    }

    @Composable
    private fun content(error: String?) = ActivitiesContent(
        rows = SampleDataUi5.rows, workouts = SampleDataUi5.workouts, ytd = SampleDataUi5.ytd,
        loading = false, refreshing = false, error = error,
        nowMs = SampleDataUi5.NOW_MS, today = SampleDataUi5.TODAY, zone = SampleDataUi5.ZONE,
        contentPadding = PaddingValues(0.dp),
        onRefresh = {}, onOpenActivity = { _, _ -> }, onOpenStrengthDay = {}, onOpenMap = {},
        onBack = {},
    )
}
