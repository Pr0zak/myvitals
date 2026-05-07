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
import java.util.concurrent.TimeUnit

interface BackendApi {
    @POST("ingest/batch")
    suspend fun ingestBatch(@Body batch: IngestBatch): IngestResponse

    @POST("ingest/heartbeat")
    suspend fun heartbeat(@Body hb: HeartbeatPayload): Map<String, String>

    @GET("sober/current")
    suspend fun soberCurrent(): SoberCurrentResponse

    @POST("sober/reset")
    suspend fun soberReset(@Body body: SoberResetRequest): SoberResetResponse

    // ── Strength training ─────────────────────────────────────
    @GET("workout/strength/today")
    suspend fun strengthToday(): Response<StrengthWorkoutDetail>

    @POST("workout/strength/today/regenerate")
    suspend fun regenerateStrengthToday(@Body body: RegenerateRequest): StrengthWorkoutDetail

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
