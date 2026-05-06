package app.myvitals.sync

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class HeartRateSample(
    val time: String,
    val bpm: Double,
    val source: String = "watch",
)

@JsonClass(generateAdapter = true)
data class HrvSample(
    val time: String,
    @Json(name = "rmssd_ms") val rmssdMs: Double,
)

@JsonClass(generateAdapter = true)
data class StepsSample(
    val time: String,
    val count: Int,
)

@JsonClass(generateAdapter = true)
data class SleepStageSample(
    val time: String,
    val stage: String,
    @Json(name = "duration_s") val durationS: Int,
)

@JsonClass(generateAdapter = true)
data class WorkoutSample(
    val time: String,
    val type: String,
    @Json(name = "duration_s") val durationS: Int,
    val kcal: Double? = null,
    @Json(name = "avg_hr") val avgHr: Double? = null,
    @Json(name = "max_hr") val maxHr: Double? = null,
    val source: String? = null,
    val title: String? = null,
)

@JsonClass(generateAdapter = true)
data class BodyMetricSample(
    val time: String,
    @Json(name = "weight_kg") val weightKg: Double? = null,
    @Json(name = "body_fat_pct") val bodyFatPct: Double? = null,
    val bmi: Double? = null,
    @Json(name = "lean_mass_kg") val leanMassKg: Double? = null,
    val source: String = "watch",
)

@JsonClass(generateAdapter = true)
data class BloodPressureSample(
    val time: String,
    val systolic: Int,
    val diastolic: Int,
    @Json(name = "pulse_bpm") val pulseBpm: Int? = null,
    val source: String = "watch",
    val notes: String? = null,
)

@JsonClass(generateAdapter = true)
data class SkinTempSample(
    val time: String,
    @Json(name = "celsius_delta") val celsiusDelta: Double,
)

@JsonClass(generateAdapter = true)
data class SleepSessionSample(
    val start: String,
    val end: String,
    val source: String = "watch",
    val title: String? = null,
)

// ── Sober tracking ────────────────────────────────────────────
@JsonClass(generateAdapter = true)
data class SoberStreak(
    val id: Int,
    val addiction: String,
    @Json(name = "start_at") val startAt: String,
    @Json(name = "end_at") val endAt: String?,
    val notes: String?,
    val days: Double,
)

@JsonClass(generateAdapter = true)
data class SoberCurrentResponse(
    val active: SoberStreak?,
    val addiction: String,
    val now: String? = null,
    @Json(name = "elapsed_seconds") val elapsedSeconds: Long? = null,
    val days: Int? = null,
    val hours: Int? = null,
    val minutes: Int? = null,
)

@JsonClass(generateAdapter = true)
data class SoberResetRequest(
    val addiction: String = "alcohol",
    val notes: String? = null,
    val at: String? = null,
)

@JsonClass(generateAdapter = true)
data class SoberResetResponse(
    val ok: Boolean,
    @Json(name = "current_id") val currentId: Int,
    @Json(name = "started_at") val startedAt: String? = null,
    val noop: Boolean? = null,
)

@JsonClass(generateAdapter = true)
data class HeartbeatPayload(
    @Json(name = "attempt_at") val attemptAt: String,
    val success: Boolean,
    @Json(name = "permissions_lost") val permissionsLost: Boolean = false,
    @Json(name = "perms_granted") val permsGranted: Int? = null,
    @Json(name = "perms_required") val permsRequired: Int? = null,
    @Json(name = "perms_missing") val permsMissing: List<String>? = null,
    @Json(name = "last_success_at") val lastSuccessAt: String? = null,
    @Json(name = "error_summary") val errorSummary: String? = null,
    @Json(name = "records_pulled") val recordsPulled: Int? = null,
    @Json(name = "app_version") val appVersion: String? = null,
)

@JsonClass(generateAdapter = true)
data class IngestBatch(
    val heartrate: List<HeartRateSample> = emptyList(),
    val hrv: List<HrvSample> = emptyList(),
    val steps: List<StepsSample> = emptyList(),
    @Json(name = "sleep_stages") val sleepStages: List<SleepStageSample> = emptyList(),
    val workouts: List<WorkoutSample> = emptyList(),
    @Json(name = "body_metrics") val bodyMetrics: List<BodyMetricSample> = emptyList(),
    @Json(name = "blood_pressure") val bloodPressure: List<BloodPressureSample> = emptyList(),
    @Json(name = "skin_temp") val skinTemp: List<SkinTempSample> = emptyList(),
    @Json(name = "sleep_sessions") val sleepSessions: List<SleepSessionSample> = emptyList(),
) {
    fun isEmpty(): Boolean = heartrate.isEmpty() && hrv.isEmpty() && steps.isEmpty()
        && sleepStages.isEmpty() && workouts.isEmpty() && bodyMetrics.isEmpty()
        && bloodPressure.isEmpty() && skinTemp.isEmpty() && sleepSessions.isEmpty()
}

@JsonClass(generateAdapter = true)
data class IngestResponse(
    val heartrate: Int = 0,
    val hrv: Int = 0,
    val steps: Int = 0,
    @Json(name = "sleep_stages") val sleepStages: Int = 0,
    val workouts: Int = 0,
    @Json(name = "body_metrics") val bodyMetrics: Int = 0,
    @Json(name = "blood_pressure") val bloodPressure: Int = 0,
    @Json(name = "skin_temp") val skinTemp: Int = 0,
    @Json(name = "sleep_sessions") val sleepSessions: Int = 0,
)
