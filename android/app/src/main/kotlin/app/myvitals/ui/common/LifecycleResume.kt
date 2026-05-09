package app.myvitals.ui.common

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/**
 * Runs `onResume` whenever the host's lifecycle hits ON_RESUME and at
 * least `staleAfterMs` have passed since the last invocation. Replaces
 * the "I just opened the app, why is the data still showing 4h-old
 * numbers" UX. Initial composition does NOT trigger — initial fetch
 * is the caller's responsibility (LaunchedEffect(Unit) etc.); this
 * only handles the resume path.
 */
@Composable
fun LifecycleResumeEffect(
    staleAfterMs: Long = 60_000L,
    onResume: () -> Unit,
) {
    val owner = LocalLifecycleOwner.current
    val callback by rememberUpdatedState(onResume)
    DisposableEffect(owner) {
        var lastFiredAt = System.currentTimeMillis()
        var firstResume = true
        val obs = LifecycleEventObserver { _, event ->
            if (event != Lifecycle.Event.ON_RESUME) return@LifecycleEventObserver
            if (firstResume) {
                firstResume = false
                lastFiredAt = System.currentTimeMillis()
                return@LifecycleEventObserver
            }
            val now = System.currentTimeMillis()
            if (now - lastFiredAt >= staleAfterMs) {
                lastFiredAt = now
                runCatching { callback() }
            }
        }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
}
