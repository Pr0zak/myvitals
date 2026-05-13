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
    private val patchAdapter: JsonAdapter<WorkoutPatchRequest> =
        moshi.adapter(WorkoutPatchRequest::class.java)

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

    /** Bulk per-exercise stats keyed by exercise_id. Used by the catalog
     *  screen to surface times-performed pills and stat-based sort. Best-
     *  effort: returns empty map on network failure. */
    suspend fun exercisesStatsSummary(): Map<String, app.myvitals.sync.StrengthExerciseStatsSummary> =
        withContext(Dispatchers.IO) {
            try { api().strengthExercisesStatsSummary() }
            catch (e: Exception) {
                Timber.w(e, "exercisesStatsSummary failed")
                emptyMap()
            }
        }

    /** Patch the workout status. On network failure: buffer the request,
     *  mutate the local cache so the UI reflects the new state, and
     *  return the locally-mutated plan. SyncWorker / the foreground
     *  flush replay buffered patches in oldest-first order. */
    private suspend fun patchWithBuffer(
        workoutId: Long, body: WorkoutPatchRequest,
    ): StrengthWorkoutDetail = withContext(Dispatchers.IO) {
        try {
            val updated = api().patchStrengthWorkout(workoutId, body)
            planCache.savePlan(updated)
            updated
        } catch (e: Exception) {
            Timber.w(e, "patchStrengthWorkout %s buffered: %s", workoutId, body)
            AppDatabase.get(context).bufferedWorkoutWrites().insert(
                app.myvitals.data.BufferedWorkoutWrite(
                    kind = "patch_workout",
                    path = workoutId.toString(),
                    jsonBody = patchAdapter.toJson(body),
                    createdAtEpochS = System.currentTimeMillis() / 1000,
                ),
            )
            // Optimistic local update so the screen flips status without
            // waiting for the next online sync.
            val cached = planCache.loadPlan() ?: return@withContext throw e
            val mutated = cached.copy(
                status = body.status ?: cached.status,
                completedAt = body.completedAt ?: cached.completedAt,
            )
            planCache.savePlan(mutated)
            mutated
        }
    }

    suspend fun completeWorkout(workoutId: Long): StrengthWorkoutDetail =
        patchWithBuffer(
            workoutId,
            WorkoutPatchRequest(
                status = "completed",
                completedAt = java.time.Instant.now().toString(),
            ),
        )

    suspend fun aiReview(workoutId: Long): app.myvitals.sync.StrengthReviewResponse =
        withContext(Dispatchers.IO) { api().strengthReview(workoutId) }

    suspend fun deferWorkout(workoutId: Long): StrengthWorkoutDetail =
        patchWithBuffer(workoutId, WorkoutPatchRequest(status = "skipped"))

    /** Discard an ad-hoc workout (e.g. one created via Custom workout
     *  that the user changed their mind about). Marks it `regenerated`
     *  so the next /today query falls through to whatever was previous
     *  (the morning's completed strength session, or nothing). The
     *  workout's logged sets stay in the DB but it's no longer the
     *  "current" plan. */
    suspend fun discardWorkout(workoutId: Long): StrengthWorkoutDetail =
        patchWithBuffer(workoutId, WorkoutPatchRequest(status = "regenerated"))

    suspend fun unskipWorkout(workoutId: Long): StrengthWorkoutDetail =
        patchWithBuffer(workoutId, WorkoutPatchRequest(status = "planned"))

    suspend fun equipment(): app.myvitals.sync.EquipmentResponse =
        withContext(Dispatchers.IO) { api().strengthEquipment() }

    suspend fun putEquipment(payload: app.myvitals.sync.EquipmentPayload):
            app.myvitals.sync.EquipmentResponse = withContext(Dispatchers.IO) {
        api().putStrengthEquipment(app.myvitals.sync.EquipmentRequest(payload = payload))
    }

    suspend fun setPref(exerciseId: String, pref: String) {
        withContext(Dispatchers.IO) {
            try {
                api().setExercisePref(exerciseId, app.myvitals.sync.ExercisePrefBody(pref))
            } catch (e: Exception) {
                Timber.w(e, "setPref network error — buffering")
                AppDatabase.get(context).bufferedWorkoutWrites().insert(
                    app.myvitals.data.BufferedWorkoutWrite(
                        kind = "set_pref",
                        path = exerciseId,
                        jsonBody = "\"$pref\"",
                        createdAtEpochS = System.currentTimeMillis() / 1000,
                    ),
                )
            }
        }
    }

    suspend fun swapExercise(
        wexId: Long, newExerciseId: String,
    ): app.myvitals.sync.StrengthWorkoutExerciseRow = withContext(Dispatchers.IO) {
        api().swapStrengthExercise(wexId, app.myvitals.sync.SwapBody(newExerciseId))
    }

    suspend fun listHistory(): List<app.myvitals.sync.StrengthWorkoutSummary> =
        withContext(Dispatchers.IO) {
            try { api().strengthWorkouts().workouts } catch (e: Exception) {
                Timber.w(e, "listHistory failed"); emptyList()
            }
        }

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

    /** Replay buffered workout-mutation writes (status patches +
     *  exercise-pref toggles). Oldest-first to preserve user intent
     *  when multiple writes happened to the same workout. */
    suspend fun flushBufferedWorkoutWrites(): Int = withContext(Dispatchers.IO) {
        val dao = AppDatabase.get(context).bufferedWorkoutWrites()
        var flushed = 0
        for (row in dao.oldest()) {
            try {
                when (row.kind) {
                    "patch_workout" -> {
                        val body = patchAdapter.fromJson(row.jsonBody) ?: continue
                        api().patchStrengthWorkout(row.path.toLong(), body)
                    }
                    "set_pref" -> {
                        // jsonBody = pref string ("favorite" | "avoid" | "disabled" | "")
                        api().setExercisePref(
                            row.path,
                            app.myvitals.sync.ExercisePrefBody(row.jsonBody.trim('"')),
                        )
                    }
                    else -> {
                        Timber.w("Unknown buffered kind: %s", row.kind)
                    }
                }
                dao.delete(row.id)
                flushed++
            } catch (e: Exception) {
                Timber.w(e, "flushBufferedWorkoutWrites failed at id=${row.id}")
                dao.bumpAttempts(row.id)
                break
            }
        }
        flushed
    }

    /** Combined count: set logs + workout writes (status / pref). */
    suspend fun bufferedCount(): Int = withContext(Dispatchers.IO) {
        AppDatabase.get(context).bufferedStrengthSets().count() +
            AppDatabase.get(context).bufferedWorkoutWrites().count()
    }
}
