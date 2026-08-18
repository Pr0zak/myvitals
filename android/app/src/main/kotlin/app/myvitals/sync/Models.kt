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
    val force: String? = null,  // CAT-1: push / pull / static
    val instructions: List<String> = emptyList(),
    @Json(name = "image_front") val imageFront: String? = null,
    @Json(name = "image_side") val imageSide: String? = null,
    @Json(name = "youtube_query") val youtubeQuery: String? = null,
    // Bilateral → 2 sets, one per side; UI labels them R / L.
    // is_timed=true means target reps carry HOLD SECONDS (planks,
    // isometric holds, mobility yoga). Default false — Moshi fills
    // the default when the JSON omits the key, so we want a
    // false-by-default for the long tail of rep-based exercises.
    // Catalog rows opt-in by explicitly setting is_timed:true.
    @Json(name = "is_bilateral") val isBilateral: Boolean = false,
    @Json(name = "is_timed") val isTimed: Boolean = false,
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
    // PR-1: set on the log_set response when this set just beat a record.
    @Json(name = "is_weight_pr") val isWeightPr: Boolean = false,
    @Json(name = "is_e1rm_pr") val isE1rmPr: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class LastSet(
    @Json(name = "set_number") val setNumber: Int,
    @Json(name = "weight_lb") val weightLb: Double? = null,
    val reps: Int? = null,
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
    // Backend flag — when true, targetReps* carry HOLD SECONDS and the
    // logged actualReps should be interpreted as seconds too.
    @Json(name = "is_timed") val isTimed: Boolean = false,
    val notes: String? = null,
    // LOAD-1: "30 lb DB + 2.5 lb wrist" when the weight needs micro-loaders;
    // null for bodyweight / plain-dumbbell weights.
    @Json(name = "load_hint") val loadHint: String? = null,
    // PROG-1: "Greyskull LP · AMRAP last · +5" scheme badge on program lifts;
    // null for normal generator-driven exercises.
    @Json(name = "program_scheme") val programScheme: String? = null,
    // LOG-1: previous session's working sets, for a faint "last: 30×8 · 30×8" line.
    @Json(name = "last_sets") val lastSets: List<LastSet> = emptyList(),
    // SKIP-1: the user explicitly declined this slot — distinct from
    // "sets is empty", which means never touched. Renders collapsed with an
    // Undo affordance instead of a live logging table. False-by-default so a
    // cached plan from before the field existed reads as "not declined".
    val skipped: Boolean = false,
    // TD-10: the user appended this slot themselves; the generator did not
    // prescribe it. False-by-default so a cached plan from before the field
    // existed reads as "planned" rather than claiming the user added it.
    @Json(name = "added_ad_hoc") val addedAdHoc: Boolean = false,
    // TD-6: one row per prescribed set, with the prefill resolved
    // server-side. Render these — do NOT derive starting values here. This
    // screen and StrengthToday.vue used to seed the inputs from different
    // rules for the same workout.
    @Json(name = "planned_sets") val plannedSets: List<PlannedSet> = emptyList(),
    val sets: List<StrengthSetRow> = emptyList(),
)

/**
 * One prescribed set, with the prefill the client should show — TD-6.
 *
 * The cascade behind [prefillWeightLb] / [prefillReps] lives in
 * `_planned_sets` server-side: this session's most recent logged set of the
 * same exercise, then the previous session's same-index set, then the slot
 * prescription — tiered separately for warm-up and working, so a light
 * warm-up can never seed a working target.
 *
 * [prefillRating] is null for an unlogged set, on purpose. This screen used
 * to pre-select "Good" to save a tap, but the rating is the input to next
 * session's weight selection, so a default manufactures progression data
 * from a user who tapped through without thinking.
 */
@JsonClass(generateAdapter = true)
data class PlannedSet(
    @Json(name = "set_number") val setNumber: Int,
    @Json(name = "set_type") val setType: String = "working",
    @Json(name = "target_weight_lb") val targetWeightLb: Double? = null,
    @Json(name = "target_reps") val targetReps: Int = 0,
    @Json(name = "rest_s") val restS: Int = 90,
    /** PROG-1 Greyskull: the last set is as many reps as possible. */
    @Json(name = "is_amrap") val isAmrap: Boolean = false,
    @Json(name = "prefill_weight_lb") val prefillWeightLb: Double? = null,
    @Json(name = "prefill_reps") val prefillReps: Int = 0,
    @Json(name = "prefill_rating") val prefillRating: Int? = null,
)

/** POST /workout/strength/workouts/{id}/exercises — append an off-plan lift.
 *  target_sets omitted means "whatever the planner would prescribe for an
 *  accessory", which is the right default: the point of this feature is
 *  choosing the movement, not re-deriving the prescription. */
