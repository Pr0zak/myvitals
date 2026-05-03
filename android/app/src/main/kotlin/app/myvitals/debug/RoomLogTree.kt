package app.myvitals.debug

import android.content.Context
import app.myvitals.data.AppDatabase
import app.myvitals.data.LogEntry
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Timber tree that persists log entries to Room. Tag inference walks the stack
 * at call time (Timber's auto-tag only ships with DebugTree).
 *
 * Inserts run on Dispatchers.IO so callers never block; failures fall back to
 * android.util.Log to avoid recursive logging.
 */
class RoomLogTree(context: Context) : Timber.Tree() {

    private val appContext = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        // Resolve the tag synchronously so Throwable().stackTrace reflects the caller,
        // not the coroutine that does the DB insert.
        val effectiveTag = tag ?: inferTag()
        val nowMs = System.currentTimeMillis()
        val stack = t?.stackTraceToString()

        scope.launch {
            try {
                AppDatabase.get(appContext).logs().insert(
                    LogEntry(
                        tsEpochMs = nowMs,
                        level = priority,
                        tag = effectiveTag,
                        message = message,
                        stack = stack,
                    )
                )
            } catch (e: Throwable) {
                android.util.Log.e("RoomLogTree", "insert failed", e)
            }
        }
    }

    private fun inferTag(): String? {
        return try {
            Throwable().stackTrace
                .firstOrNull { frame ->
                    val cls = frame.className
                    IGNORED_PREFIXES.none { cls.startsWith(it) }
                }
                ?.className
                ?.substringAfterLast('.')
                ?.replace(ANON_CLASS_SUFFIX, "")
                ?.take(40)
        } catch (e: Throwable) {
            null
        }
    }

    companion object {
        private val IGNORED_PREFIXES = listOf(
            "timber.log.",
            "app.myvitals.debug.RoomLogTree",
            "java.lang.Thread",
            "kotlinx.coroutines.",
            "kotlin.coroutines.",
            "dalvik.system.",
        )
        private val ANON_CLASS_SUFFIX = Regex("\\$\\d+$")
    }
}
