package app.myvitals.strength

import android.content.Context
import app.myvitals.data.AppDatabase
import app.myvitals.data.BufferedStrengthSet
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.LogSetRequest
import app.myvitals.sync.RegenerateRequest
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthRecoveryResponse
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.sync.WorkoutPatchRequest
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * Single entry-point for all strength API + offline-buffer concerns.
 *
 * - GET endpoints that fail fall back to an in-memory cache (today's
 *   plan + the catalog get a JSON copy in encrypted prefs so the user
 *   can open the app on the train and still see today's workout).
 * - POST /sets, when the network throws, lands in
 *   `buffered_strength_sets` and is replayed on the next successful
 *   tick (called from SyncWorker or the user pulling-to-refresh).
 */
class StrengthRepository(
    private val context: Context,
    private val settings: SettingsRepository,
) {

    private val moshi: Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val logSetAdapter: JsonAdapter<LogSetRequest> =
        moshi.adapter(LogSetRequest::class.java)

    private fun api() = BackendClient.create(settings.backendUrl, settings.bearerToken)

    private val planCache = StrengthPlanCache(context, moshi)

    suspend fun today(): StrengthWorkoutDetail? = withContext(Dispatchers.IO) {
        try {
            val resp = api().strengthToday()
            if (resp.isSuccessful) {
                val body = resp.body()
                if (body != null) planCache.savePlan(body)
                else planCache.savePlan(null) // 200 with null = rest day
                body
            } else {
                planCache.loadPlan()
            }
        } catch (e: Exception) {
            Timber.w(e, "strengthToday network error — falling back to cache")
            planCache.loadPlan()
        }
    }

    suspend fun regenerate(force: Boolean): StrengthWorkoutDetail =
        withContext(Dispatchers.IO) {
            val plan = api().regenerateStrengthToday(RegenerateRequest(force))
            planCache.savePlan(plan)
            plan
        }

    suspend fun recovery(): StrengthRecoveryResponse? = withContext(Dispatchers.IO) {
        try { api().strengthRecovery() } catch (e: Exception) {
            Timber.w(e, "strengthRecovery failed"); null
        }
    }

    suspend fun history(): List<StrengthWorkoutSummary> = withContext(Dispatchers.IO) {
        try { api().strengthWorkouts().workouts } catch (e: Exception) {
            Timber.w(e, "strengthWorkouts failed"); emptyList()
        }
    }

    suspend fun workoutDetail(id: Long): StrengthWorkoutDetail =
        withContext(Dispatchers.IO) { api().strengthWorkout(id) }

    suspend fun catalog(): Map<String, StrengthExerciseInfo> =
        withContext(Dispatchers.IO) {
            try {
                val r = api().strengthExercises()
                planCache.saveCatalog(r.exercises)
                r.exercises.associateBy { it.id }
            } catch (e: Exception) {
                Timber.w(e, "strengthExercises failed — falling back to cache")
                planCache.loadCatalog().associateBy { it.id }
            }
        }

    suspend fun completeWorkout(workoutId: Long): StrengthWorkoutDetail =
        withContext(Dispatchers.IO) {
            api().patchStrengthWorkout(workoutId, WorkoutPatchRequest(
                status = "completed",
                completedAt = java.time.Instant.now().toString(),
            ))
        }

    suspend fun aiReview(workoutId: Long): app.myvitals.sync.StrengthReviewResponse =
        withContext(Dispatchers.IO) { api().strengthReview(workoutId) }

    /**
     * Logs a set immediately if the network is up; otherwise queues it
     * to `buffered_strength_sets` (best-effort flush by SyncWorker).
     * Returns true if it landed on the backend, false if buffered.
     */
    suspend fun logSet(req: LogSetRequest): Boolean = withContext(Dispatchers.IO) {
        try {
            api().logStrengthSet(req)
            true
        } catch (e: Exception) {
            Timber.w(e, "logSet network error — buffering")
            val json = logSetAdapter.toJson(req)
            AppDatabase.get(context).bufferedStrengthSets().insert(
                BufferedStrengthSet(
                    jsonBody = json,
                    createdAtEpochS = System.currentTimeMillis() / 1000,
                )
            )
            false
        }
    }

    /** Try to push every queued set log. Returns count flushed. */
    suspend fun flushBufferedSets(): Int = withContext(Dispatchers.IO) {
        val dao = AppDatabase.get(context).bufferedStrengthSets()
        var flushed = 0
        val rows = dao.oldest()
        for (row in rows) {
            try {
                val req = logSetAdapter.fromJson(row.jsonBody) ?: continue
                api().logStrengthSet(req)
                dao.delete(row.id)
                flushed++
            } catch (e: Exception) {
                Timber.w(e, "flushBufferedSets failed at id=${row.id}")
                dao.bumpAttempts(row.id)
                break  // bail to avoid hammering on a persistent error
            }
        }
        flushed
    }

    suspend fun bufferedCount(): Int = withContext(Dispatchers.IO) {
        AppDatabase.get(context).bufferedStrengthSets().count()
    }
}
