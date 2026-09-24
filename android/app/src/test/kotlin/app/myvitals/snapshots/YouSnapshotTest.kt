package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.dp
import app.myvitals.ui.neon.YouContent
import app.myvitals.ui.neon.YouData
import org.junit.Rule
import org.junit.Test

/** The You tab (UI-3) in the states that matter. */
class YouSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = loaded(0)
    @Test fun loaded_2() = loaded(VIEWPORT_DP - 60)

    private fun loaded(scroll: Int) = paparazzi.snapshot {
        NeonFrame(scroll) {
            YouContent(
                data = SampleDataYouBody.you,
                loading = false, refreshing = false, error = null,
                todayLabel = "Tue, Sep 22",
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
                zone = SampleDataYouBody.ZONE,
            )
        }
    }

    /** A real "not fasting" answer and no active sober streak: neutral
     *  invitations, never warnings. */
    @Test fun notFasting() = paparazzi.snapshot {
        NeonFrame {
            YouContent(
                data = SampleDataYouBody.you.copy(
                    fasting = null, fastingKnown = true,
                    sober = SampleDataYouBody.sober.copy(active = null, days = null),
                ),
                loading = false, refreshing = false, error = null,
                todayLabel = "Tue, Sep 22",
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
                zone = SampleDataYouBody.ZONE,
            )
        }
    }

    /** First launch, requests in flight, nothing cached. */
    @Test fun loading() = paparazzi.snapshot {
        NeonFrame {
            YouContent(
                data = YouData(), loading = true, refreshing = false, error = null,
                todayLabel = "Tue, Sep 22",
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
            )
        }
    }

    /** Every request failed, nothing cached: the banner and the navigation
     *  grid — no "Not fasting", no "No active goals yet" (UX-F3). */
    @Test fun failed() = paparazzi.snapshot {
        NeonFrame {
            YouContent(
                data = YouData(), loading = false, refreshing = false,
                error = "Couldn't reach the backend.",
                todayLabel = "Tue, Sep 22",
                contentPadding = PaddingValues(0.dp),
                onOpen = {}, onRefresh = {},
            )
        }
    }
}
