package app.myvitals.snapshots

import app.myvitals.sync.PrepPlanOut
import app.myvitals.ui.meals.PrepContent
import org.junit.Rule
import org.junit.Test

/** Week prep (UI-6): segmented component ring, week strip, fat on every meal. */
class PrepSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun prepDay() = render(SampleDataUi6.prepPlan, "prep", 0)
    @Test fun week_1() = render(SampleDataUi6.prepPlan, "week", 0)
    @Test fun week_2() = render(SampleDataUi6.prepPlan, "week", VIEWPORT_DP - 60)

    /** The server said there is no plan: the planning card. */
    @Test fun noPlan() = render(null, "prep", 0)

    @Test fun loading() = render(null, "prep", 0, known = false)

    /** Unreachable: a failure card, never "No prep plan yet". */
    @Test fun failed() = render(null, "prep", 0, known = false, error = "Couldn't reach the backend.")

    private fun render(
        plan: PrepPlanOut?,
        sub: String,
        scroll: Int,
        known: Boolean = true,
        error: String? = null,
    ) = paparazzi.snapshot {
        NeonFrame(scroll) {
            PrepContent(
                plan = plan, planKnown = known, targets = SampleDataUi6.targets,
                loading = !known && error == null, error = error, notice = null, sub = sub, busy = null,
                generating = false, showTargets = false, draftDays = 5, draftSlots = listOf("lunch", "dinner"),
                today = SampleDataUi6.TODAY,
                onRetry = {}, onSub = {}, onToggleTargets = {}, onDays = {}, onToggleSlot = {},
                onGenerate = {}, onShoppingList = {}, onTick = {}, onStatus = { _, _ -> }, onLog = {},
            )
        }
    }
}