@JsonClass(generateAdapter = true)
data class AddExerciseBody(
    @Json(name = "exercise_id") val exerciseId: String,
    @Json(name = "target_sets") val targetSets: Int? = null,
    val position: Int? = null,
)

@JsonClass(generateAdapter = true)
data class StrengthWorkoutDetail(
    val id: Long,
    val date: String,
    @Json(name = "generated_at") val generatedAt: String,
    @Json(name = "split_focus") val splitFocus: String,
    val status: String,
    val seed: String,
    @Json(name = "fasting_context") val fastingContext: FastingContext? = null,
    @Json(name = "recovery_score_used") val recoveryScoreUsed: Double? = null,
    @Json(name = "readiness_score_used") val readinessScoreUsed: Double? = null,
    @Json(name = "sleep_h_used") val sleepHUsed: Double? = null,
    // Automatic recovery deload applied to this plan's weights (1.0 = none).
    // < 1.0 → StrengthTodayScreen shows a "load eased — Use full weight" banner.
    @Json(name = "deload_factor") val deloadFactor: Double = 1.0,
    @Json(name = "deload_reason") val deloadReason: String? = null,
    @Json(name = "started_at") val startedAt: String? = null,
    @Json(name = "completed_at") val completedAt: String? = null,
    @Json(name = "paused_at") val pausedAt: String? = null,
    @Json(name = "total_paused_s") val totalPausedS: Int = 0,
    val notes: String? = null,
    // SKIP-1 progress counters, computed server-side. Both surfaces used to
    // derive these locally with formulas that disagreed (the web pip excluded
    // individually-skipped sets, this one included them), so the same session
    // read differently depending on which screen you opened. Render verbatim —
    // do not re-derive from `exercises`.
    @Json(name = "exercises_done") val exercisesDone: Int = 0,
    @Json(name = "exercises_total") val exercisesTotal: Int = 0,
    @Json(name = "sets_done") val setsDone: Int = 0,
    @Json(name = "sets_total") val setsTotal: Int = 0,
    val exercises: List<StrengthWorkoutExerciseRow> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class FastingContext(
    val active: Boolean,
    @Json(name = "current_hours") val currentHours: Double,
    val stage: String,
    val modulation: String,
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

// BODY-1: body circumference measurements (cm), manual entry.
@JsonClass(generateAdapter = true)
data class CircumferencePoint(
    val time: String,
    @Json(name = "waist_cm") val waistCm: Double? = null,
    @Json(name = "chest_cm") val chestCm: Double? = null,
    @Json(name = "arms_cm") val armsCm: Double? = null,
    @Json(name = "hips_cm") val hipsCm: Double? = null,
    @Json(name = "thighs_cm") val thighsCm: Double? = null,
    @Json(name = "neck_cm") val neckCm: Double? = null,
    @Json(name = "calves_cm") val calvesCm: Double? = null,
)

@JsonClass(generateAdapter = true)
data class CircumferenceResponse(
    val points: List<CircumferencePoint> = emptyList(),
    @Json(name = "latest_per_site") val latestPerSite: Map<String, Double> = emptyMap(),
)

@JsonClass(generateAdapter = true)
data class CircumferenceIn(
    @Json(name = "waist_cm") val waistCm: Double? = null,
    @Json(name = "chest_cm") val chestCm: Double? = null,
    @Json(name = "arms_cm") val armsCm: Double? = null,
    @Json(name = "hips_cm") val hipsCm: Double? = null,
    @Json(name = "thighs_cm") val thighsCm: Double? = null,
    @Json(name = "neck_cm") val neckCm: Double? = null,
    @Json(name = "calves_cm") val calvesCm: Double? = null,
    val time: String? = null,
)

// VOLT-1: weekly mesocycle volume trend.
@JsonClass(generateAdapter = true)
data class StrengthWeeklyPoint(
    @Json(name = "week_start") val weekStart: String,
    @Json(name = "volume_lb") val volumeLb: Double,
    val sets: Int = 0,
    val workouts: Int = 0,
)

@JsonClass(generateAdapter = true)
data class StrengthVolumeTrend(
    val weeks: Int = 16,
    val since: String? = null,
    val trend: List<StrengthWeeklyPoint> = emptyList(),
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
    val e1rm: Double? = null,  // e1RM-1: Epley estimated 1-rep-max for the day
)

@JsonClass(generateAdapter = true)
data class StrengthRecord(
    @Json(name = "exercise_id") val exerciseId: String,
    val name: String,
    @Json(name = "best_weight_lb") val bestWeightLb: Double,
    @Json(name = "best_weight_date") val bestWeightDate: String? = null,
    @Json(name = "best_e1rm") val bestE1rm: Double,
    @Json(name = "best_e1rm_date") val bestE1rmDate: String? = null,
    @Json(name = "last_performed_date") val lastPerformedDate: String? = null,
)

@JsonClass(generateAdapter = true)
data class StrengthRecordsResponse(
    val records: List<StrengthRecord> = emptyList(),
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
    @Json(name = "completed_by_activity_source")
    val completedByActivitySource: String? = null,
    @Json(name = "completed_by_activity_source_id")
    val completedByActivitySourceId: String? = null,
    /** TD-4 — net duration, tonnage and energy cost, computed server-side.
     *  Null until the session is completed. */
    @Json(name = "session_summary") val sessionSummary: SessionSummary? = null,
)

/**
 * What one finished strength session cost — TD-4.
 *
 * Every field is computed on the server. [netDurationS] in particular
 * replaces the gross `completedAt - startedAt` arithmetic both clients used
 * to do, which disagreed with the training-load model about the same
 * workout because that model subtracts the accumulated pause.
 *
 * [kcalMethod] must reach the UI. An estimate rendered as a bare number is
 * indistinguishable from a measurement, and "none" with a null [kcalEst] is
 * a real answer — the profile lacks the body data to estimate honestly —
 * rather than an error to hide.
 */
@JsonClass(generateAdapter = true)
data class SessionSummary(
    @Json(name = "net_duration_s") val netDurationS: Int? = null,
    @Json(name = "working_sets") val workingSets: Int = 0,
    @Json(name = "total_reps") val totalReps: Int = 0,
    @Json(name = "total_volume_lb") val totalVolumeLb: Double = 0.0,
    @Json(name = "avg_hr") val avgHr: Double? = null,
    @Json(name = "max_hr") val maxHr: Double? = null,
    @Json(name = "kcal_est") val kcalEst: Double? = null,
    /** "hr" | "met" | "none" */
    @Json(name = "kcal_method") val kcalMethod: String = "none",
)

@JsonClass(generateAdapter = true)
data class StrengthWorkoutsResponse(
    val count: Int,
    val workouts: List<StrengthWorkoutSummary>,
)

/** One projected workout day from GET /workout/strength/upcoming. */
@JsonClass(generateAdapter = true)
data class UpcomingDay(
    val date: String,
    @Json(name = "is_today") val isToday: Boolean = false,
    @Json(name = "split_focus") val splitFocus: String,
    @Json(name = "preview_exercises") val previewExercises: List<String> = emptyList(),
    @Json(name = "exercise_count") val exerciseCount: Int = 0,
)

@JsonClass(generateAdapter = true)
data class UpcomingResponse(
    val count: Int = 0,
    val upcoming: List<UpcomingDay> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class RegenerateRequest(
    val force: Boolean = false,
    @Json(name = "force_full_weight") val forceFullWeight: Boolean = false,
)

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
    @Json(name = "set_type") val setType: String = "working",
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
    @Json(name = "best_e1rm") val bestE1rm: Double? = null,   // e1RM-1
    @Json(name = "last_e1rm") val lastE1rm: Double? = null,
    @Json(name = "last_performed_date") val lastPerformedDate: String? = null,
    @Json(name = "avg_rating") val avgRating: Double? = null,
)

/** Bulk variant of StrengthExerciseStats — returned by
 *  /exercises-stats-summary as `Map<exerciseId, …>` so the catalog can
 *  paint per-row pills without N round-trips. exerciseId is omitted
 *  (it's the map key). */
@JsonClass(generateAdapter = true)
data class StrengthExerciseStatsSummary(
    @Json(name = "times_performed") val timesPerformed: Int,
    @Json(name = "total_sets") val totalSets: Int,
    @Json(name = "total_reps") val totalReps: Int,
    @Json(name = "total_volume_lb") val totalVolumeLb: Double,
    @Json(name = "max_weight_lb") val maxWeightLb: Double? = null,
    @Json(name = "last_performed_date") val lastPerformedDate: String? = null,
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
data class MuscleVolumeRow(
    val sets: Int = 0,
    val mev: Int = 0,
    val mav: Int = 0,
    val status: String = "untrained",   // untrained | under | in_range | over
)

@JsonClass(generateAdapter = true)
data class MuscleVolumeResponse(
    @Json(name = "window_days") val windowDays: Int = 7,
    val muscles: Map<String, MuscleVolumeRow> = emptyMap(),
)

@JsonClass(generateAdapter = true)
data class FocusCueBody(
    val headline: String = "",
    val tone: String = "neutral",
    val cue: String = "",
)

@JsonClass(generateAdapter = true)
data class FocusCueResponse(
    val cue: FocusCueBody,
    @Json(name = "generated_at") val generatedAt: String,
    val model: String,
    val cached: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class DeloadJudgment(
    @Json(name = "should_deload") val shouldDeload: Boolean = false,
    val severity: String = "none",            // none | light | moderate | rest
    val headline: String = "",
    val evidence: List<String> = emptyList(),
    val recommendation: String = "",
)

@JsonClass(generateAdapter = true)
data class DeloadCheckResponse(
    val judgment: DeloadJudgment,
    @Json(name = "generated_at") val generatedAt: String,
    val model: String,
    val cached: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class TrainingPreferences(
    val level: String = "intermediate",                   // beginner | intermediate | advanced
    @Json(name = "days_per_week") val daysPerWeek: Int = 3,
    @Json(name = "split_preference") val splitPreference: String = "auto",
    @Json(name = "workout_minutes") val workoutMinutes: Int = 50,  // deprecated (WP-17)
    @Json(name = "exercises_per_workout") val exercisesPerWorkout: Int? = null,  // WP-17 — null = auto
    @Json(name = "include_mobility") val includeMobility: Boolean = true,
    @Json(name = "yoga_on_rest_days") val yogaOnRestDays: Boolean = true,
    @Json(name = "cardio_days_per_week") val cardioDaysPerWeek: Int = 2,
    val goal: String = "hypertrophy",                     // strength | hypertrophy | general
    val program: ProgramConfig = ProgramConfig(),         // PROG-1 — opt-in program mode
)

// PROG-1 — program mode. One core lift under a fixed progression scheme.
// amrap_last_set defaults false (Moshi-default landmine avoidance — the
// catalog/greyskull path opts in explicitly).
@JsonClass(generateAdapter = true)
data class ProgramLiftState(
    @Json(name = "exercise_id") val exerciseId: String,
    val scheme: String = "linear",                        // greyskull | linear | double
    @Json(name = "current_weight_lb") val currentWeightLb: Double? = null,
    @Json(name = "increment_lb") val incrementLb: Double = 5.0,
    val sets: Int = 3,
    @Json(name = "reps_low") val repsLow: Int = 5,
    @Json(name = "reps_high") val repsHigh: Int = 5,
    @Json(name = "amrap_last_set") val amrapLastSet: Boolean = false,
    @Json(name = "rest_s") val restS: Int = 180,
    @Json(name = "consecutive_fails") val consecutiveFails: Int = 0,
    @Json(name = "fails_before_deload") val failsBeforeDeload: Int = 3,
    @Json(name = "deload_pct") val deloadPct: Double = 0.10,
    @Json(name = "last_advanced_on") val lastAdvancedOn: String? = null,
)

@JsonClass(generateAdapter = true)
data class ProgramConfig(
    val enabled: Boolean = false,
    val lifts: List<ProgramLiftState> = emptyList(),
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

// ── Coach (AI cards) ───────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class CoachCard(
    val analysis: Map<String, Any?>,
    @Json(name = "generated_at") val generatedAt: String,
    val model: String,
    val cached: Boolean,
)


// ── Fasting ────────────────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class FastingSession(
    val id: Long,
    @Json(name = "started_at") val startedAt: String,
    @Json(name = "ended_at") val endedAt: String?,
    val protocol: String,
    val mode: String,
    @Json(name = "target_hours") val targetHours: Double?,
    @Json(name = "target_eating_window_h") val targetEatingWindowH: Double?,
    val notes: String?,
    @Json(name = "elapsed_h") val elapsedH: Double,
    @Json(name = "current_stage") val currentStage: String,
    @Json(name = "next_stage_at_h") val nextStageAtH: Double?,
    @Json(name = "is_active") val isActive: Boolean,
)

@JsonClass(generateAdapter = true)
data class FastingStartRequest(
    val protocol: String,
    @Json(name = "target_hours") val targetHours: Double? = null,
    @Json(name = "target_eating_window_h") val targetEatingWindowH: Double? = null,
    val notes: String? = null,
)

@JsonClass(generateAdapter = true)
data class FastingEndRequest(
    @Json(name = "session_id") val sessionId: Long? = null,
    @Json(name = "ended_at") val endedAt: String? = null,
    val notes: String? = null,
)

@JsonClass(generateAdapter = true)
data class FastingLogRequest(
    @Json(name = "session_id") val sessionId: Long,
    val hunger: Int? = null,
    val mood: Int? = null,
    @Json(name = "hydration_ml") val hydrationMl: Int? = null,
    val notes: String? = null,
)

@JsonClass(generateAdapter = true)
data class FastingStats(
    @Json(name = "sessions_count") val sessionsCount: Int,
    @Json(name = "completed_count") val completedCount: Int,
    @Json(name = "avg_duration_h") val avgDurationH: Double?,
    @Json(name = "median_duration_h") val medianDurationH: Double?,
    @Json(name = "longest_h") val longestH: Double?,
    @Json(name = "current_streak_days") val currentStreakDays: Int,
    @Json(name = "last_completed_at") val lastCompletedAt: String?,
)


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
    // Spotter/partner available → unlocks partner-resistance exercises
    // (towel triceps extension, manual hamstring). Off by default.
    @Json(name = "training_partner") val trainingPartner: Boolean = false,
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

// ── Readiness detail (/summary/readiness) ─────────────────────────

@JsonClass(generateAdapter = true)
data class ReadinessDriver(
    val key: String,
    val label: String,
    val value: Double? = null,
    val unit: String = "",
    /** z against the 28-day baseline; null for the sleep branches. */
    val z: Double? = null,
    @Json(name = "sub_score") val subScore: Double? = null,
    val weight: Double = 0.0,
    val baseline: Double? = null,
    @Json(name = "higher_is_better") val higherIsBetter: Boolean = true,
)

@JsonClass(generateAdapter = true)
data class ReadinessPoint(val date: String, val score: Double? = null)

@JsonClass(generateAdapter = true)
data class ReadinessDetail(
    val date: String,
    val score: Double? = null,
    /** low | moderate | high; null when there's no score. */
    val band: String? = null,
    /** Why there's no score, when there isn't one. */
    val reason: String? = null,
    val drivers: List<ReadinessDriver> = emptyList(),
    val series: List<ReadinessPoint> = emptyList(),
    val weights: Map<String, Double> = emptyMap(),
)

// ── Vitals tiles (/summary/tiles) ────────────────────────────────
//
// The verdict is the SERVER's — see analytics/tiles.py. Nothing here
// decides what counts as good, so the phone grid and the web grid can't
// disagree about the same reading.

@JsonClass(generateAdapter = true)
data class VitalTilePoint(
    val date: String,
    val value: Double? = null,
)

@JsonClass(generateAdapter = true)
data class VitalTile(
    val key: String,
    val label: String,
    val unit: String = "",
    /** Number for most metrics, "139/92" for blood pressure — hence Any?. */
    val value: Any? = null,
    /** baseline | target | neutral */
    val kind: String = "neutral",
    @Json(name = "higher_is_better") val higherIsBetter: Boolean? = null,
    val baseline: Double? = null,
    /** Explicit "your normal" bounds. The rule lives in analytics/tiles.py;
     *  computing it here too is how two surfaces drift. */
    @Json(name = "band_low") val bandLow: Double? = null,
    @Json(name = "band_high") val bandHigh: Double? = null,
    /** Section heading for the Key metrics grid, assigned server-side. */
    val group: String? = null,
    val target: Double? = null,
    val delta: Double? = null,
    val z: Double? = null,
    /** good | typical | watch, or null when the server withheld a verdict. */
    val status: String? = null,
    @Json(name = "status_reason") val statusReason: String? = null,
    /** Set for intermittently-measured metrics: the reading's own date... */
    @Json(name = "as_of") val asOf: String? = null,
    /** ...and its age, so a stale value is never shown as if it were today's. */
    @Json(name = "stale_days") val staleDays: Int? = null,
    val series: List<VitalTilePoint> = emptyList(),
) {
    /** Moshi parses JSON numbers as Double, so an int-valued metric would
     *  otherwise render as "5.0 steps". */
    fun displayValue(): String {
        val v = value ?: return "—"
        if (v is String) return v
        val d = (v as? Number)?.toDouble() ?: return v.toString()
        return when {
            key == "steps" -> "%,d".format(d.toLong())
            d == d.toLong().toDouble() -> d.toLong().toString()
            else -> "%.1f".format(d)
        }
    }
}

@JsonClass(generateAdapter = true)
data class VitalTilesRollup(
    val judged: Int = 0,
    @Json(name = "in_range") val inRange: Int = 0,
    val total: Int = 0,
)

@JsonClass(generateAdapter = true)
data class FocusCount(
    val tracked: Int = 0,
    val total: Int = 0,
)

@JsonClass(generateAdapter = true)
data class WeekProgress(
    val label: String = "Weekly steps",
    val done: Int = 0,
    val goal: Int = 0,
    val pct: Double = 0.0,
)

@JsonClass(generateAdapter = true)
data class VitalTilesResponse(
    val date: String,
    val tiles: List<VitalTile> = emptyList(),
    /** Health-status roll-up, counted server-side so surfaces agree. */
    val summary: VitalTilesRollup? = null,
    /** Section headings in display order. */
    /** Weekly steps progress for the hero ring, summed server-side. */
    val week: WeekProgress? = null,
    @Json(name = "group_order") val groupOrder: List<String> = emptyList(),
    /** Per-focus-area "N tracked" counts. */
    @Json(name = "focus_areas") val focusAreas: Map<String, FocusCount> = emptyMap(),
)

// ── Narrative event cards (/summary/events) ──────────────────────
//
// Wording and nap-vs-night classification are the SERVER's — see
// analytics/events.py — so both clients say the same sentence.

@JsonClass(generateAdapter = true)
data class NarrativeSegment(
    val start: String,
    val stage: String,
    @Json(name = "duration_s") val durationS: Int = 0,
)

@JsonClass(generateAdapter = true)
data class NarrativeStageTotal(
    val stage: String,
    @Json(name = "duration_s") val durationS: Int = 0,
)

@JsonClass(generateAdapter = true)
data class NarrativeStat(
    val label: String,
    val value: String,
    val chip: String,
    /** good | typical | watch */
    val tone: String = "typical",
)

@JsonClass(generateAdapter = true)
data class NarrativeEvent(
    val id: String,
    /** "up" | "down", or null when the user hasn't voted. */
    val feedback: String? = null,
    /** nap | sleep */
    val kind: String,
    val headline: String,
    val detail: String,
    val start: String,
    val end: String,
    @Json(name = "duration_s") val durationS: Int = 0,
    val title: String? = null,
    /** Nested stat cards (sleep score / duration). Empty for a nap — it is
     *  not scored and has no goal, and a zero would read as a bad night. */
    val stats: List<NarrativeStat> = emptyList(),
    val stages: List<NarrativeStageTotal> = emptyList(),
    val segments: List<NarrativeSegment> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class EventFeedbackRequest(
    /** null clears a previous vote. */
    val vote: String? = null,
)

@JsonClass(generateAdapter = true)
data class NarrativeEventsResponse(
    val date: String,
    val events: List<NarrativeEvent> = emptyList(),
)

// ── Trend badges (/ai/badges — pure statistics, no LLM) ───────────

@JsonClass(generateAdapter = true)
data class TrendBadge(
    val key: String,
    val label: String,
    val value: String,
    val subtitle: String = "",
    /** good | warn | bad | neutral */
    val tone: String = "neutral",
    /** up | down | flat | spike | streak */
    val direction: String = "flat",
)

// ── All-activities map ────────────────────────────────────────────

@JsonClass(generateAdapter = true)
data class MapTrack(
    val source: String,
    @Json(name = "source_id") val sourceId: String,
    val type: String,
    val name: String? = null,
    @Json(name = "start_at") val startAt: String,
    @Json(name = "duration_s") val durationS: Int = 0,
    @Json(name = "distance_m") val distanceM: Double? = null,
    @Json(name = "trail_id") val trailId: Long? = null,
    @Json(name = "trail_name") val trailName: String? = null,
    /** RDP-simplified — not the full-fidelity track. */
    val polyline: String,
)

@JsonClass(generateAdapter = true)
data class ActivityMapResponse(
    val tracks: List<MapTrack> = emptyList(),
    /** [south, west, north, east] over every track — the "fit all" extent. */
    val bounds: List<Double>? = null,
    /** Bounds of the cluster the user actually trains in. Open on this;
     *  fitting [bounds] lets one holiday ride shrink home to a dot. */
    @Json(name = "primary_bounds") val primaryBounds: List<Double>? = null,
    val returned: Int = 0,
)

// ── HR zones (TD-2) ───────────────────────────────────────────────
//
// Boundaries, seconds and percentages all arrive already computed. The phone
// renders them and does not reconstruct a zone from a bpm reading, because
// the moment two surfaces each own a percentage table they drift — which is
// exactly what happened on the web before this endpoint existed.

@JsonClass(generateAdapter = true)
data class HrZone(
    val zone: String,
    val label: String,
    @Json(name = "lo_bpm") val loBpm: Int,
    /** Null on the open-ended top zone. */
    @Json(name = "hi_bpm") val hiBpm: Int? = null,
    val seconds: Int = 0,
    val pct: Double = 0.0,
)

@JsonClass(generateAdapter = true)
data class ActivityZones(
    @Json(name = "max_hr") val maxHr: Int = 0,
    /** "profile" | "estimated" | "default" — a chart built on a guessed
     *  maximum should say so rather than presenting itself as measured. */
    @Json(name = "max_hr_source") val maxHrSource: String = "default",
    @Json(name = "age_used") val ageUsed: Int? = null,
    /** False when no HR series survived and the whole session was attributed
     *  to one zone from its average. Defaults false so absence reads as
     *  "coarse" rather than silently claiming sampled detail. */
    val sampled: Boolean = false,
    @Json(name = "total_seconds") val totalSeconds: Int = 0,
    val zones: List<HrZone> = emptyList(),
)

// ── Trail → linked activities ─────────────────────────────────────

@JsonClass(generateAdapter = true)
data class TrailVisit(
    val source: String,
    @Json(name = "source_id") val sourceId: String,
    val type: String,
    val name: String? = null,
    @Json(name = "start_at") val startAt: String,
    @Json(name = "duration_s") val durationS: Int = 0,
    @Json(name = "distance_m") val distanceM: Double? = null,
    @Json(name = "avg_hr") val avgHr: Double? = null,
    val kcal: Double? = null,
)

@JsonClass(generateAdapter = true)
data class TrailVisitsResponse(
    @Json(name = "trail_id") val trailId: Long = 0,
    val name: String? = null,
    val count: Int = 0,
    val visits: List<TrailVisit> = emptyList(),
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
data class AiAlertRow(
    val id: Long,
    @Json(name = "created_at") val createdAt: String,
    val kind: String,
    val severity: String,
    val title: String,
    val body: String,
    val metric: String?,
    @Json(name = "z_score") val zScore: Double?,
    @Json(name = "acked_at") val ackedAt: String?,
    @Json(name = "phone_notified_at") val phoneNotifiedAt: String?,
)

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

/** PATCH /activities/{source}/{sourceId}. Only set fields are applied;
 *  backend re-scans HR samples when start_at or duration changes. */
@JsonClass(generateAdapter = true)
data class ActivityEditBody(
    val name: String? = null,
    val type: String? = null,
    @Json(name = "duration_minutes") val durationMinutes: Double? = null,
    @Json(name = "start_at") val startAt: String? = null,
    val notes: String? = null,
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
    @Json(name = "skin_temp_delta_avg") val skinTempDeltaAvg: Double? = null,
    @Json(name = "readiness_score") val readinessScore: Double? = null,
    @Json(name = "sleep_debt_h") val sleepDebtH: Double? = null,
    @Json(name = "fasting_hours") val fastingHours: Double? = null,
    // Newest HeartRate sample time from /summary/today — drives the
    // "synced Xm ago" freshness line on the neon Today screen.
    @Json(name = "last_sync") val lastSync: String? = null,
    // Fields /summary/today backfilled from an EARLIER day, mapped to the
    // date the value actually came from. Overnight metrics go missing until
    // the watch syncs last night; without this the Body screen states a
    // day-old HRV — or a three-month-old weight — as today's fact.
    @Json(name = "carried_from") val carriedFrom: Map<String, String> = emptyMap(),
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
    // PUT /profile replaces the whole row, so every caller must echo back
    // the fields it is not editing. Omitting this one would let the phone's
    // workout-reminder save silently erase a measured max HR set on the web.
    @Json(name = "max_hr") val maxHr: Double? = null,
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
    @Json(name = "max_hr") val maxHr: Double? = null,
    @Json(name = "activity_level") val activityLevel: String? = null,
    val extra: ProfileExtra? = null,
    val derived: ProfileDerived? = null,
) {
    fun stepsGoal(): Int = extra?.stepsGoal ?: 10_000
    fun sleepGoalH(): Double = extra?.sleepGoalH ?: 8.0
    /** Max HR for chart scaling. A measured value wins over the Tanaka
     *  estimate, which in turn beats the age-30 fallback. Zone *boundaries*
     *  no longer come from here — the server owns those (TD-2) — but the HR
     *  chart still scales its axis against this. */
    fun maxHr(): Int = maxHr?.toInt() ?: derived?.maxHrEstimated ?: 187
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
    /** "sleep" or "nap", classified server-side. Defaults to "sleep" so an
     *  older backend that omits it behaves exactly as before. */
    val kind: String = "sleep",
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
    // True extremes over the raw rows. `points` may be bucket AVERAGES (the
    // HR trace requests 2-minute buckets), so min/max taken from them are
    // flattened — a 40s sprint inside a 2-minute bucket disappears into the
    // mean. Server computes these from the unbucketed table.
    @Json(name = "min_bpm") val minBpm: Double? = null,
    @Json(name = "max_bpm") val maxBpm: Double? = null,
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
    // SKIP-1 — on the transition into "completed", ask the server to mark
    // every slot with no logged sets as skipped. Nullable so the key is
    // omitted entirely when unset and the server default (true) stands: the
    // notification action completes a workout with no UI to confirm in.
    // Interactive surfaces ask first and then send this explicitly.
    @Json(name = "close_remaining") val closeRemaining: Boolean? = null,
)

/** PATCH /workout/strength/workout-exercises/{id} — SKIP-1. Returns the
 *  whole workout so the caller picks up the recomputed progress counters. */
@JsonClass(generateAdapter = true)
data class WorkoutExercisePatchRequest(
    val skipped: Boolean,
)

/** POST /workout/strength/workouts/{id}/complete-cardio. Mints a manual
 *  Activity row + marks the cardio-day strength workout complete. */
@JsonClass(generateAdapter = true)
data class CompleteCardioRequest(
    val label: String,
    @Json(name = "duration_minutes") val durationMinutes: Double,
    @Json(name = "start_at") val startAt: String? = null,
    val type: String = "manual_cardio",
    val notes: String? = null,
)

@JsonClass(generateAdapter = true)
data class AiGoal(
    val id: Int,
    val kind: String,
    val title: String,
    @Json(name = "target_value") val targetValue: Double? = null,
    @Json(name = "target_unit") val targetUnit: String? = null,
    @Json(name = "target_date") val targetDate: String? = null,
    @Json(name = "started_at") val startedAt: String,
    @Json(name = "ended_at") val endedAt: String? = null,
    val notes: String? = null,
    @Json(name = "current_value") val currentValue: Double? = null,
    @Json(name = "progress_pct") val progressPct: Double? = null,
    @Json(name = "baseline_value") val baselineValue: Double? = null,
)

@JsonClass(generateAdapter = true)
data class UpdateCheck(
    val current: String,
    val latest: String? = null,
    @Json(name = "latest_tag") val latestTag: String? = null,
    @Json(name = "latest_url") val latestUrl: String? = null,
    @Json(name = "latest_published_at") val latestPublishedAt: String? = null,
    @Json(name = "release_notes") val releaseNotes: String? = null,
    @Json(name = "update_available") val updateAvailable: Boolean = false,
    val error: String? = null,
)

@JsonClass(generateAdapter = true)
data class UpdateApplyResult(
    val triggered: Boolean,
    @Json(name = "trigger_path") val triggerPath: String? = null,
    val error: String? = null,
    val hint: String? = null,
)

@JsonClass(generateAdapter = true)
data class Annotation(
    val id: Int,
    val ts: String,
    val type: String,
    val payload: Map<String, Any> = emptyMap(),
    val note: String? = null,
)

@JsonClass(generateAdapter = true)
data class AnnotationCreate(
    val type: String,
    val payload: Map<String, Any> = emptyMap(),
    val ts: String? = null,
    val note: String? = null,
)

@JsonClass(generateAdapter = true)
data class DeviceStatusPoint(
    val time: String,
    @Json(name = "battery_pct") val batteryPct: Int? = null,
    @Json(name = "is_charging") val isCharging: Boolean? = null,
    @Json(name = "activity_state") val activityState: String? = null,
    @Json(name = "is_worn") val isWorn: Boolean? = null,
    val online: Boolean? = null,
)

@JsonClass(generateAdapter = true)
data class DeviceStatusSeriesResponse(
    @Json(name = "device_id") val deviceId: String,
    val since: String,
    val until: String,
    val count: Int,
    val points: List<DeviceStatusPoint> = emptyList(),
    @Json(name = "on_body_pct") val onBodyPct: Double? = null,
    @Json(name = "on_body_seconds") val onBodySeconds: Double = 0.0,
    @Json(name = "off_body_seconds") val offBodySeconds: Double = 0.0,
    @Json(name = "unknown_seconds") val unknownSeconds: Double = 0.0,
)

// SCS-4 — cookie-mode Strava sync responses.
@JsonClass(generateAdapter = true)
data class StravaCookieSyncResponse(
    val upserted: Int,
    @Json(name = "activity_ids") val activityIds: List<Long> = emptyList(),
    val error: String? = null,
)

@JsonClass(generateAdapter = true)
data class StravaCookieStatusResponse(
    val configured: Boolean,
    @Json(name = "athlete_id") val athleteId: Long? = null,
    @Json(name = "athlete_name") val athleteName: String? = null,
    @Json(name = "last_sync_at") val lastSyncAt: String? = null,
    @Json(name = "last_error") val lastError: String? = null,
    // True when the last sync failed and needs the user to reconnect
    // Strava in Settings (dead cookie / broken auto-login). Drives the
    // reconnect banner on the Activities screen.
    @Json(name = "needs_reconnect") val needsReconnect: Boolean = false,
)


/** GET /summary/training-load — weekly load against the acute:chronic band.
 *  The band and the verdict are the server's; the client renders, never judges. */
@JsonClass(generateAdapter = true)
data class TrainingLoadDay(
    val date: String = "",
    val load: Double = 0.0,
)

@JsonClass(generateAdapter = true)
data class TrainingLoad(
    @Json(name = "week_load") val weekLoad: Double = 0.0,
    @Json(name = "target_low") val targetLow: Double? = null,
    @Json(name = "target_high") val targetHigh: Double? = null,
    val acwr: Double? = null,
    val band: String = "unknown",
    val ctl: Double? = null,
    val atl: Double? = null,
    val daily: List<TrainingLoadDay> = emptyList(),
)
