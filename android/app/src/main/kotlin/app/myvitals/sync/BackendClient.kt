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
import retrofit2.http.PATCH
import retrofit2.http.POST
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
    @POST("ai/coach/cardio")
    suspend fun coachCardio(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/cardio/latest")
    suspend fun coachCardioLatest(): Response<CoachCard>

    @POST("ai/coach/workout")
    suspend fun coachWorkout(@Body body: Map<String, Any> = emptyMap()): CoachCard

    @GET("ai/coach/workout/latest")
    suspend fun coachWorkoutLatest(): Response<CoachCard>

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
    suspend fun strengthWorkouts(): StrengthWorkoutsResponse

    @GET("workout/strength/workouts/{id}")
    suspend fun strengthWorkout(@Path("id") id: Long): StrengthWorkoutDetail

    @PATCH("workout/strength/workouts/{id}")
    suspend fun patchStrengthWorkout(
        @Path("id") id: Long, @Body body: WorkoutPatchRequest,
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

    @GET("workout/strength/equipment")
    suspend fun strengthEquipment(): EquipmentResponse

    @retrofit2.http.PUT("workout/strength/equipment")
    suspend fun putStrengthEquipment(@Body body: EquipmentRequest): EquipmentResponse

    @retrofit2.http.PUT("workout/strength/exercises/{id}/pref")
    suspend fun setExercisePref(
        @Path("id") exerciseId: String, @Body body: ExercisePrefBody,
    ): Map<String, String>

    @POST("workout/strength/workout-exercises/{wexId}/swap")
    suspend fun swapStrengthExercise(
        @Path("wexId") wexId: Long, @Body body: SwapBody,
    ): StrengthWorkoutExerciseRow

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

    @GET("activities")
    suspend fun activities(
        @retrofit2.http.Query("type") type: String? = null,
        @retrofit2.http.Query("limit") limit: Int = 50,
        @retrofit2.http.Query("since") since: String? = null,
    ): List<ActivityRow>

    @POST("activities/{source}/{sourceId}/link-trail")
    suspend fun linkActivityTrail(
        @Path("source") source: String,
        @Path("sourceId") sourceId: String,
        @Body body: ActivityLinkTrailBody,
    ): Response<okhttp3.ResponseBody>

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

    @GET("update/check")
    suspend fun updateCheck(): UpdateCheck

    @POST("update/apply")
    suspend fun updateApply(): UpdateApplyResult
}

object BackendClient {
    fun create(baseUrl: String, bearerToken: String): BackendApi {
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

        val auth = Interceptor { chain ->
            val req = chain.request().newBuilder()
                .header("Authorization", "Bearer $bearerToken")
                .build()
            chain.proceed(req)
        }

        // 30-day backfills can move ~10 MB of JSON over slow phone wifi.
        // Default OkHttp writeTimeout is 10 s — far too short. Bump everything.
        val http = OkHttpClient.Builder()
            .addInterceptor(auth)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS)
            .callTimeout(180, TimeUnit.SECONDS)
            .build()

        return Retrofit.Builder()
            .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
            .client(http)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(BackendApi::class.java)
    }
}
