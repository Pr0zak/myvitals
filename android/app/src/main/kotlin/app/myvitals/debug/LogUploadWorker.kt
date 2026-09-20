package app.myvitals.debug

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.myvitals.data.AppDatabase
import app.myvitals.data.LogEntry
import app.myvitals.data.SettingsRepository
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.http.Body
import retrofit2.http.POST
import timber.log.Timber
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

@JsonClass(generateAdapter = true)
data class LogIn(
    val ts: String,
    val level: String,
    val tag: String?,
    val message: String,
    val stack: String?,
)

@JsonClass(generateAdapter = true)
data class LogBatch(
    val source: String,
    val entries: List<LogIn>,
)

interface DebugApi {
    @POST("debug/logs")
    suspend fun upload(@Body batch: LogBatch): Map<String, Int>
}

class LogUploadWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    private val settings = SettingsRepository(context)
    private val db = AppDatabase.get(context)

    override suspend fun doWork(): Result {
        if (!settings.isConfigured()) return Result.success()

        val pending = db.logs().unsent(limit = 200)
        if (pending.isEmpty()) return Result.success()

        val api = buildApi(settings.backendUrl, settings.bearerToken)
        val batch = LogBatch(
            source = "phone",
            entries = pending.map { it.toApi() },
        )

        return try {
            api.upload(batch)
            val now = System.currentTimeMillis()
            db.logs().markSent(pending.map { it.id }, now)

            // Prune logs older than 14 days. Retention window keeps ~20k rows / ~3.5 MB,
            // which is enough for debugging sync problems without unbounded growth.
            // 14 days = 1,209,600,000 ms.
            val fourteenDaysAgoMs = now - 1_209_600_000L
            db.logs().deleteOlderThan(fourteenDaysAgoMs)

            Timber.d("Uploaded %d log entries", pending.size)
            Result.success()
        } catch (e: Exception) {
            // Don't log via Timber — would create a feedback loop where every
            // failed upload makes more pending logs.
            android.util.Log.w("LogUploadWorker", "upload failed: ${e.message}")
            Result.retry()
        }
    }

    private fun buildApi(baseUrl: String, token: String): DebugApi {
        val moshi = Moshi.Builder().build()
        val auth = Interceptor { chain ->
            chain.proceed(chain.request().newBuilder()
                .header("Authorization", "Bearer $token").build())
        }
        return Retrofit.Builder()
            .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
            .client(OkHttpClient.Builder().addInterceptor(auth).build())
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(DebugApi::class.java)
    }

    companion object {
        const val UNIQUE_NAME = "myvitals_log_upload"
    }
}

private val isoFmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
    .apply { timeZone = TimeZone.getTimeZone("UTC") }

private fun LogEntry.toApi(): LogIn = LogIn(
    ts = isoFmt.format(Date(tsEpochMs)),
    level = when (level) {
        android.util.Log.VERBOSE -> "VERBOSE"
        android.util.Log.DEBUG -> "DEBUG"
        android.util.Log.INFO -> "INFO"
        android.util.Log.WARN -> "WARN"
        android.util.Log.ERROR -> "ERROR"
        else -> "INFO"
    },
    tag = tag,
    message = message,
    stack = stack,
)
