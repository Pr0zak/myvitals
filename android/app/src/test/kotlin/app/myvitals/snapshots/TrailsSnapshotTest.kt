package app.myvitals.snapshots

import androidx.compose.foundation.layout.PaddingValues
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

    @Composable
    private fun content(ui: TrailsUi, loading: Boolean = false, error: String? = null) = TrailsContent(
        ui = ui, loading = loading, refreshing = false, error = error,
        nowMs = SampleDataUi5.NOW_MS, dense = false, expandedId = null,
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
        expandedMap = {},
    )
}
