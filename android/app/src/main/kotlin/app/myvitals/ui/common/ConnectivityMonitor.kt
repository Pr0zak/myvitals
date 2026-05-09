package app.myvitals.ui.common

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

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
