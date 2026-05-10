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
    val source: String = "unknown",
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

// ── Strength training (Phase 5) ─────────────────────────────────

@JsonClass(generateAdapter = true)
data class StrengthExerciseInfo(
    val id: String,
    val name: String,
    @Json(name = "primary_muscle") val primaryMuscle: String,
    @Json(name = "secondary_muscles") val secondaryMuscles: List<String> = emptyList(),
    val equipment: List<String> = emptyList(),
    @Json(name = "is_compound") val isCompound: Boolean = false,
    @Json(name = "movement_pattern") val movementPattern: String,
    val level: String = "intermediate",
    val mechanic: String? = null,
    val instructions: List<String> = emptyList(),
    @Json(name = "image_front") val imageFront: String? = null,
    @Json(name = "image_side") val imageSide: String? = null,
    @Json(name = "youtube_query") val youtubeQuery: String? = null,
    // Mobility-only flags. Bilateral → 2 sets, one per side; UI labels
    // them R / L. is_timed=false means the "reps" target is actual rep
    // count (Thread-the-Needle, Cat-Cow), not seconds-to-hold.
    @Json(name = "is_bilateral") val isBilateral: Boolean = false,
    @Json(name = "is_timed") val isTimed: Boolean = true,
)

@JsonClass(generateAdapter = true)
data class StrengthExercisesResponse(
    val count: Int,
    val exercises: List<StrengthExerciseInfo>,
)

