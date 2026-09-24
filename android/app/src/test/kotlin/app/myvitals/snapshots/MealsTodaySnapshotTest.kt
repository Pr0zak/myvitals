package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.dp
import app.myvitals.sync.LogDayOut
import app.myvitals.sync.PrepTargetsOut
import app.myvitals.ui.meals.MealsTodayContent
import org.junit.Rule
import org.junit.Test

/** Meals Today (UI-6): energy ring + per-meal fat column, verdict stripes. */
class MealsTodaySnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = render(SampleDataUi6.mealsDay, SampleDataUi6.targets, 0)
    @Test fun loaded_2() = render(SampleDataUi6.mealsDay, SampleDataUi6.targets, VIEWPORT_DP - 60)

    /** Nothing logged and no target: ring at 0 saying so, four dashed slots. */
    @Test fun emptyNoTarget() = render(SampleDataUi6.mealsEmptyDay, SampleDataUi6.noTargets, 0)

    @Test fun loading() = render(null, null, 0)

    /** Unreachable with nothing cached: says so — never "nothing logged". */
    @Test fun failed() = render(null, null, 0, error = "Couldn't reach the backend.")

    private fun render(day: LogDayOut?, targets: PrepTargetsOut?, scroll: Int, error: String? = null) =
        paparazzi.snapshot {
            NeonFrame(scroll) {
                MealsTodayContent(
                    day = day, targets = targets,
                    recents = if (day != null) SampleDataUi6.recents else emptyList(),
                    loading = day == null && error == null, error = error, actionError = null, busy = false,
                    refreshing = false, dateLabel = "Tue 22 Sep", contentPadding = PaddingValues(0.dp),
                    onBack = {}, onRefresh = {}, onAdd = {}, onOpenMore = {}, onRepeatYesterday = {},
                    onRecent = {},
                )
            }
        }
}
