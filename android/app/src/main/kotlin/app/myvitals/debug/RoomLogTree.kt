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
 * Timber tree that persists log entries into the Room "logs" table.
 * Inserts happen on Dispatchers.IO so calls to Timber.* never block the caller.
 *
 * Failures inside the tree fall back to android.util.Log to avoid recursion.
 */
class RoomLogTree(context: Context) : Timber.Tree() {

    private val appContext = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        scope.launch {
            try {
                AppDatabase.get(appContext).logs().insert(
                    LogEntry(
                        tsEpochMs = System.currentTimeMillis(),
                        level = priority,
                        tag = tag,
                        message = message,
                        stack = t?.stackTraceToString(),
                    )
                )
            } catch (e: Throwable) {
                android.util.Log.e("RoomLogTree", "insert failed", e)
            }
        }
    }
}
