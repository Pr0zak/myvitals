package app.myvitals.snapshots

import androidx.compose.runtime.Composable
import app.myvitals.sync.ActivityRow
import app.myvitals.ui.activities.ActivityDetailContent
import org.junit.Rule
import org.junit.Test

/** Activity detail (UI-5): map-first hero, big numbers, zone bands. */
class ActivityDetailSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun withMap_1() = paparazzi.snapshot { NeonFrame(0) { content(SampleDataUi5.ride, hr = true) } }
    @Test fun withMap_2() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP - 60) { content(SampleDataUi5.ride, hr = true) }
    }

    /** No route: the category-tinted card holds the hero's place. */
    @Test fun noMap() = paparazzi.snapshot {
        NeonFrame { content(SampleDataUi5.walkNoRoute, hr = false) }
    }

    /** An edit failed: an inline notice above the loaded activity, which
     *  stays on screen. */
    @Test fun editFailed() = paparazzi.snapshot {
        NeonFrame {
            content(SampleDataUi5.ride, hr = true, notice = "Edit failed: duration must be positive")
        }
    }

    @Test fun loading() = paparazzi.snapshot { NeonFrame { content(null, hr = false, loading = true) } }

    /** Nothing cached and the request failed: say so, with a retry. */
    @Test fun failed() = paparazzi.snapshot {
        NeonFrame { content(null, hr = false, error = "Couldn't reach the backend.") }
    }

    @Composable
    private fun content(
        a: ActivityRow?,
        hr: Boolean,
        loading: Boolean = false,
        error: String? = null,
        notice: String? = null,
    ) = ActivityDetailContent(
        activity = a, trails = SampleDataUi5.trailsForDetail,
        hrPoints = if (hr) SampleDataUi5.hrPoints else emptyList(),
        zones = if (hr) SampleDataUi5.zones else null,
        loading = loading, error = error, notice = notice, zone = SampleDataUi5.ZONE,
        savingType = false,
        onBack = {}, onRetry = {}, onDismissNotice = {}, onChangeType = {}, onUndoType = {},
        onEdit = {}, onPickTrail = {},
        map = { _, m -> MapPlaceholderUi5(m) },
    )
}
