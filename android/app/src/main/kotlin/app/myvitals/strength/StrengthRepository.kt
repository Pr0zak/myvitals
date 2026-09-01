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
import app.myvitals.sync.StrengthSetRow
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.sync.UpcomingDay
import app.myvitals.sync.WorkoutExercisePatchRequest
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
    private val wexPatchAdapter: JsonAdapter<WorkoutExercisePatchRequest> =
        moshi.adapter(WorkoutExercisePatchRequest::class.java)

    private fun api() = BackendClient.create(settings.backendUrl, settings.bearerToken)

    private val planCache = StrengthPlanCache(context, moshi)

    suspend fun today(): StrengthWorkoutDetail? = withContext(Dispatchers.IO) {
        // Offline → serve cache instantly instead of waiting on a doomed
        // call to time out.
        if (!app.myvitals.sync.NetworkStatus.isOnline(context)) {
            return@withContext planCache.loadPlan()
        }
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

    suspend fun regenerate(
        force: Boolean, forceFullWeight: Boolean = false,
    ): StrengthWorkoutDetail =
        withContext(Dispatchers.IO) {
            val plan = api().regenerateStrengthToday(
                RegenerateRequest(force, forceFullWeight),
            )
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

    /** The generator's own schedule for the days ahead (OG2-A4).
     *
     * The week strip used to decide which days were training days from a
     * copy of the weekday table. There were four copies, and the three on
     * the read side agreed with each other while disagreeing with the
     * generator that actually decides. Asking the server removes the
     * question. Rest days are absent from the response by construction, so
     * membership of this list is the whole test.
     *
     * Failing soft matters here: an unreachable backend must leave the strip
     * showing history without projections, not blank it or crash the screen.
     */
    suspend fun upcoming(): List<UpcomingDay> = withContext(Dispatchers.IO) {
        try { api().upcomingWorkouts().upcoming } catch (e: Exception) {
            Timber.w(e, "upcomingWorkouts failed"); emptyList()
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
        // Offline → buffer immediately + optimistic local update, so the
        // UI reflects the change instantly instead of hanging on a timeout.
        if (!app.myvitals.sync.NetworkStatus.isOnline(context)) {
            return@withContext bufferWorkoutPatch(workoutId, body)
        }
        try {
            val updated = api().patchStrengthWorkout(workoutId, body)
            planCache.savePlan(updated)
            updated
        } catch (e: Exception) {
            Timber.w(e, "patchStrengthWorkout %s buffered: %s", workoutId, body)
            bufferWorkoutPatch(workoutId, body)
        }
    }

    /** Persist a workout patch to the Room replay buffer and apply it
     *  optimistically to the cached plan. Shared by the offline
     *  short-circuit and the network-failure fallback. */
    private suspend fun bufferWorkoutPatch(
        workoutId: Long, body: WorkoutPatchRequest,
    ): StrengthWorkoutDetail {
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
        val cached = planCache.loadPlan()
            ?: throw IllegalStateException("no cached plan to update offline")
        val newStatus = body.status ?: cached.status
        // SKIP-1 — mirror the server's close-remaining sweep locally. Without
        // it an offline Finish leaves every un-logged slot un-skipped until
        // the write replays, which is the exact bug SKIP-1 fixes: a finished
        // session still offering live logging tables. Same rule as
        // _close_remaining_exercises — a slot carrying any real logged rep
        // keeps its partial record and is left alone. A null close_remaining
        // means the key is omitted and the server default (true) applies.
        val closeRemaining = body.closeRemaining != false
        val becameCompleted = newStatus == "completed" && cached.status != "completed"
        val exercises =
            if (becameCompleted && closeRemaining) {
                cached.exercises.map { wex ->
                    if (wex.sets.none { it.actualReps != null }) wex.copy(skipped = true)
                    else wex
                }
            } else cached.exercises
        val mutated = withRecountedProgress(
            cached.copy(
                status = newStatus,
                completedAt = body.completedAt ?: cached.completedAt,
                exercises = exercises,
            ),
        )
        planCache.savePlan(mutated)
        return mutated
    }

    /**
     * Recompute the four progress counters over a locally-mutated plan.
     *
     * This is the deliberate, offline-only exception to "the server publishes
     * the counters and the clients render them verbatim". A buffered write has
     * no server response to read them from, so without this an offline skip
     * collapses the card while the progress pip stays behind. The formulas
     * mirror the backend's `_accounted_sets` / `_exercise_done` exactly, and
     * the next successful fetch overwrites all four with the authoritative
     * numbers.
     */
    private fun withRecountedProgress(
        plan: StrengthWorkoutDetail,
    ): StrengthWorkoutDetail {
        fun accounted(wex: app.myvitals.sync.StrengthWorkoutExerciseRow): Int =
            if (wex.skipped) wex.targetSets
            else minOf(
                wex.sets.count { it.actualReps != null || it.skipped },
                wex.targetSets,
            )
        fun done(wex: app.myvitals.sync.StrengthWorkoutExerciseRow): Boolean =
            wex.skipped || accounted(wex) >= wex.targetSets
        return plan.copy(
            exercisesDone = plan.exercises.count { done(it) },
            exercisesTotal = plan.exercises.size,
            setsDone = plan.exercises.sumOf { accounted(it) },
            setsTotal = plan.exercises.sumOf { it.targetSets },
        )
    }

    /** SKIP-1 — decline one exercise slot, or un-skip it (the Undo path).
     *  The response is the whole workout with its progress counters already
     *  recomputed, so callers replace their workout state with it outright.
     *
     *  Buffered offline like the status patches. A 4xx is deliberately NOT
     *  buffered: the 409 "sets already logged" refusal is a decision the user
     *  has to see, and replaying it later would only fail again. */
    suspend fun skipExercise(wexId: Long, skipped: Boolean): StrengthWorkoutDetail =
        withContext(Dispatchers.IO) {
            if (!app.myvitals.sync.NetworkStatus.isOnline(context)) {
                return@withContext bufferSkipExercise(wexId, skipped)
            }
            try {
                val updated = api().patchStrengthWorkoutExercise(
                    wexId, WorkoutExercisePatchRequest(skipped),
                )
                planCache.savePlan(updated)
                updated
            } catch (e: retrofit2.HttpException) {
                // attempts=0 reduces the predicate to "the server rejects this
                // exact body and always will" — the 409 case, plus a stale id.
                if (shouldDropBuffered(e, 0)) throw IllegalStateException(serverDetail(e), e)
                Timber.w(e, "skipExercise %s buffered (HTTP %s)", wexId, e.code())
                bufferSkipExercise(wexId, skipped)
            } catch (e: Exception) {
                Timber.w(e, "skipExercise %s buffered (skipped=%s)", wexId, skipped)
                bufferSkipExercise(wexId, skipped)
            }
        }

    /** Queue a slot skip for replay and collapse the card locally.
     *
     *  The progress counters are recomputed over the mutated plan (see
     *  [withRecountedProgress]) — leaving them at their last server value made
     *  an offline skip collapse the card while the pip stayed behind, which
     *  reads as a broken screen rather than a queued write. */
    private suspend fun bufferSkipExercise(
        wexId: Long, skipped: Boolean,
    ): StrengthWorkoutDetail {
        AppDatabase.get(context).bufferedWorkoutWrites().insert(
            app.myvitals.data.BufferedWorkoutWrite(
                kind = "skip_exercise",
                path = wexId.toString(),
                jsonBody = wexPatchAdapter.toJson(WorkoutExercisePatchRequest(skipped)),
                createdAtEpochS = System.currentTimeMillis() / 1000,
            ),
        )
        val cached = planCache.loadPlan()
            ?: throw IllegalStateException("no cached plan to update offline")
        val mutated = withRecountedProgress(
            cached.copy(
                exercises = cached.exercises.map {
                    if (it.id == wexId) it.copy(skipped = skipped) else it
                },
            ),
        )
        planCache.savePlan(mutated)
        return mutated
    }

    /** [closeRemaining] null omits the key so the server default (true)
     *  stands — that's the notification-action path, which has no UI in which
     *  to confirm. The interactive screens ask first and pass it explicitly. */
    suspend fun completeWorkout(
        workoutId: Long, closeRemaining: Boolean? = null,
    ): StrengthWorkoutDetail =
        patchWithBuffer(
            workoutId,
            WorkoutPatchRequest(
                status = "completed",
                completedAt = java.time.Instant.now().toString(),
                closeRemaining = closeRemaining,
            ),
        )

    /** Cardio-day completion that also mints a manual Activity row so
     *  the session shows up in the feed, on HR chart markers, and in
     *  the weekly cardio dose. No offline buffering — needs the
     *  backend to scan HR samples and link the activity. The dialog
     *  shows a clear "needs network" error if the call fails. */
    suspend fun completeCardio(
        workoutId: Long,
        label: String,
        durationMinutes: Double,
        startAt: java.time.Instant? = null,
        type: String = "manual_cardio",
        notes: String? = null,
    ): StrengthWorkoutDetail = withContext(Dispatchers.IO) {
        val resp = api().completeCardioWorkout(
            workoutId,
            app.myvitals.sync.CompleteCardioRequest(
                label = label,
                durationMinutes = durationMinutes,
                startAt = startAt?.toString(),
                type = type,
                notes = notes,
            ),
        )
        planCache.savePlan(resp)
        resp
    }

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

    /** WP-14 — pause the active session. Backend stamps paused_at and
     *  (on resume) folds the interval into total_paused_s, so net
     *  duration excludes time away. Buffered offline like other patches. */
    suspend fun pauseWorkout(workoutId: Long): StrengthWorkoutDetail =
        patchWithBuffer(workoutId, WorkoutPatchRequest(status = "paused"))

    suspend fun resumeWorkout(workoutId: Long): StrengthWorkoutDetail =
        patchWithBuffer(workoutId, WorkoutPatchRequest(status = "in_progress"))

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

    /**
     * TD-10 — append an off-plan exercise to an open session.
     *
     * Deliberately NOT buffered offline alongside set logs. The prescription
     * is server compute — last target weight from history, progressed by the
     * trailing rating, rounded against the user's actual dumbbell pairs and
     * micro-loaders — so an optimistic client-guessed weight would both
     * violate the architecture rule and then disagree with the server when
     * the buffered write eventually replayed. Same reasoning as regenerate,
     * custom-workout and swap: these need the network, and say so.
     */
    suspend fun addExercise(
        workoutId: Long, exerciseId: String, targetSets: Int? = null,
    ): app.myvitals.sync.StrengthWorkoutDetail = withContext(Dispatchers.IO) {
        api().addStrengthExercise(
            workoutId, app.myvitals.sync.AddExerciseBody(exerciseId, targetSets),
        )
    }

    /** Remove a slot. Throws on 409 when real sets exist — the caller shows
     *  the server's message, which explains that skipping is the right move. */
    suspend fun deleteExercise(
        wexId: Long,
    ): app.myvitals.sync.StrengthWorkoutDetail = withContext(Dispatchers.IO) {
        api().deleteStrengthWorkoutExercise(wexId)
    }

    /** OG2-A9: delete a logged set. Deliberately NOT buffered.
     *
     *  It is addressed by `set_id`, a server surrogate, and a set logged
     *  offline has no id here — `logSet` returns null on the buffered path,
     *  so the row never comes back. Delete is literally inexpressible for
     *  exactly the sets most likely to need it, which is why CORRECTION is
     *  the offline repair: it is addressed by (workout_exercise_id,
     *  set_number), which this client derives from its own render loop, and
     *  rides the buffer that already exists.
     *
     *  Throwing rather than buffering is the honest failure. A queued delete
     *  would drain from `buffered_workout_writes`, which flushes AFTER
     *  `buffered_strength_sets` at every call site — so a delete could
     *  replay before the insert it was meant to remove, and the set would
     *  come back.
     */
    suspend fun deleteSet(
        setId: Long,
    ): app.myvitals.sync.StrengthWorkoutDetail = withContext(Dispatchers.IO) {
        api().deleteStrengthSet(setId)
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
    /**
     * Logs a set. Returns the server [StrengthSetRow] on a successful online
     * post (carrying PR-1's is_weight_pr / is_e1rm_pr flags), or null when the
     * write was buffered offline/on-error. Null == "queued, no PR info yet" —
     * the same "not immediately confirmed" signal the old Boolean `false` gave.
     */
    suspend fun logSet(req: LogSetRequest): StrengthSetRow? = withContext(Dispatchers.IO) {
        suspend fun buffer() {
            AppDatabase.get(context).bufferedStrengthSets().insert(
                BufferedStrengthSet(
                    jsonBody = logSetAdapter.toJson(req),
                    createdAtEpochS = System.currentTimeMillis() / 1000,
                )
            )
        }
        // Offline → buffer instantly; mid-workout set logging must never
        // block on a timeout (gym wifi is the whole point of buffering).
        if (!app.myvitals.sync.NetworkStatus.isOnline(context)) {
            buffer(); return@withContext null
        }
        try {
            api().logStrengthSet(req)
        } catch (e: Exception) {
            Timber.w(e, "logSet network error — buffering")
            buffer()
            null
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
                if (shouldDropBuffered(e, row.attempts)) {
                    // 4xx (bad body) or too many failed attempts → this row will
                    // never succeed. Drop it and keep going so one poisoned set
                    // can't permanently jam every newer gym-logged set behind it.
                    Timber.w(e, "Dropping poisoned buffered set id=${row.id} (attempts=${row.attempts})")
                    dao.delete(row.id)
                    continue
                }
                Timber.w(e, "flushBufferedSets failed at id=${row.id}")
                dao.bumpAttempts(row.id)
                break  // transient (IO / 5xx) — preserve order, retry next tick
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
                    "skip_exercise" -> {
                        // SKIP-1 — path is the workout_exercise id, not a workout id.
                        val body = wexPatchAdapter.fromJson(row.jsonBody) ?: continue
                        api().patchStrengthWorkoutExercise(row.path.toLong(), body)
                    }
                    else -> {
                        Timber.w("Unknown buffered kind: %s", row.kind)
                    }
                }
                dao.delete(row.id)
                flushed++
            } catch (e: Exception) {
                if (shouldDropBuffered(e, row.attempts)) {
                    Timber.w(e, "Dropping poisoned buffered write id=${row.id} kind=${row.kind} (attempts=${row.attempts})")
                    dao.delete(row.id)
                    continue
                }
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

    companion object {
        /** Drop a buffered write after this many transient failures so a
         *  permanently-failing row can't block the queue forever. A touch more
         *  generous than the ingest buffer's 3 — gym logs are user-entered. */
        private const val MAX_FLUSH_ATTEMPTS = 5

        /**
         * Decide whether a failed buffered replay should be dropped (vs retried).
         * A 4xx (except 408/429) means the server rejects this exact body and
         * always will — drop immediately. Otherwise it's transient (IO / 5xx /
         * timeout): drop only once it has burned through MAX_FLUSH_ATTEMPTS.
         */
        private fun shouldDropBuffered(e: Throwable, attempts: Int): Boolean {
            val code = (e as? retrofit2.HttpException)?.code()
            if (code != null && code in 400..499 && code != 408 && code != 429) return true
            return attempts + 1 >= MAX_FLUSH_ATTEMPTS
        }

        /**
         * FastAPI puts the human-readable reason in `{"detail": "…"}`.
         * HttpException's own message is just "HTTP 409 Conflict", which tells
         * the user nothing about which sets are in the way — so pull the detail
         * out and fall back to the status line only if the body isn't ours.
         */
        private fun serverDetail(e: retrofit2.HttpException): String = try {
            e.response()?.errorBody()?.string()
                ?.let { org.json.JSONObject(it).optString("detail") }
                ?.takeIf { it.isNotBlank() }
                ?: e.message()
        } catch (_: Exception) {
            e.message()
        }
    }
}
