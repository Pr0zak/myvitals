package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.dp
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.SoberStreak
import app.myvitals.ui.SoberContent
import org.junit.Rule
import org.junit.Test

/** Sober (UI-6): server milestones on the ring, calm reset below history. */
class SoberSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = render(SampleDataUi6.soberCurrent, 0)
    @Test fun loaded_2() = render(SampleDataUi6.soberCurrent, VIEWPORT_DP - 60)

    /** No active streak: an empty ring and "Start counting", not a failure. */
    @Test fun noActiveStreak() = render(SampleDataUi6.soberNone, 0, history = emptyList())

    /** First open, request in flight. */
    @Test fun loading() = render(null, 0, history = emptyList(), loading = true)

    /** Backend unreachable, nothing cached: says so — never "no streak". */
    @Test fun failed() = render(null, 0, history = emptyList(), error = "Couldn't reach the backend.")

    private fun render(
        current: SoberCurrentResponse?,
        scroll: Int,
        history: List<SoberStreak> = SampleDataUi6.soberHistory,
        loading: Boolean = false,
        error: String? = null,
    ) = paparazzi.snapshot {
        NeonFrame(scroll) {
            SoberContent(
                current = current, history = history, loading = loading, error = error,
                actionError = null, nowMs = SampleDataUi6.NOW_MS, resetting = false, refreshing = false,
                contentPadding = PaddingValues(0.dp), onBack = {}, onReset = {}, onRefresh = {},
            )
        }
    }
}
