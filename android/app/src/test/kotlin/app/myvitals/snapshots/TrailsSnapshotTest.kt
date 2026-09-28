package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Modifier
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.trails.TrailsContent
import app.myvitals.ui.trails.TrailsUi
import org.junit.Rule
import org.junit.Test

/** Trails (UI-5): status hero, starred carousel, grouped rows. */
class TrailsSnapshotTest {
    @get:Rule val paparazzi = screenshotRule()

    @Test fun loaded_1() = paparazzi.snapshot { NeonFrame(0) { content(SampleDataUi5.trailsUi) } }
    @Test fun loaded_2() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP - 60) { content(SampleDataUi5.trailsUi) }
    }

    /** Refresh failed, trails cached: amber banner ABOVE the saved board. */
    @Test fun failedWithCache() = paparazzi.snapshot {
        NeonFrame { content(SampleDataUi5.trailsUi, error = "Couldn't reach the backend.") }
    }

    @Test fun loading() = paparazzi.snapshot { NeonFrame { content(TrailsUi(), loading = true) } }

    /** Condensed rows: a tap brings back the trail's own message (and map). */
    @Test fun denseTappedOpen() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP / 2) { content(SampleDataUi5.trailsUi, dense = true, expandedId = 3) }
    }
    @Test fun denseTappedClosed() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP - 60) { content(SampleDataUi5.trailsUi, dense = true, expandedId = 8) }
    }
    @Test fun denseTappedNoPin() = paparazzi.snapshot {
        NeonFrame(VIEWPORT_DP - 60) { content(SampleDataUi5.trailsUi, dense = true, expandedId = 9) }
    }

    @Composable
    private fun content(ui: TrailsUi, loading: Boolean = false, error: String? = null,
                        dense: Boolean = false, expandedId: Long? = null) = TrailsContent(
        ui = ui, loading = loading, refreshing = false, error = error,
        nowMs = SampleDataUi5.NOW_MS, dense = dense, expandedId = expandedId,
        actionResult = null, recentRides = emptyList(),
        linking = false, fetchingOsm = false,
        contentPadding = PaddingValues(0.dp),
        onRefresh = {}, onToggleDense = {}, onOpenMap = {}, onOpenBoard = null,
        onLinkActivities = {}, onFetchOsm = {}, onDismissAction = {},
        onTapTrail = {}, onSubscribeToggle = {}, onEditPin = {},
        onOpenTrailVisits = {}, onLinkRide = {},
        miniMap = { m ->
            MapPlaceholderUi5(m, route = false, pins = listOf(
                NeonMV.Lime, NeonMV.Lime, NeonMV.Amber, NeonMV.Lime,
                NeonMV.Bad, NeonMV.Lime, NeonMV.Muted,
            ))
        },
        expandedMap = {
            MapPlaceholderUi5(Modifier.fillMaxWidth().height(150.dp), route = true,
                pins = listOf(NeonMV.Lime))
        },
    )
}
