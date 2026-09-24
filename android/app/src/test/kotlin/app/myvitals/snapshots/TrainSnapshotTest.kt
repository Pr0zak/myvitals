package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.unit.dp
import app.myvitals.ui.common.LocalShimmerShift
import app.myvitals.ui.neon.TrainHubContent
import org.junit.Rule
import org.junit.Test

/** The Train tab (`TrainHubScreen`, UI-1) in the states that matter. */
class TrainSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            TrainHubContent(
                workout = SampleDataTrain.workout,
                upcoming = SampleDataTrain.upcoming,
                stats = SampleDataTrain.stats,
                muscles = SampleDataTrain.muscles,
                activities = SampleDataTrain.activities,
                yearWorkouts = SampleDataTrain.yearWorkouts,
                activityStats = SampleDataTrain.activityStats,
                loading = false, refreshing = false, error = null,
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
                zone = SampleDataTrain.zone, now = SampleDataTrain.now,
            )
        }
    }

    /** First launch, requests in flight: the hero's shape, shimmering. */
    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            CompositionLocalProvider(LocalShimmerShift provides 200f) {
                TrainHubContent(
                    workout = null, upcoming = emptyList(), stats = null, muscles = null,
                    activities = emptyList(), yearWorkouts = emptyList(), activityStats = null,
                    loading = true, refreshing = false, error = null,
                    contentPadding = PaddingValues(0.dp),
                    onOpen = {}, onRefresh = {},
                    zone = SampleDataTrain.zone, now = SampleDataTrain.now,
                )
            }
        }
    }

    /** Backend unreachable: a banner, and NOT "Rest day" / "No activity". */
    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            TrainHubContent(
                workout = null, upcoming = emptyList(), stats = null, muscles = null,
                activities = emptyList(), yearWorkouts = emptyList(), activityStats = null,
                loading = false, refreshing = false,
                error = "Couldn't load today's plan, activities, workouts, volume.",
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
                zone = SampleDataTrain.zone, now = SampleDataTrain.now,
            )
        }
    }
}
