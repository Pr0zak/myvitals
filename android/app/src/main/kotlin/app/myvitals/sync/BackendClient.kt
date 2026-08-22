package app.myvitals.sync

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.DELETE
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

interface BackendApi {
    @POST("ingest/batch")
    suspend fun ingestBatch(@Body batch: IngestBatch): IngestResponse

    @POST("ingest/heartbeat")
    suspend fun heartbeat(@Body hb: HeartbeatPayload): Map<String, String>

    @GET("sober/current")
    suspend fun soberCurrent(): SoberCurrentResponse

    @GET("sober/history")
    suspend fun soberHistory(@Query("limit") limit: Int = 100): List<SoberStreak>

    @POST("sober/reset")
    suspend fun soberReset(@Body body: SoberResetRequest): SoberResetResponse

    // ── Fasting ────────────────────────────────────────────────
    // ── Coach (AI) ─────────────────────────────────────────────
    // ASK-1: free-form Q&A, structured and cached like every other card.
    // The phone had no Ask surface at all — it was web-only.
    @POST("ai/ask")
    suspend fun aiAsk(@Body body: Map<String, String>): AiAskResult

    @GET("ai/ask/latest")
    suspend fun aiAskLatest(): Response<AiAskResult>

    @POST("ai/coach/cardio")
    suspend fun coachCardio(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/cardio/latest")
    suspend fun coachCardioLatest(): Response<CoachCard>

    @POST("ai/coach/workout")
    suspend fun coachWorkout(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/workout/latest")
    suspend fun coachWorkoutLatest(): Response<CoachCard>

    @POST("ai/coach/sleep")
    suspend fun coachSleep(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/sleep/latest")
    suspend fun coachSleepLatest(): Response<CoachCard>

    @POST("ai/coach/recovery")
    suspend fun coachRecovery(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/recovery/latest")
    suspend fun coachRecoveryLatest(): Response<CoachCard>

    @POST("ai/coach/fasting")
    suspend fun coachFasting(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/fasting/latest")
    suspend fun coachFastingLatest(): Response<CoachCard>

    @GET("fasting/current")
    suspend fun fastingCurrent(): Response<FastingSession>   // 200 with null body or row

    @POST("fasting/start")
    suspend fun fastingStart(@Body body: FastingStartRequest): FastingSession

    @POST("fasting/end")
    suspend fun fastingEnd(@Body body: FastingEndRequest): FastingSession

    @GET("fasting/history")
    suspend fun fastingHistory(@Query("limit") limit: Int = 20): List<FastingSession>

    @GET("fasting/stats")
    suspend fun fastingStats(@Query("days") days: Int = 90): FastingStats

    @POST("fasting/logs")
    suspend fun fastingLogAdd(@Body body: FastingLogRequest): Response<Unit>

    // ── Strength training ─────────────────────────────────────
    @GET("workout/strength/today")
    suspend fun strengthToday(): Response<StrengthWorkoutDetail>

    @GET("workout/strength/upcoming")
    suspend fun upcomingWorkouts(
        @Query("days") days: Int = 9,
        @Query("per_day_count") perDayCount: Int = 4,
    ): UpcomingResponse

    @GET("workout/strength/by-date/{date}")
    suspend fun strengthWorkoutByDate(
        @Path("date") date: String,
    ): Response<StrengthWorkoutDetail>

    @POST("workout/strength/today/regenerate")
    suspend fun regenerateStrengthToday(@Body body: RegenerateRequest): StrengthWorkoutDetail

    @POST("workout/strength/today/swap-type")
    suspend fun swapStrengthTodayType(
        @Body body: SwapTodayTypeRequest,
    ): StrengthWorkoutDetail

    @GET("workout/strength/recovery")
    suspend fun strengthRecovery(): StrengthRecoveryResponse

    @GET("workout/strength/exercises")
    suspend fun strengthExercises(): StrengthExercisesResponse

    @GET("workout/strength/workouts")
    suspend fun strengthWorkouts(
        /** Server default is 100 (~6 months at 4x/week), which leaves the
         *  YTD comparison's last-year bucket empty and reports a bogus
         *  "↑ 100%". The web twin asks for 400. */
        @Query("limit") limit: Int = 400,
    ): StrengthWorkoutsResponse

    @GET("workout/strength/workouts/{id}")
    suspend fun strengthWorkout(@Path("id") id: Long): StrengthWorkoutDetail

    @PATCH("workout/strength/workouts/{id}")
    suspend fun patchStrengthWorkout(
        @Path("id") id: Long, @Body body: WorkoutPatchRequest,
    ): StrengthWorkoutDetail

    @POST("workout/strength/workouts/{id}/complete-cardio")
    suspend fun completeCardioWorkout(
        @Path("id") id: Long, @Body body: CompleteCardioRequest,
    ): StrengthWorkoutDetail

    @POST("workout/strength/sets")
    suspend fun logStrengthSet(@Body body: LogSetRequest): StrengthSetRow

    @POST("ai/strength/review/{id}")
    suspend fun strengthReview(@Path("id") id: Long): StrengthReviewResponse

    @POST("ai/strength/nudge/{id}")
    suspend fun strengthNudge(@Path("id") id: Long): StrengthNudgeResponse

    @GET("workout/strength/muscle-volume")
    suspend fun strengthMuscleVolume(
        @Query("days") days: Int = 7,
    ): MuscleVolumeResponse

    @POST("ai/strength/focus-cue/{id}")
    suspend fun strengthFocusCue(@Path("id") id: Long): FocusCueResponse

    @POST("ai/strength/deload-check")
    suspend fun strengthDeloadCheck(): DeloadCheckResponse

    @GET("ai/strength/deload-check/latest")
    suspend fun strengthDeloadLatest(): Response<DeloadCheckResponse>

    @GET("workout/strength/exercises/{id}/stats")
    suspend fun strengthExerciseStats(
        @Path("id") exerciseId: String,
    ): StrengthExerciseStats

    @GET("workout/strength/exercises-stats-summary")
    suspend fun strengthExercisesStatsSummary(): Map<String, StrengthExerciseStatsSummary>

    @GET("workout/strength/explain/{id}")
    suspend fun strengthExplain(@Path("id") id: Long): StrengthExplain

    @GET("workout/strength/stats")
    suspend fun strengthStats(
        @retrofit2.http.Query("days") days: Int = 90,
    ): StrengthStats

    @GET("workout/strength/records")
    suspend fun strengthRecords(): StrengthRecordsResponse

    @GET("workout/strength/volume-trend")
    suspend fun strengthVolumeTrend(
        @retrofit2.http.Query("weeks") weeks: Int = 16,
    ): StrengthVolumeTrend

    @GET("workout/strength/equipment")
    suspend fun strengthEquipment(): EquipmentResponse

    @retrofit2.http.PUT("workout/strength/equipment")
    suspend fun putStrengthEquipment(@Body body: EquipmentRequest): EquipmentResponse

    @retrofit2.http.PUT("workout/strength/exercises/{id}/pref")
    suspend fun setExercisePref(
        @Path("id") exerciseId: String, @Body body: ExercisePrefBody,
    ): Map<String, String>

    /** TD-10 — append an off-plan exercise. Responds with the whole
     *  rehydrated workout so the caller picks up the recomputed progress
     *  counters and session summary in one round trip. */
    @POST("workout/strength/workouts/{workoutId}/exercises")
    suspend fun addStrengthExercise(
        @Path("workoutId") workoutId: Long, @Body body: AddExerciseBody,
    ): StrengthWorkoutDetail

    /** Remove a slot. 409 when real sets are logged against it — skipping is
     *  the right move there, so the record of performed work survives. */
    @retrofit2.http.DELETE("workout/strength/workout-exercises/{wexId}")
    suspend fun deleteStrengthWorkoutExercise(
        @Path("wexId") wexId: Long,
    ): StrengthWorkoutDetail

    @POST("workout/strength/workout-exercises/{wexId}/swap")
    suspend fun swapStrengthExercise(
        @Path("wexId") wexId: Long, @Body body: SwapBody,
    ): StrengthWorkoutExerciseRow

    /** SKIP-1 — decline one slot, or un-skip it. 409 when the slot already
     *  carries real logged sets. Responds with the whole workout. */
    @PATCH("workout/strength/workout-exercises/{wexId}")
    suspend fun patchStrengthWorkoutExercise(
        @Path("wexId") wexId: Long, @Body body: WorkoutExercisePatchRequest,
    ): StrengthWorkoutDetail

    // ── Trails ────────────────────────────────────────────────
    @GET("trails")
    suspend fun trails(): TrailsResponse

    @POST("trails/refresh")
    suspend fun refreshTrails(): TrailRefreshResponse

    @POST("trails/{id}/subscribe")
    suspend fun subscribeTrail(@Path("id") id: Long, @Body body: TrailSubscribeBody): Map<String, Any>

    @retrofit2.http.DELETE("trails/{id}/subscribe")
    suspend fun unsubscribeTrail(@Path("id") id: Long): Response<Void>

    @GET("trails/alerts")
    suspend fun trailAlerts(
        @retrofit2.http.Query("unacked_only") unackedOnly: Boolean = false,
    ): List<TrailAlertRow>

    @POST("trails/alerts/mark-notified")
    suspend fun markTrailAlertsNotified(@Body body: MarkNotifiedBody): Map<String, Int>

    // AI anomaly / goal / streak alerts (distinct from trail alerts above).
    // Backend handles lazy anomaly-scan triggering on read.
    @GET("ai/alerts")
    suspend fun aiAlerts(
        @retrofit2.http.Query("unacked_only") unackedOnly: Boolean = true,
        @retrofit2.http.Query("limit") limit: Int = 20,
    ): List<AiAlertRow>

    @POST("ai/alerts/mark-notified")
    suspend fun markAiAlertsNotified(@Body ids: List<Long>): Map<String, Int>

    @retrofit2.http.PUT("trails/{id}/location")
    suspend fun editTrailLocation(
        @Path("id") id: Long, @Body body: TrailLocationBody,
    ): Map<String, Any>

    @POST("trails/link-activities")
    suspend fun linkAllActivitiesToTrails(
        @retrofit2.http.Query("max_km") maxKm: Double = 2.0,
        @retrofit2.http.Query("relink") relink: Boolean = false,
    ): TrailLinkActivitiesResponse

    @GET("trails/{id}/osm-paths")
    suspend fun trailOsmPaths(@Path("id") id: Long): Response<okhttp3.ResponseBody>

    // ── Vitals dashboard ──────────────────────────────────────
    @GET("profile")
    suspend fun profile(): ProfileResponse

    @retrofit2.http.PUT("profile")
    suspend fun putProfile(@Body body: ProfilePutBody): ProfileResponse

    // TILE-1: scoped read/write of the Key-metrics tile order. Separate
    // from putProfile because that endpoint replaces `extra` wholesale, so
    // saving any unrelated profile field through it drops preferences this
    // build does not know about.
    // CONS-1: the phone did not consume this at all, so TrainHubScreen
    // counted "this week" from whatever activities it had loaded.
    @GET("activities/stats")
    suspend fun activitiesStats(@retrofit2.http.Query("days") days: Int = 30): ActivityStatsOut

    // DISP-1: units / time format / theme. The phone had no unit
    // preference at all before this.
    // HEALTH-1: per-stream freshness + per-integration status in one call.
    @GET("query/data-health")
    suspend fun dataHealth(): DataHealth

    @GET("profile/display-prefs")
    suspend fun displayPrefs(): DisplayPrefsOut

    @retrofit2.http.PUT("profile/display-prefs")
    suspend fun putDisplayPrefs(@Body body: Map<String, String>): DisplayPrefsOut

    // DOW-1: per-weekday step-goal overrides.
    @GET("profile/steps-schedule")
    suspend fun stepsSchedule(): StepsSchedule

    @retrofit2.http.PUT("profile/steps-schedule")
    suspend fun putStepsSchedule(@Body body: StepsScheduleIn): StepsSchedule

    @GET("profile/tile-prefs")
    suspend fun tilePrefs(): TilePrefsOut

    @retrofit2.http.PUT("profile/tile-prefs")
    suspend fun putTilePrefs(@Body body: TilePrefsIn): TilePrefsOut

    @GET("summary/today")
    suspend fun summaryToday(): DailySummary

    @GET("query/weight")
    suspend fun weightSeries(
        @retrofit2.http.Query("since") since: String? = null,
    ): okhttp3.ResponseBody

    @GET("query/blood-pressure")
    suspend fun bpSeries(
        @retrofit2.http.Query("since") since: String? = null,
    ): okhttp3.ResponseBody

    @GET("query/circumference")
    suspend fun circumference(
        @retrofit2.http.Query("since") since: String? = null,
    ): CircumferenceResponse

    @POST("query/circumference")
    suspend fun logCircumference(@Body body: CircumferenceIn): Map<String, String>

    @GET("summary/training-load")
    suspend fun trainingLoad(): TrainingLoad

    @GET("summary/range")
    suspend fun summaryRange(
        @retrofit2.http.Query("since") since: String,
        @retrofit2.http.Query("until") until: String? = null,
    ): List<DailySummary>

    @GET("query/sleep/last")
    suspend fun sleepLast(): Response<SleepNight>

    @GET("query/sleep/range")
    suspend fun sleepRange(
        @retrofit2.http.Query("since") since: String,
        @retrofit2.http.Query("until") until: String? = null,
    ): List<SleepNight>

    @GET("query/sleep/raw")
    suspend fun sleepRaw(
        @retrofit2.http.Query("since") since: String,
        @retrofit2.http.Query("until") until: String? = null,
    ): List<SleepRawSegment>

    @GET("query/heartrate")
    suspend fun heartRateSeries(
        @retrofit2.http.Query("since") since: String? = null,
        @retrofit2.http.Query("until") until: String? = null,
        @retrofit2.http.Query("bucket_seconds") bucketSeconds: Int? = null,
    ): TimeSeries

    @GET("query/hrv")
    suspend fun hrvSeries(
        @retrofit2.http.Query("since") since: String? = null,
        @retrofit2.http.Query("until") until: String? = null,
    ): TimeSeries

    @GET("query/steps")
    suspend fun stepsSeries(
        @retrofit2.http.Query("since") since: String? = null,
        @retrofit2.http.Query("until") until: String? = null,
    ): TimeSeries

    @GET("activities/{source}/{sourceId}")
    suspend fun activity(
        @Path("source") source: String,
        @Path("sourceId") sourceId: String,
    ): ActivityRow

    /** TD-2 — time-in-zone for one activity, computed server-side. The phone
     *  showed a bare HR line and no zones at all before this; the web computed
     *  its own and got them wrong. Neither client derives a zone now. */
    @GET("activities/{source}/{sourceId}/zones")
    suspend fun activityZones(
        @Path("source") source: String,
        @Path("sourceId") sourceId: String,
        @retrofit2.http.Query("buckets") buckets: Int = 0,
    ): ActivityZones

    @GET("activities")
    suspend fun activities(
        @retrofit2.http.Query("type") type: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 50,
        @retrofit2.http.Query("since") since: String? = null,
    ): List<ActivityRow>

    /** Every GPS-tracked activity as simplified polylines, for the map
     *  screen. Server-side RDP keeps this ~400 KB instead of the 3.4 MB
     *  the full-fidelity tracks would cost. */
    /** Readiness + the drivers that produced it, banded server-side. */
    @GET("summary/readiness")
    suspend fun readinessDetail(): ReadinessDetail

    /** Per-tile value, 14-day series and verdict. Judgement is server-side. */
    // DAY-1: everything about one calendar day in a single call. Sections
    // are independently best-effort server-side.
    @GET("summary/day")
    suspend fun summaryDay(@retrofit2.http.Query("date") date: String): DaySnapshot

    @GET("summary/tiles")
    suspend fun summaryTiles(): VitalTilesResponse

    /** Narrative cards for today (sleep + naps) with hypnogram segments. */
    @GET("summary/events")
    suspend fun summaryEvents(): NarrativeEventsResponse

    /** Record 👍/👎 on a narrative card; null vote clears it. */
    @POST("summary/events/{eventId}/feedback")
    suspend fun eventFeedback(
        @Path(value = "eventId", encoded = false) eventId: String,
        @Body body: EventFeedbackRequest,
    ): okhttp3.ResponseBody

    /** Pure-statistics trend badges for the Today header. No LLM, no cost. */
    @GET("ai/badges")
    suspend fun aiBadges(): List<TrendBadge>

    @GET("activities/map")
    suspend fun activitiesMap(
        @retrofit2.http.Query("type") type: String? = null,
        @retrofit2.http.Query("since") since: String? = null,
        @retrofit2.http.Query("trail_id") trailId: Long? = null,
        @retrofit2.http.Query("limit") limit: Int = 1000,
    ): ActivityMapResponse

    /** Activities linked to a trail, newest first. */
    @GET("trails/{id}/visits")
    suspend fun trailVisits(
        @Path("id") id: Long,
        @retrofit2.http.Query("days") days: Int = 3650,
    ): TrailVisitsResponse

    @POST("activities/{source}/{sourceId}/link-trail")
    suspend fun linkActivityTrail(
        @Path("source") source: String,
        @Path("sourceId") sourceId: String,
        @Body body: ActivityLinkTrailBody,
    ): Response<okhttp3.ResponseBody>

    @retrofit2.http.PATCH("activities/{source}/{sourceId}")
    suspend fun editActivity(
        @Path("source") source: String,
        @Path("sourceId") sourceId: String,
        @Body body: ActivityEditBody,
    ): ActivityRow

    @POST("trails/fetch-all-osm-paths")
    suspend fun fetchAllTrailOsmPaths(
        @retrofit2.http.Query("radius_m") radiusM: Double = 500.0,
        @retrofit2.http.Query("relink") relink: Boolean = false,
    ): TrailOsmFetchAllResponse

    @GET("device-status/series")
    suspend fun deviceStatusSeries(
        @retrofit2.http.Query("device_id") deviceId: String = "pixel_watch_3",
        @retrofit2.http.Query("since") since: String? = null,
        @retrofit2.http.Query("until") until: String? = null,
    ): DeviceStatusSeriesResponse

    @GET("journal")
    suspend fun journalList(
        @retrofit2.http.Query("since") since: String? = null,
        @retrofit2.http.Query("until") until: String? = null,
        @retrofit2.http.Query("type") type: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 50,
    ): List<Annotation>

    @POST("journal")
    suspend fun journalCreate(@Body body: AnnotationCreate): Annotation

    @retrofit2.http.DELETE("journal/{id}")
    suspend fun journalDelete(@Path("id") id: Int): Response<okhttp3.ResponseBody>

    @GET("ai/goals")
    suspend fun aiGoals(
        @retrofit2.http.Query("active_only") activeOnly: Boolean = true,
    ): List<AiGoal>

    /** SCS-4: trigger cookie-mode Strava sync from the phone. Uses
     *  `require_any` on the backend so the ingest token is accepted. */
    @POST("strava/cookie-sync")
    suspend fun stravaCookieSync(): StravaCookieSyncResponse

    @GET("strava/cookie")
    suspend fun stravaCookieStatus(): StravaCookieStatusResponse

    @GET("update/check")
    suspend fun updateCheck(): UpdateCheck

    @POST("update/apply")
    suspend fun updateApply(): UpdateApplyResult

    // ── Meals (MEAL-1) ────────────────────────────────────────────────
    //
    // Paths are bare, with no leading "/api". Caddy strips that prefix
    // exactly once for the browser; the phone talks to the backend
    // directly, so spelling it here would 404. Same standard form as
    // every other endpoint above.

    @GET("meals/foods/search")
    suspend fun mealsSearchFoods(
        @Query("q") q: String,
        @Query("ingredients_only") ingredientsOnly: Boolean = false,
        @Query("limit") limit: Int = 25,
    ): List<FoodOut>

    @GET("meals/foods/{id}")
    suspend fun mealsGetFood(@Path("id") id: Long): FoodOut

    @POST("meals/foods")
    suspend fun mealsCreateFood(@Body body: FoodIn): FoodOut

    @PATCH("meals/foods/{id}")
    suspend fun mealsUpdateFood(@Path("id") id: Long, @Body body: FoodIn): FoodOut

    @DELETE("meals/foods/{id}")
    suspend fun mealsDeleteFood(@Path("id") id: Long): Response<Unit>

    @GET("meals/recipes")
    suspend fun mealsRecipes(
        @Query("include_archived") includeArchived: Boolean = false,
    ): List<RecipeOut>

    @GET("meals/recipes/{id}")
    suspend fun mealsRecipe(@Path("id") id: Long): RecipeOut

    @POST("meals/recipes")
    suspend fun mealsCreateRecipe(@Body body: RecipeIn): RecipeOut

    @PATCH("meals/recipes/{id}")
    suspend fun mealsUpdateRecipe(@Path("id") id: Long, @Body body: RecipeIn): RecipeOut

    @DELETE("meals/recipes/{id}")
    suspend fun mealsDeleteRecipe(@Path("id") id: Long): Response<Unit>

    @GET("meals/pantry")
    suspend fun mealsPantry(): List<PantryItemOut>

    @POST("meals/pantry")
    suspend fun mealsAddPantry(@Body body: PantryItemIn): PantryItemOut

    @PATCH("meals/pantry/{id}")
    suspend fun mealsUpdatePantry(@Path("id") id: Long, @Body body: PantryItemIn): PantryItemOut

    @DELETE("meals/pantry/{id}")
    suspend fun mealsDeletePantry(@Path("id") id: Long): Response<Unit>

    @GET("meals/stats")
    suspend fun mealsStats(): MealsStats

    @GET("meals/diet-profile")
    suspend fun mealsDietProfile(): DietProfile

    @PUT("meals/diet-profile")
    suspend fun mealsPutDietProfile(@Body body: DietProfileIn): DietProfile

    @GET("meals/nutrition/assess")
    suspend fun mealsAssessFat(@Query("fat_g") fatG: Double): FatAssessment

    @GET("meals/plan")
    suspend fun mealsPlan(
        @Query("start") start: String? = null,
        @Query("days") days: Int = 7,
    ): List<PlanDayOut>

    @POST("meals/plan")
    suspend fun mealsAddPlanEntry(@Body body: PlanEntryIn): PlanEntryOut

    @DELETE("meals/plan/{id}")
    suspend fun mealsDeletePlanEntry(@Path("id") id: Long): Response<Unit>

    @POST("meals/shopping-list")
    suspend fun mealsGenerateShoppingList(@Body body: ShoppingListIn): ShoppingListOut

    @GET("meals/shopping-lists")
    suspend fun mealsShoppingLists(): List<ShoppingListOut>

    @PATCH("meals/shopping-list/{listId}/items/{itemId}")
    suspend fun mealsCheckShoppingItem(
        @Path("listId") listId: Long,
        @Path("itemId") itemId: Long,
        @Query("checked") checked: Boolean,
    ): Map<String, Any>

    @DELETE("meals/shopping-list/{id}")
    suspend fun mealsDeleteShoppingList(@Path("id") id: Long): Response<Unit>

    @POST("ai/meals/suggest")
    suspend fun mealsSuggest(@Body body: Map<String, String> = emptyMap()): MealSuggestEnvelope

    // Reading the last card must never bill. Returns 200 with a null
    // body when nothing has been generated yet, which Retrofit surfaces
    // as a successful Response with body() == null.
    @GET("ai/meals/suggest/latest")
    suspend fun mealsSuggestLatest(): Response<MealSuggestEnvelope>

    @GET("meals/log")
    suspend fun mealsLog(
        @Query("start") start: String? = null,
        @Query("days") days: Int = 7,
    ): List<LogDayOut>

    @POST("meals/log")
    suspend fun mealsAddLogEntry(@Body body: LogEntryIn): LogEntryOut

    @DELETE("meals/log/{id}")
    suspend fun mealsDeleteLogEntry(@Path("id") id: Long): Response<Unit>

    @PATCH("meals/log/day/{day}")
    suspend fun mealsMarkLogDay(
        @Path("day") day: String,
        @Body body: LogDayPatch,
    ): LogDayOut

    @GET("meals/log/stats")
    suspend fun mealsLogStats(@Query("days") days: Int = 30): LogStatsOut
}

object BackendClient {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    // Track backend reachability so the app-level banner can tell the
    // user "can't reach server" vs "device offline". Any response →
    // OK; any IOException (connect refused / timeout / DNS) → UNREACHABLE.
    private val statusTracker = Interceptor { chain ->
        try {
            val resp = chain.proceed(chain.request())
            ServerStatus.markOk()
            resp
        } catch (e: java.io.IOException) {
            ServerStatus.markUnreachable()
            throw e
        }
    }

    // ONE shared client for the whole app → one connection pool + one
    // dispatcher thread pool. Previously create() built a fresh OkHttpClient on
    // every call (every repo method, every screen fetch, every ingest chunk),
    // so connections were never kept alive and the dispatcher's ExecutorService
    // churned. Per-(baseUrl, token) APIs derive from this via newBuilder(),
    // which reuses the pool/dispatcher instead of allocating new ones.
    //
    // Timeouts: fail FAST so a slow/unreachable server falls back to cached
    // data in seconds, not minutes. writeTimeout stays long — a 30-day backfill
    // can push ~10 MB of JSON over slow wifi.
    private val baseHttp: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .addInterceptor(statusTracker)
            .connectTimeout(6, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .build()
    }

    private val apiCache = java.util.concurrent.ConcurrentHashMap<String, BackendApi>()

    fun create(baseUrl: String, bearerToken: String): BackendApi =
        apiCache.getOrPut("$baseUrl|$bearerToken") {
            val auth = Interceptor { chain ->
                chain.proceed(
                    chain.request().newBuilder()
                        .header("Authorization", "Bearer $bearerToken")
                        .build()
                )
            }
            val http = baseHttp.newBuilder().addInterceptor(auth).build()
            Retrofit.Builder()
                .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
                .client(http)
                .addConverterFactory(MoshiConverterFactory.create(moshi))
                .build()
                .create(BackendApi::class.java)
        }
}
