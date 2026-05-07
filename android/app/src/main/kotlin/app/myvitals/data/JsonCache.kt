package app.myvitals.data

import android.content.Context
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import java.lang.reflect.Type

/**
 * Tiny SharedPreferences-backed JSON cache. Stores `value` + write
 * timestamp per key so screens can render last-known data immediately
 * (stale-while-revalidate) and decide whether to skip a refresh.
 *
 * Type-safe via [Moshi] adapters; callers pass a Type for collections
 * (use `Types.newParameterizedType(List::class.java, Foo::class.java)`).
 */
object JsonCache {
    private const val PREFS = "myvitals_cache_v1"
    private val moshi: Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    data class Entry<T>(val value: T, val savedAt: Long)

    fun <T> read(context: Context, key: String, type: Type): Entry<T>? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val raw = prefs.getString(key, null) ?: return null
        val savedAt = prefs.getLong("${key}__t", 0L)
        return runCatching {
            val adapter = moshi.adapter<T>(type)
            val v = adapter.fromJson(raw) ?: return@runCatching null
            Entry(v, savedAt)
        }.getOrNull()?.let { Entry(it.value, savedAt) }
    }

    fun <T : Any> write(context: Context, key: String, type: Type, value: T) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val adapter = moshi.adapter<T>(type)
        val json = adapter.toJson(value)
        prefs.edit()
            .putString(key, json)
            .putLong("${key}__t", System.currentTimeMillis())
            .apply()
    }

    fun invalidate(context: Context, key: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .remove(key).remove("${key}__t").apply()
    }

    fun ageMs(context: Context, key: String): Long? {
        val savedAt = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getLong("${key}__t", 0L)
        if (savedAt == 0L) return null
        return System.currentTimeMillis() - savedAt
    }

    fun listType(elementClass: Class<*>): Type =
        Types.newParameterizedType(List::class.java, elementClass)
}
