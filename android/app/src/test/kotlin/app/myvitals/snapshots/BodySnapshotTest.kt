package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.dp
import app.myvitals.sync.VitalTilesResponse
import app.myvitals.ui.neon.BodyContent
import org.junit.Rule
import org.junit.Test

/** The Body tab (UI-3) in the states that matter. */
class BodySnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            BodyContent(
                tiles = SampleDataYouBody.tilesResponse, tilePrefs = null,
                loading = false, refreshing = false, error = null,
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
                nowMs = SampleDataYouBody.NOW_MS,
            )
        }
    }

    /** First launch, request in flight, nothing cached. */
    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            BodyContent(
                tiles = null, tilePrefs = null,
                loading = true, refreshing = false, error = null,
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
            )
        }
    }

    /** Backend unreachable, nothing cached. */
    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            BodyContent(
                tiles = null, tilePrefs = null,
                loading = false, refreshing = false, error = "Couldn't reach the backend.",
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
            )
        }
    }

    /** The server answered with no tiles — worded as "nothing yet", not as
     *  a failure. */
    @Test fun emptyNotFailed() = paparazzi.snapshot {
        NeonFrame {
            BodyContent(
                tiles = VitalTilesResponse(date = "2026-09-22"), tilePrefs = null,
                loading = false, refreshing = false, error = null,
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
            )
        }
    }
}
