package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.dp
import app.myvitals.sync.FastingSession
import app.myvitals.ui.FastingContent
import org.junit.Rule
import org.junit.Test

/** Fasting (UI-6): stage ring with server ticks, history bars, 2x2 stats. */
class FastingSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun active_1() = render(SampleDataUi6.fastActive, true, 0)
    @Test fun active_2() = render(SampleDataUi6.fastActive, true, VIEWPORT_DP - 60)

    /** Not fasting: the protocol carousel. */
    @Test fun idle() = render(null, true, 0)

    @Test fun loading() = render(null, false, 0, history = emptyList(), stats = false)

    /** Unreachable with nothing cached: a failure card, never the picker. */
    @Test fun failed() = render(
        null, false, 0, history = emptyList(), stats = false, error = "Couldn't reach the backend.",
    )

    private fun render(
        current: FastingSession?,
        known: Boolean,
        scroll: Int,
        history: List<FastingSession> = SampleDataUi6.fastHistory,
        stats: Boolean = true,
        error: String? = null,
    ) = paparazzi.snapshot {
        NeonFrame(scroll) {
            FastingContent(
                current = current, currentKnown = known, history = history,
                stats = if (stats) SampleDataUi6.fastStats else null,
                loading = !known && error == null, error = error, actionError = null,
                nowMs = SampleDataUi6.NOW_MS, selected = "16:8", busy = false, logSaving = false, logMsg = null,
                refreshing = false, contentPadding = PaddingValues(0.dp),
                onBack = {}, onRefresh = {}, onSelect = {}, onStart = {}, onEnd = {}, onLog = { _, _ -> },
            )
        }
    }
}
