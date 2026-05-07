package app.myvitals.ui.common

import android.content.Context

/** Bundled Leaflet 1.9.4 — read once and cached as raw strings to inline
 * into WebView HTML. Avoids the flaky `loadDataWithBaseURL("file://…")`
 * sub-resource loading on modern Android. */
object LeafletAssets {
    @Volatile private var cssCache: String? = null
    @Volatile private var jsCache: String? = null

    fun css(ctx: Context): String = cssCache ?: synchronized(this) {
        cssCache ?: ctx.assets.open("leaflet/leaflet.css")
            .bufferedReader().use { it.readText() }
            .also { cssCache = it }
    }

    fun js(ctx: Context): String = jsCache ?: synchronized(this) {
        jsCache ?: ctx.assets.open("leaflet/leaflet.js")
            .bufferedReader().use { it.readText() }
            .also { jsCache = it }
    }
}
