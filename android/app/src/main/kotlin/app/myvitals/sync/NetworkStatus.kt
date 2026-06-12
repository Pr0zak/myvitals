package app.myvitals.sync

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * App-wide backend reachability signal so the UI can tell the user what's
 * going on without every screen reinventing it.
 *
 * - [NetworkStatus.isOnline] is a cheap, non-Composable device-connectivity
 *   check used by repositories to skip a doomed network call and buffer
 *   immediately (instant offline behaviour, no waiting on a timeout).
 * - [ServerStatus] is updated by an OkHttp interceptor on every call:
 *   OK on any response, UNREACHABLE on an IOException (connect refused /
 *   timeout / DNS). The app-level banner observes it to distinguish
 *   "device offline" from "online but the server isn't answering".
 */
object NetworkStatus {
    fun isOnline(context: Context): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java)
            ?: return true  // fail open — don't wrongly short-circuit
        val net = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(net) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }
}

object ServerStatus {
    enum class State { UNKNOWN, OK, UNREACHABLE }

    private val _state = MutableStateFlow(State.UNKNOWN)
    val state: StateFlow<State> = _state

    fun markOk() { _state.value = State.OK }
    fun markUnreachable() { _state.value = State.UNREACHABLE }
}
