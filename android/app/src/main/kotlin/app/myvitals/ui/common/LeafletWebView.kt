package app.myvitals.ui.common

import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import timber.log.Timber

/**
 * WebView host for inlined Leaflet HTML. Both per-trail mini maps and
 * the aggregate trail-status map render Leaflet via WebView with the
 * CSS + JS bundled from app assets — this composable wraps the
 * WebView setup so each caller only has to build their unique HTML
 * payload.
 *
 * The HTML must be a complete document; the consumer is responsible
 * for `<head>` (including viewport + Leaflet CSS+JS) and `<body>`. See
 * `app/myvitals/ui/trails/TrailsScreen.kt` for examples.
 *
 * `tag` is a stable identity used to detect when the HTML changed and
 * the WebView should re-render. Pass the same value as the `html`
 * input unless you need a different cache key.
 */
@Composable
fun LeafletWebView(html: String, modifier: Modifier = Modifier) {
    AndroidView(
        factory = { wctx ->
            WebView(wctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.loadsImagesAutomatically = true
                settings.mixedContentMode =
                    android.webkit.WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                webViewClient = WebViewClient()
                webChromeClient = object : android.webkit.WebChromeClient() {
                    override fun onConsoleMessage(
                        m: android.webkit.ConsoleMessage,
                    ): Boolean {
                        Timber.tag("LeafletWebView").i(
                            "[${m.messageLevel()}] ${m.message()} "
                            + "(${m.sourceId()}:${m.lineNumber()})",
                        )
                        return true
                    }
                }
                setBackgroundColor(android.graphics.Color.parseColor("#0F1620"))
                loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
                tag = html
            }
        },
        update = { webview ->
            if (webview.tag != html) {
                webview.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
                webview.tag = html
            }
        },
        modifier = modifier,
    )
}
