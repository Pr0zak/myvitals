package app.myvitals.ui.common

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Tracks whether the device has any usable network. Returns a State
 * that recomposes when connectivity flips. Collects via
 * ConnectivityManager.NetworkCallback so it's accurate within ~1s of
 * a real change (vs polling).
 *
 * Note: "validated" is more reliable than "connected" — captive
 * portals and degraded hotspots can be CONNECTED without functional
 * internet. We only flip to true when the network has the
 * NET_CAPABILITY_VALIDATED capability set.
 */
@Composable
fun rememberOnlineState(): State<Boolean> {
    val ctx = LocalContext.current
    val online = remember { mutableStateOf(initialOnline(ctx)) }

    DisposableEffect(ctx) {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        if (cm == null) {
            // Shouldn't happen; bail out cleanly.
            return@DisposableEffect onDispose {}
        }
        val req = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                val caps = cm.getNetworkCapabilities(network)
                if (caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true) {
                    online.value = true
                }
            }
            override fun onCapabilitiesChanged(
                network: Network, caps: NetworkCapabilities,
            ) {
                online.value = caps.hasCapability(
                    NetworkCapabilities.NET_CAPABILITY_VALIDATED,
                )
            }
            override fun onLost(network: Network) {
                // Re-check via system state — another network might still
                // be active (e.g. dropping wifi while LTE is up).
                online.value = initialOnline(ctx)
            }
        }
        cm.registerNetworkCallback(req, cb)
        onDispose { cm.unregisterNetworkCallback(cb) }
    }
    return online
}

private fun initialOnline(ctx: Context): Boolean {
    val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        ?: return true  // assume online so we don't show false-positive offline banner
    val active = cm.activeNetwork ?: return false
    val caps = cm.getNetworkCapabilities(active) ?: return false
    return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
}

/**
 * Slim app-wide status bar shown above the nav content. Tells the user
 * why they might be seeing saved data:
 *   - device offline → "Offline — showing saved data…"
 *   - online but the backend isn't answering (the ServerStatus signal,
 *     updated by the OkHttp interceptor on connect/timeout failures) →
 *     "Can't reach server…"
 * Renders nothing when everything's healthy, so it's invisible in the
 * normal case.
 */
@Composable
fun ConnectionBanner() {
    val online by rememberOnlineState()
    val server by app.myvitals.sync.ServerStatus.state.collectAsState()

    val (text, bg) = when {
        !online -> "Offline — showing saved data. Changes sync when you reconnect." to
            androidx.compose.ui.graphics.Color(0xFFF59E0B)
        server == app.myvitals.sync.ServerStatus.State.UNREACHABLE ->
            "Can't reach server — showing saved data, retrying…" to
                androidx.compose.ui.graphics.Color(0xFFEF4444)
        else -> return
    }

    androidx.compose.foundation.layout.Row(
        modifier = androidx.compose.ui.Modifier
            .fillMaxWidth()
            .background(bg.copy(alpha = 0.16f))
            .padding(horizontal = 14.dp, vertical = 6.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        androidx.compose.foundation.layout.Box(
            androidx.compose.ui.Modifier
                .size(7.dp)
                .clip(androidx.compose.foundation.shape.CircleShape)
                .background(bg),
        )
        androidx.compose.foundation.layout.Spacer(androidx.compose.ui.Modifier.width(8.dp))
        androidx.compose.material3.Text(
            text,
            color = app.myvitals.ui.MV.OnSurface,
            fontSize = 12.sp,
        )
    }
}
