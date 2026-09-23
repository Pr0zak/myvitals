package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.dp
import app.myvitals.ui.common.WeeklyLoadCard
import app.myvitals.ui.neon.RingsContent
import org.junit.Rule
import org.junit.Test

/** The Today tab (`RingsScreen`) in the states that matter. */
class TodayScreenSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)
    @Test fun loaded_3() = loaded(2 * (VIEWPORT_DP - 60))

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            RingsContent(
                summary = SampleData.summary,
                readiness = SampleData.readiness,
                rollup = SampleData.rollup,
                vitalTiles = SampleData.tiles,
                week = SampleData.week,
                tilePrefs = null,
                groupOrder = SampleData.groupOrder,
                narrativeEvents = listOf(SampleData.sleepEvent),
                focusCounts = SampleData.focus,
                error = null, loading = false, refreshing = false,
                contentPadding = PaddingValues(0.dp),
                onOpen = {},
                weeklyLoad = { WeeklyLoadCard(SampleData.trainingLoad) },
                onRefresh = {}, onVote = { _, _ -> },
            )
        }
    }

    /** Backend unreachable on a cold start: nothing cached, one error. */
    @Test fun unreachable() = paparazzi.snapshot {
        NeonFrame {
            RingsContent(
                summary = null, readiness = null, rollup = null,
                vitalTiles = emptyList(), week = null, tilePrefs = null,
                groupOrder = emptyList(), narrativeEvents = emptyList(),
                focusCounts = emptyMap(),
                error = "Couldn't reach the backend.", loading = false, refreshing = false,
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, weeklyLoad = {}, onRefresh = {}, onVote = { _, _ -> },
            )
        }
    }

    /** First launch, request in flight. */
    @Test fun loading() = paparazzi.snapshot {
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
