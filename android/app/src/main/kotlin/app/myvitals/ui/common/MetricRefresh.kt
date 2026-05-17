package app.myvitals.ui.common

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import kotlinx.coroutines.launch

/**
 * Wrap a metric screen's content so a swipe-down anywhere on the
 * scroll surface triggers `onRefresh`. Used across the detail screens
 * (Steps / HR / HRV / Sleep / Weight / BP / Skin Δ) and VitalsScreen
 * to give the user manual control over the stale-while-revalidate
 * refresh that runs automatically on screen entry.
 *
 * The container takes a `refreshing: Boolean` flag — true while the
 * network fetch is in flight — and renders the standard Material3
 * pull indicator above the content. Caller is responsible for setting
 * the flag to true at the start of `onRefresh` and back to false in
 * a finally block.
 *
 * Usage:
 *   var refreshing by remember { mutableStateOf(false) }
 *   PullableMetricBox(refreshing = refreshing, onRefresh = {
 *     scope.launch {
 *       refreshing = true
 *       try { load(force = true) } finally { refreshing = false }
 *     }
 *   }) {
 *     LazyColumn(...) { items(rows) { ... } }
 *   }
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PullableMetricBox(
    refreshing: Boolean,
    onRefresh: suspend () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val scope = rememberCoroutineScope()
    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { scope.launch { onRefresh() } },
        modifier = modifier.fillMaxSize(),
    ) {
        content()
    }
}
