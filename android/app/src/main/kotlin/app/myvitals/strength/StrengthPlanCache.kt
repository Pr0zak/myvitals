package app.myvitals.strength

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthWorkoutDetail
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import timber.log.Timber

/**
 * Tiny offline cache for the strength surface. Backed by encrypted
 * SharedPreferences (same store + key scheme as the bearer token, since
 * the cached plan can include user-specific weights/reps/notes).
 *
 * - Today's plan: re-cached on every successful GET /workout/strength/today
 *   (including a null payload for rest-day responses, so the next opens
 *   show the rest-day card immediately).
 * - Catalog: re-cached on every GET /workout/strength/exercises so
 *   exercise names are resolvable on the active-workout screen even
 *   when offline. ~250 KB JSON; fine.
 */
class StrengthPlanCache(context: Context, moshi: Moshi) {

    private val prefs = run {
        val key = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context, FILE, key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private val planAdapter = moshi.adapter(StrengthWorkoutDetail::class.java)
    private val catalogAdapter = moshi.adapter<List<StrengthExerciseInfo>>(
        Types.newParameterizedType(List::class.java, StrengthExerciseInfo::class.java)
    )

    fun savePlan(plan: StrengthWorkoutDetail?) {
        val json = if (plan == null) "" else planAdapter.toJson(plan)
        prefs.edit().putString(KEY_PLAN, json)
            .putLong(KEY_PLAN_AT, System.currentTimeMillis()).apply()
    }

    fun loadPlan(): StrengthWorkoutDetail? {
        val json = prefs.getString(KEY_PLAN, null) ?: return null
        if (json.isEmpty()) return null  // rest-day cached
        return try { planAdapter.fromJson(json) } catch (e: Exception) {
            Timber.w(e, "plan cache parse failed"); null
        }
    }

    fun saveCatalog(exs: List<StrengthExerciseInfo>) {
        prefs.edit().putString(KEY_CAT, catalogAdapter.toJson(exs)).apply()
    }

    fun loadCatalog(): List<StrengthExerciseInfo> {
        val json = prefs.getString(KEY_CAT, null) ?: return emptyList()
        return try { catalogAdapter.fromJson(json) ?: emptyList() } catch (e: Exception) {
            Timber.w(e, "catalog cache parse failed"); emptyList()
        }
    }

    companion object {
        private const val FILE = "myvitals_strength_cache"
        private const val KEY_PLAN = "today_plan_json"
        private const val KEY_PLAN_AT = "today_plan_cached_at_ms"
        private const val KEY_CAT = "catalog_json"
    }
}
