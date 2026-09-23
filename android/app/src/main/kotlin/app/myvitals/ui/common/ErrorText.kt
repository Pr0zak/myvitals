package app.myvitals.ui.common

import retrofit2.HttpException

/**
 * The server's own explanation of a failure, when it gave one (UX-E1).
 *
 * FastAPI puts the reason in `{"detail": "…"}`, and the backend now maps AI
 * provider failures to a readable one there — "The AI is rate-limited right
 * now — try again in a minute." Retrofit's `HttpException.message` is only
 * the status line ("HTTP 503 "), so screens rendering `e.message` showed a
 * bare code for a failure the server had already put into words. Falls back
 * to the exception's own message when the body is not ours.
 *
 * Reading `errorBody()` consumes it, so call this once per exception.
 */
fun Throwable.userMessage(fallback: String = "Something went wrong"): String {
    if (this is HttpException) {
        val detail = try {
            response()?.errorBody()?.string()
                ?.let { org.json.JSONObject(it).opt("detail") as? String }
                ?.takeIf { it.isNotBlank() }
        } catch (_: Exception) {
            null
        }
        if (detail != null) return detail
    }
    return message?.takeIf { it.isNotBlank() } ?: fallback
}
