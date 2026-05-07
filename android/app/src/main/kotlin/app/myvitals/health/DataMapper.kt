package app.myvitals.health

import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.SkinTemperatureRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import app.myvitals.sync.BloodPressureSample
import app.myvitals.sync.BodyMetricSample
import app.myvitals.sync.HeartRateSample
import app.myvitals.sync.HrvSample
import app.myvitals.sync.IngestBatch
import app.myvitals.sync.SkinTempSample
import app.myvitals.sync.SleepSessionSample
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
        weight: List<WeightRecord> = emptyList(),
        bodyFat: List<BodyFatRecord> = emptyList(),
        leanMass: List<LeanBodyMassRecord> = emptyList(),
        bloodPressure: List<BloodPressureRecord> = emptyList(),
        skinTemp: List<SkinTemperatureRecord> = emptyList(),
    ): IngestBatch {
        // Body-fat and lean-mass usually arrive as separate HC records but typically
        // share a timestamp (smart scale). Index them by ISO-instant so the matching
        // weight row picks them up.
        val fatByTs = bodyFat.associate { it.time.toString() to it.percentage.value }
        val leanByTs = leanMass.associate { it.time.toString() to it.mass.inKilograms }
        val weightSamples = weight.map { w ->
            val ts = w.time.toString()
            BodyMetricSample(
                time = ts,
                weightKg = w.weight.inKilograms,
                bodyFatPct = fatByTs[ts],
                leanMassKg = leanByTs[ts],
                source = "health_connect",
            )
        }
        // Standalone body-fat / lean-mass rows that didn't share a timestamp with
        // a weight reading still get persisted (so a manual % entry isn't lost).
        val weightTs = weight.map { it.time.toString() }.toHashSet()
        val orphanFat = bodyFat.filter { it.time.toString() !in weightTs }.map {
            BodyMetricSample(time = it.time.toString(), bodyFatPct = it.percentage.value, source = "health_connect")
        }
        val orphanLean = leanMass.filter { it.time.toString() !in weightTs }.map {
            BodyMetricSample(time = it.time.toString(), leanMassKg = it.mass.inKilograms, source = "health_connect")
        }
        return IngestBatch(
            heartrate = heartRate.flatMap { record ->
                record.samples.map {
                    HeartRateSample(time = it.time.toString(), bpm = it.beatsPerMinute.toDouble())
                }
            },
            hrv = hrv.map {
                HrvSample(time = it.time.toString(), rmssdMs = it.heartRateVariabilityMillis)
            },
            steps = steps.map {
                StepsSample(
                    time = it.startTime.toString(),
                    count = it.count.toInt(),
                    source = it.metadata.dataOrigin.packageName
                        .takeIf { p -> p.isNotBlank() } ?: "unknown",
                )
            },
            sleepStages = sleep.flatMap(::sessionStages),
            sleepSessions = sleep.map { s ->
                SleepSessionSample(
                    start = s.startTime.toString(),
                    end = s.endTime.toString(),
                    source = "watch",
                    title = s.title,
                )
            },
            workouts = exercise.map { session ->
                WorkoutSample(
                    time = session.startTime.toString(),
                    type = exerciseTypeName(session.exerciseType),
                    durationS = (session.endTime.epochSecond - session.startTime.epochSecond).toInt(),
                    source = session.metadata.dataOrigin.packageName.takeIf { it.isNotBlank() },
                    title = session.title,
                )
            },
            bodyMetrics = weightSamples + orphanFat + orphanLean,
            bloodPressure = bloodPressure.map { bp ->
                BloodPressureSample(
                    time = bp.time.toString(),
                    systolic = bp.systolic.inMillimetersOfMercury.toInt(),
                    diastolic = bp.diastolic.inMillimetersOfMercury.toInt(),
                    source = "health_connect",
                )
            },
            skinTemp = skinTemp.flatMap { rec ->
                rec.deltas.map { d ->
                    SkinTempSample(time = d.time.toString(), celsiusDelta = d.delta.inCelsius)
                }
            },
        )
    }

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
