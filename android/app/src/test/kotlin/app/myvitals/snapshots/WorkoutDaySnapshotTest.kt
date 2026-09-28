package app.myvitals.snapshots

import app.myvitals.ui.strength.StrengthDayViewContent
import org.junit.Rule
import org.junit.Test

/** A past workout opened from the week strip (`StrengthDayViewScreen`). */
class WorkoutDaySnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    private fun shoot(scroll: Int = 0) = paparazzi.snapshot {
        NeonFrame(scroll) {
            StrengthDayViewContent(
                dateIso = SampleDataWorkout.completed.date,
                workout = SampleDataWorkout.completed,
                loading = false, error = null, notFound = false,
                catalog = SampleDataWorkout.catalog,
                backendBaseUrl = "",
                onBack = {},
            )
        }
    }

    @Test fun completed_1() = shoot()
    @Test fun completed_2() = shoot(VIEWPORT_DP - 80)
    @Test fun notFound() = paparazzi.snapshot {
        NeonFrame {
            StrengthDayViewContent("2026-09-20", null, false, null, true, emptyMap(), "", {})
        }
    }
}
