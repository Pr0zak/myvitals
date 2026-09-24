package app.myvitals.snapshots

import androidx.compose.runtime.CompositionLocalProvider
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.ui.common.LocalShimmerShift
import app.myvitals.ui.strength.CoachCardState
import app.myvitals.ui.strength.StrengthTodayActions
import app.myvitals.ui.strength.StrengthTodayContent
import app.myvitals.ui.strength.StrengthTodayState
import org.junit.Rule
import org.junit.Test

/** The active-workout screen (`StrengthTodayScreen`, UI-2) in the states that matter. */
class WorkoutSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    private fun state(
        workout: StrengthWorkoutDetail?,
        loading: Boolean = false,
        loadError: String? = null,
        restLeftMs: Long = 0L,
    ) = StrengthTodayState().apply {
        this.workout = workout
        catalog = SampleDataWorkout.catalog
        history = SampleDataWorkout.history
        projectedDates = SampleDataWorkout.projectedDates
        this.loading = loading
        this.loadError = loadError
        nowMs = SampleDataWorkout.NOW_MS
        if (restLeftMs > 0) {
            restTotal = 90_000L
            restEndsAt = SampleDataWorkout.NOW_MS + restLeftMs
        }
    }

    private fun shoot(st: StrengthTodayState, scroll: Int = 0) = paparazzi.snapshot {
        NeonFrame(scroll) {
            CompositionLocalProvider(LocalShimmerShift provides 200f) {
                StrengthTodayContent(
                    st = st,
                    coach = CoachCardState(),
                    actions = StrengthTodayActions(onBack = {}),
                    today = SampleDataWorkout.today,
                )
            }
        }
    }

    /** Mid-session: the NOW hero with steppers, chips, the hero's grid. */
    @Test fun inProgress_1() = shoot(state(SampleDataWorkout.workout))
    /** Further down: up-next lines, superset, skipped slot, done row, week. */
    @Test fun inProgress_2() = shoot(state(SampleDataWorkout.workout), scroll = VIEWPORT_DP - 80)
    /** Just logged a set: the rest ring replaces the steppers inside the hero. */
    @Test fun resting() = shoot(state(SampleDataWorkout.workout, restLeftMs = 52_000L))
    /** Stamped: the summary hero from session_summary, then finished rows. */
    @Test fun completed_1() = shoot(state(SampleDataWorkout.completed))
    @Test fun completed_2() = shoot(state(SampleDataWorkout.completed), scroll = VIEWPORT_DP - 80)
    /** First load: the hero's shape, shimmering. */
    @Test fun loading() = shoot(state(null, loading = true))
    /** Backend unreachable: an amber banner, and NOT "Generate today's plan". */
    @Test fun failed() = shoot(state(null, loadError = "Failed to connect to the server"))
    /** A timed, bilateral hold is NOW: seconds readout and a Start button. */
    @Test fun timedHold() = shoot(state(SampleDataWorkout.timedHold))
}
