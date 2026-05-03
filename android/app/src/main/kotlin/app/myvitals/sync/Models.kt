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
)

@JsonClass(generateAdapter = true)
data class IngestBatch(
    val heartrate: List<HeartRateSample> = emptyList(),
    val hrv: List<HrvSample> = emptyList(),
    val steps: List<StepsSample> = emptyList(),
    @Json(name = "sleep_stages") val sleepStages: List<SleepStageSample> = emptyList(),
    val workouts: List<WorkoutSample> = emptyList(),
) {
    fun isEmpty(): Boolean = heartrate.isEmpty() && hrv.isEmpty() && steps.isEmpty()
        && sleepStages.isEmpty() && workouts.isEmpty()
}

@JsonClass(generateAdapter = true)
data class IngestResponse(
    val heartrate: Int = 0,
    val hrv: Int = 0,
    val steps: Int = 0,
    @Json(name = "sleep_stages") val sleepStages: Int = 0,
    val workouts: Int = 0,
)
