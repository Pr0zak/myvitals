package app.myvitals.health

import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import app.myvitals.sync.HeartRateSample
import app.myvitals.sync.HrvSample
import app.myvitals.sync.IngestBatch
import app.myvitals.sync.SleepStageSample
import app.myvitals.sync.StepsSample
import app.myvitals.sync.WorkoutSample

object DataMapper {

    fun toBatch(
        heartRate: List<HeartRateRecord>,
        hrv: List<HeartRateVariabilityRmssdRecord>,
        steps: List<StepsRecord>,
        sleep: List<SleepSessionRecord>,
        exercise: List<ExerciseSessionRecord>,
    ): IngestBatch = IngestBatch(
        heartrate = heartRate.flatMap { record ->
            record.samples.map {
                HeartRateSample(time = it.time.toString(), bpm = it.beatsPerMinute.toDouble())
            }
        },
        hrv = hrv.map {
            HrvSample(time = it.time.toString(), rmssdMs = it.heartRateVariabilityMillis)
        },
        steps = steps.map {
            // Health Connect emits stepped intervals; we record at the interval start.
            StepsSample(time = it.startTime.toString(), count = it.count.toInt())
        },
        sleepStages = sleep.flatMap(::sessionStages),
        workouts = exercise.map { session ->
            WorkoutSample(
                time = session.startTime.toString(),
                type = exerciseTypeName(session.exerciseType),
                durationS = (session.endTime.epochSecond - session.startTime.epochSecond).toInt(),
            )
        },
    )

    private fun sessionStages(session: SleepSessionRecord): List<SleepStageSample> {
        // If HC didn't break the session into stages, emit one synthetic "light" stage
        // covering the whole session — better than dropping the data entirely.
        if (session.stages.isEmpty()) {
            return listOf(
                SleepStageSample(
                    time = session.startTime.toString(),
                    stage = "light",
                    durationS = (session.endTime.epochSecond - session.startTime.epochSecond).toInt(),
                )
            )
        }
        return session.stages.map { stage ->
            SleepStageSample(
                time = stage.startTime.toString(),
                stage = stageName(stage.stage),
                durationS = (stage.endTime.epochSecond - stage.startTime.epochSecond).toInt(),
            )
        }
    }

    private fun stageName(stage: Int): String = when (stage) {
        SleepSessionRecord.STAGE_TYPE_AWAKE,
        SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED -> "awake"
        SleepSessionRecord.STAGE_TYPE_LIGHT,
        SleepSessionRecord.STAGE_TYPE_SLEEPING -> "light"
        SleepSessionRecord.STAGE_TYPE_DEEP -> "deep"
        SleepSessionRecord.STAGE_TYPE_REM -> "rem"
        SleepSessionRecord.STAGE_TYPE_OUT_OF_BED -> "out_of_bed"
        else -> "unknown"
    }

    private fun exerciseTypeName(type: Int): String = when (type) {
        ExerciseSessionRecord.EXERCISE_TYPE_RUNNING -> "running"
        ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL -> "running_treadmill"
        ExerciseSessionRecord.EXERCISE_TYPE_WALKING -> "walking"
        ExerciseSessionRecord.EXERCISE_TYPE_HIKING -> "hiking"
        ExerciseSessionRecord.EXERCISE_TYPE_BIKING -> "biking"
        ExerciseSessionRecord.EXERCISE_TYPE_BIKING_STATIONARY -> "biking_stationary"
        ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_POOL -> "swimming_pool"
        ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_OPEN_WATER -> "swimming_open_water"
        ExerciseSessionRecord.EXERCISE_TYPE_YOGA -> "yoga"
        ExerciseSessionRecord.EXERCISE_TYPE_PILATES -> "pilates"
        ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING -> "strength"
        ExerciseSessionRecord.EXERCISE_TYPE_WEIGHTLIFTING -> "weightlifting"
        ExerciseSessionRecord.EXERCISE_TYPE_CALISTHENICS -> "calisthenics"
        ExerciseSessionRecord.EXERCISE_TYPE_HIGH_INTENSITY_INTERVAL_TRAINING -> "hiit"
        ExerciseSessionRecord.EXERCISE_TYPE_BOXING -> "boxing"
        ExerciseSessionRecord.EXERCISE_TYPE_DANCING -> "dancing"
        ExerciseSessionRecord.EXERCISE_TYPE_OTHER_WORKOUT -> "other"
        else -> "type_$type"
    }
}