@JsonClass(generateAdapter = true)
data class StrengthSetRow(
    val id: Long,
    @Json(name = "workout_exercise_id") val workoutExerciseId: Long,
    @Json(name = "set_number") val setNumber: Int,
    @Json(name = "target_weight_lb") val targetWeightLb: Double? = null,
    @Json(name = "target_reps") val targetReps: Int,
    @Json(name = "actual_weight_lb") val actualWeightLb: Double? = null,
    @Json(name = "actual_reps") val actualReps: Int? = null,
    val rating: Int? = null,
    @Json(name = "rest_seconds_taken") val restSecondsTaken: Int? = null,
    @Json(name = "logged_at") val loggedAt: String? = null,
    val skipped: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class StrengthWorkoutExerciseRow(
    val id: Long,
    @Json(name = "workout_id") val workoutId: Long,
    @Json(name = "exercise_id") val exerciseId: String,
    @Json(name = "order_index") val orderIndex: Int,
    @Json(name = "superset_id") val supersetId: String? = null,
    @Json(name = "target_sets") val targetSets: Int,
    @Json(name = "target_reps_low") val targetRepsLow: Int,
    @Json(name = "target_reps_high") val targetRepsHigh: Int,
    @Json(name = "target_weight_lb") val targetWeightLb: Double? = null,
    @Json(name = "target_rest_s") val targetRestS: Int = 90,
    val notes: String? = null,
    val sets: List<StrengthSetRow> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class StrengthWorkoutDetail(
    val id: Long,
    val date: String,
    @Json(name = "generated_at") val generatedAt: String,
    @Json(name = "split_focus") val splitFocus: String,
    val status: String,
    val seed: String,
    @Json(name = "recovery_score_used") val recoveryScoreUsed: Double? = null,
    @Json(name = "readiness_score_used") val readinessScoreUsed: Double? = null,
    @Json(name = "sleep_h_used") val sleepHUsed: Double? = null,
    @Json(name = "started_at") val startedAt: String? = null,
    @Json(name = "completed_at") val completedAt: String? = null,
    val notes: String? = null,
    val exercises: List<StrengthWorkoutExerciseRow> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class StrengthExplain(
    @Json(name = "workout_id") val workoutId: Long,
    @Json(name = "split_focus") val splitFocus: String,
    @Json(name = "why_split") val whySplit: String,
    @Json(name = "why_exercises") val whyExercises: String,
    @Json(name = "why_targets") val whyTargets: String,
)

@JsonClass(generateAdapter = true)
data class StrengthDailyVolume(
    val date: String,
    @Json(name = "volume_lb") val volumeLb: Double,
    val sets: Int,
)

@JsonClass(generateAdapter = true)
data class StrengthMuscleVolume(
    val muscle: String,
    @Json(name = "volume_lb") val volumeLb: Double,
)

@JsonClass(generateAdapter = true)
data class StrengthProgressionPoint(
    val date: String,
    @Json(name = "top_weight_lb") val topWeightLb: Double,
)

@JsonClass(generateAdapter = true)
data class StrengthStats(
    val since: String,
    val days: Int,
    @Json(name = "n_workouts") val nWorkouts: Int,
    @Json(name = "n_sets") val nSets: Int,
    @Json(name = "total_volume_lb") val totalVolumeLb: Double,
    @Json(name = "rpe_avg") val rpeAvg: Double? = null,
    val daily: List<StrengthDailyVolume> = emptyList(),
    @Json(name = "per_muscle") val perMuscle: List<StrengthMuscleVolume> = emptyList(),
    val progression: Map<String, List<StrengthProgressionPoint>> = emptyMap(),
    @Json(name = "progression_names") val progressionNames: Map<String, String> = emptyMap(),
)

@JsonClass(generateAdapter = true)
data class StrengthWorkoutSummary(
    val id: Long,
    val date: String,
    @Json(name = "split_focus") val splitFocus: String,
    val status: String,
    @Json(name = "started_at") val startedAt: String? = null,
    @Json(name = "completed_at") val completedAt: String? = null,
    @Json(name = "generated_at") val generatedAt: String,
)

@JsonClass(generateAdapter = true)
data class StrengthWorkoutsResponse(
    val count: Int,
    val workouts: List<StrengthWorkoutSummary>,
)

@JsonClass(generateAdapter = true)
data class RegenerateRequest(val force: Boolean = false)

@JsonClass(generateAdapter = true)
data class SwapTodayTypeRequest(
    val type: String,                                  // "strength" | "yoga" | "cardio"
    val split: String? = null,
    @Json(name = "duration_minutes") val durationMinutes: Int? = null,
    val difficulty: String? = null,                    // "easy" | "normal" | "hard"
    @Json(name = "replace_completed") val replaceCompleted: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class StrengthRecoveryResponse(
    val date: String,
    @Json(name = "recovery_aware") val recoveryAware: Boolean,
    @Json(name = "recovery_score") val recoveryScore: Double? = null,
    @Json(name = "readiness_score") val readinessScore: Double? = null,
    @Json(name = "sleep_h") val sleepH: Double? = null,
    @Json(name = "deload_factor") val deloadFactor: Double = 1.0,
    @Json(name = "rest_day_recommended") val restDayRecommended: Boolean = false,
    @Json(name = "rest_day_reason") val restDayReason: String? = null,
)

@JsonClass(generateAdapter = true)
data class LogSetRequest(
    @Json(name = "workout_exercise_id") val workoutExerciseId: Long,
    @Json(name = "set_number") val setNumber: Int,
    @Json(name = "target_weight_lb") val targetWeightLb: Double? = null,
    @Json(name = "target_reps") val targetReps: Int,
    @Json(name = "actual_weight_lb") val actualWeightLb: Double? = null,
    @Json(name = "actual_reps") val actualReps: Int? = null,
    val rating: Int? = null,
    @Json(name = "rest_seconds_taken") val restSecondsTaken: Int? = null,
    val skipped: Boolean = false,
    @Json(name = "logged_at") val loggedAt: String? = null,
)

@JsonClass(generateAdapter = true)
data class StrengthReviewBody(
    val headline: String,
    val tone: String,
    val highlights: List<String> = emptyList(),
    val concerns: List<String> = emptyList(),
    @Json(name = "next_session_suggestion") val nextSessionSuggestion: String,
)

@JsonClass(generateAdapter = true)
data class StrengthReviewResponse(
    val review: StrengthReviewBody,
    @Json(name = "generated_at") val generatedAt: String,
    val model: String,
    val cached: Boolean,
)

@JsonClass(generateAdapter = true)
data class StrengthExerciseStats(
    @Json(name = "exercise_id") val exerciseId: String,
    @Json(name = "times_performed") val timesPerformed: Int,
    @Json(name = "total_sets") val totalSets: Int,
    @Json(name = "total_reps") val totalReps: Int,
    @Json(name = "total_volume_lb") val totalVolumeLb: Double,
    @Json(name = "last_weight_lb") val lastWeightLb: Double? = null,
    @Json(name = "max_weight_lb") val maxWeightLb: Double? = null,
    @Json(name = "last_performed_date") val lastPerformedDate: String? = null,
    @Json(name = "avg_rating") val avgRating: Double? = null,
)

@JsonClass(generateAdapter = true)
data class StrengthSwapSuggestion(
    @Json(name = "target_exercise_id") val targetExerciseId: String,
    @Json(name = "replacement_exercise_id") val replacementExerciseId: String,
    val reason: String,
)

@JsonClass(generateAdapter = true)
data class StrengthNudgeBody(
    val swaps: List<StrengthSwapSuggestion> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class StrengthNudgeResponse(
    val nudge: StrengthNudgeBody,
    @Json(name = "generated_at") val generatedAt: String,
    val model: String,
    val cached: Boolean,
)

@JsonClass(generateAdapter = true)
data class TrainingPreferences(
    val level: String = "intermediate",                   // beginner | intermediate | advanced
    @Json(name = "days_per_week") val daysPerWeek: Int = 3,
    @Json(name = "split_preference") val splitPreference: String = "auto",
    @Json(name = "workout_minutes") val workoutMinutes: Int = 50,
)

@JsonClass(generateAdapter = true)
data class DumbbellSpec(
    val type: String = "none",                           // fixed_pairs | adjustable | none
    @Json(name = "pairs_lb") val pairsLb: List<Double> = emptyList(),
    @Json(name = "min_lb") val minLb: Double? = null,
    @Json(name = "max_lb") val maxLb: Double? = null,
    @Json(name = "increment_lb") val incrementLb: Double? = null,
)

@JsonClass(generateAdapter = true)
data class BenchSpec(val flat: Boolean = false, val incline: Boolean = false, val decline: Boolean = false)

@JsonClass(generateAdapter = true)
data class EquipmentPayload(
    val dumbbells: DumbbellSpec = DumbbellSpec(),
    @Json(name = "wrist_weights_lb") val wristWeightsLb: List<Double> = emptyList(),
    val bench: BenchSpec = BenchSpec(),
    val barbell: Boolean = false,
    @Json(name = "barbell_plates_lb") val barbellPlatesLb: List<Double> = emptyList(),
    @Json(name = "squat_rack") val squatRack: Boolean = false,
    @Json(name = "pull_up_bar") val pullUpBar: Boolean = false,
    @Json(name = "cable_stack") val cableStack: Boolean = false,
    @Json(name = "cable_increment_lb") val cableIncrementLb: Double? = null,
    @Json(name = "kettlebells_lb") val kettlebellsLb: List<Double> = emptyList(),
    @Json(name = "resistance_bands") val resistanceBands: Boolean = false,
    val bodyweight: Boolean = true,
    @Json(name = "cardio_rower") val cardioRower: Boolean = false,
    @Json(name = "cardio_bike_indoor") val cardioBikeIndoor: Boolean = false,
    @Json(name = "cardio_mtb_outdoor") val cardioMtbOutdoor: Boolean = false,
    @Json(name = "cardio_road_bike") val cardioRoadBike: Boolean = false,
    @Json(name = "cardio_treadmill") val cardioTreadmill: Boolean = false,
    @Json(name = "exercise_prefs") val exercisePrefs: Map<String, String> = emptyMap(),
    val training: TrainingPreferences = TrainingPreferences(),
)

@JsonClass(generateAdapter = true)
data class EquipmentResponse(
    val id: Int,
    val payload: EquipmentPayload,
    val unit: String,
    @Json(name = "updated_at") val updatedAt: String?,
)

@JsonClass(generateAdapter = true)
data class EquipmentRequest(
    val payload: EquipmentPayload,
    val unit: String = "lb",
)

@JsonClass(generateAdapter = true)
data class ExercisePrefBody(val pref: String)         // neutral|disabled|favorite|avoid

@JsonClass(generateAdapter = true)
data class SwapBody(@Json(name = "exercise_id") val exerciseId: String)

// ── Trails (RainoutLine status) ─────────────────────────────────

@JsonClass(generateAdapter = true)
data class Trail(
    val id: Long,
    val extension: Int,
    val name: String,
    val slug: String,
    @Json(name = "last_seen_at") val lastSeenAt: String,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val city: String? = null,
    val state: String? = null,
    val subscribed: Boolean = false,
    @Json(name = "notify_on") val notifyOn: String? = null,
    val status: String? = null,            // open | closed | pending | unknown
    val comment: String? = null,
    @Json(name = "source_ts") val sourceTs: String? = null,
    @Json(name = "fetched_at") val fetchedAt: String? = null,
    @Json(name = "visits_30d") val visits30d: Int = 0,
    @Json(name = "visits_total") val visitsTotal: Int = 0,
    @Json(name = "last_visit_at") val lastVisitAt: String? = null,
)

@JsonClass(generateAdapter = true)
data class TrailLinkActivitiesResponse(
    val scanned: Int = 0, val linked: Int = 0,
    @Json(name = "already_linked_skipped") val alreadyLinkedSkipped: Int = 0,
    @Json(name = "no_match_within_km") val noMatchWithinKm: Int = 0,
    @Json(name = "no_gps") val noGps: Int = 0,
)

@JsonClass(generateAdapter = true)
data class TrailOsmFetchAllResponse(
    val fetched: Int = 0, val skipped: Int = 0, val failed: Int = 0,
    @Json(name = "total_with_pins") val totalWithPins: Int = 0,
)

@JsonClass(generateAdapter = true)
data class TrailsResponse(
    val count: Int,
    val trails: List<Trail> = emptyList(),
    @Json(name = "dnis_url") val dnisUrl: String? = null,
)

@JsonClass(generateAdapter = true)
data class TrailSubscribeBody(@Json(name = "notify_on") val notifyOn: String = "any")

@JsonClass(generateAdapter = true)
data class TrailRefreshResponse(
    val fetched: Int = 0, val snapshots: Int = 0, val alerts: Int = 0,
)

@JsonClass(generateAdapter = true)
data class TrailAlertRow(
    val id: Long,
    @Json(name = "trail_id") val trailId: Long,
    @Json(name = "trail_name") val trailName: String?,
    @Json(name = "from_status") val fromStatus: String?,
    @Json(name = "to_status") val toStatus: String,
    @Json(name = "source_ts") val sourceTs: String?,
    @Json(name = "created_at") val createdAt: String,
    @Json(name = "phone_notified_at") val phoneNotifiedAt: String?,
    @Json(name = "acked_at") val ackedAt: String?,
)

@JsonClass(generateAdapter = true)
data class MarkNotifiedBody(val ids: List<Long>)

@JsonClass(generateAdapter = true)
data class ActivityRow(
    val source: String,
    @Json(name = "source_id") val sourceId: String,
    val type: String,
    val name: String?,
    @Json(name = "start_at") val startAt: String,
    @Json(name = "duration_s") val durationS: Int,
    @Json(name = "distance_m") val distanceM: Double?,
    @Json(name = "elevation_gain_m") val elevationGainM: Double?,
    @Json(name = "avg_hr") val avgHr: Double? = null,
    @Json(name = "max_hr") val maxHr: Double? = null,
    @Json(name = "avg_power_w") val avgPowerW: Double? = null,
    @Json(name = "kcal") val kcal: Double? = null,
    val polyline: String? = null,
    val notes: String? = null,
    val tags: List<String>? = null,
    @Json(name = "trail_id") val trailId: Long? = null,
    @Json(name = "trail_name") val trailName: String? = null,
)

@JsonClass(generateAdapter = true)
data class ActivityLinkTrailBody(
    @Json(name = "trail_id") val trailId: Long?,
)

@JsonClass(generateAdapter = true)
data class DailySummary(
    val date: String,
    @Json(name = "resting_hr") val restingHr: Double? = null,
    @Json(name = "hrv_avg") val hrvAvg: Double? = null,
    @Json(name = "recovery_score") val recoveryScore: Double? = null,
    @Json(name = "sleep_duration_s") val sleepDurationS: Int? = null,
    @Json(name = "sleep_score") val sleepScore: Double? = null,
    @Json(name = "steps_total") val stepsTotal: Int? = null,
    @Json(name = "weight_kg") val weightKg: Double? = null,
    @Json(name = "body_fat_pct") val bodyFatPct: Double? = null,
    @Json(name = "bp_systolic_avg") val bpSystolicAvg: Double? = null,
    @Json(name = "bp_diastolic_avg") val bpDiastolicAvg: Double? = null,
    @Json(name = "readiness_score") val readinessScore: Double? = null,
    @Json(name = "sleep_debt_h") val sleepDebtH: Double? = null,
)

@JsonClass(generateAdapter = true)
data class TimePoint(
    val time: String,
    val value: Double,
)

@JsonClass(generateAdapter = true)
data class ProfileDerived(
    val age: Int? = null,
    @Json(name = "max_hr_estimated") val maxHrEstimated: Int? = null,
    @Json(name = "resting_hr_baseline_auto") val restingHrBaselineAuto: Double? = null,
)

@JsonClass(generateAdapter = true)
data class ProfileExtra(
    @Json(name = "steps_goal") val stepsGoal: Int? = null,
    @Json(name = "sleep_goal_h") val sleepGoalH: Double? = null,
    @Json(name = "vitals_order") val vitalsOrder: List<String>? = null,
    @Json(name = "vitals_hidden") val vitalsHidden: List<String>? = null,
    @Json(name = "workout_reminder_enabled") val workoutReminderEnabled: Boolean? = null,
    @Json(name = "workout_reminder_hour") val workoutReminderHour: Int? = null,
)

@JsonClass(generateAdapter = true)
data class ProfilePutBody(
    @Json(name = "birth_date") val birthDate: String? = null,
    val sex: String? = null,
    @Json(name = "height_cm") val heightCm: Double? = null,
    @Json(name = "weight_goal_kg") val weightGoalKg: Double? = null,
    @Json(name = "resting_hr_baseline") val restingHrBaseline: Double? = null,
    @Json(name = "activity_level") val activityLevel: String? = null,
    val extra: Map<String, Any>? = null,
)

@JsonClass(generateAdapter = true)
data class ProfileResponse(
    @Json(name = "birth_date") val birthDate: String? = null,
    val sex: String? = null,
    @Json(name = "height_cm") val heightCm: Double? = null,
    @Json(name = "weight_goal_kg") val weightGoalKg: Double? = null,
    @Json(name = "resting_hr_baseline") val restingHrBaseline: Double? = null,
    @Json(name = "activity_level") val activityLevel: String? = null,
    val extra: ProfileExtra? = null,
    val derived: ProfileDerived? = null,
) {
    fun stepsGoal(): Int = extra?.stepsGoal ?: 10_000
    fun sleepGoalH(): Double = extra?.sleepGoalH ?: 8.0
    /** Max HR for zone bucketing; fallback assumes age ~30 (Tanaka). */
    fun maxHr(): Int = derived?.maxHrEstimated ?: 187
}

@JsonClass(generateAdapter = true)
data class SleepStageBucket(
    val stage: String,
    @Json(name = "duration_s") val durationS: Int,
)

@JsonClass(generateAdapter = true)
data class SleepNight(
    val date: String,
    val start: String? = null,
    val end: String? = null,
    @Json(name = "total_s") val totalS: Int,
    val stages: List<SleepStageBucket> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class SleepRawSegment(
    val time: String,
    val stage: String,
    @Json(name = "duration_s") val durationS: Int,
)

@JsonClass(generateAdapter = true)
data class TimeSeries(
    val points: List<TimePoint> = emptyList(),
    val avg: Double? = null,
)

@JsonClass(generateAdapter = true)
data class TrailLocationBody(
    val latitude: Double? = null,
    val longitude: Double? = null,
    val city: String? = null,
    val state: String? = null,
)

@JsonClass(generateAdapter = true)
data class WorkoutPatchRequest(
    val status: String? = null,
    @Json(name = "started_at") val startedAt: String? = null,
    @Json(name = "completed_at") val completedAt: String? = null,
    val notes: String? = null,
)
