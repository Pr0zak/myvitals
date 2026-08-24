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
import java.time.Duration
import java.time.Instant
import kotlin.math.abs

object DataMapper {

    /**
     * How far apart a weight and its body-composition companions may
     * be and still count as one weigh-in.
     *
     * Two minutes is loose enough for any plausible writer jitter
     * between three records produced by a single step onto a scale,
     * and far tighter than the gap between two genuine weigh-ins —
     * nobody weighs themselves twice inside two minutes and expects
     * the readings kept apart.
     */
    private const val COMPANION_TOLERANCE_S = 120L

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
        // A smart scale writes weight, body fat and lean mass as three
        // separate Health Connect records from one step onto the scale.
        // They are written at ~the same instant, but not necessarily the
        // SAME instant — different writers stamp them milliseconds apart.
        //
        // This used to join them on an exact `Instant.toString()`. One
        // millisecond of drift and the percentage never attached: it fell
        // through to the orphan branch as its own body_metrics row with a
        // null weight, and since the server upserts on `time` alone with
        // ON CONFLICT DO NOTHING, the two could never be merged
        // afterwards either. The reading was not lost, but the body
        // composition was permanently divorced from the weight it
        // belonged to — which for a body-composition scale is most of the
        // point of owning one.
        //
        // Nearest match within a tolerance instead, and each companion
        // record is CLAIMED once so it cannot attach to two different
        // weigh-ins.
        val fatPool = bodyFat.sortedBy { it.time }.toMutableList()
        val leanPool = leanMass.sortedBy { it.time }.toMutableList()

        fun <T> claimNearest(
            pool: MutableList<T>, target: Instant, at: (T) -> Instant,
        ): T? {
            val best = pool.minByOrNull {
                abs(Duration.between(at(it), target).seconds)
            } ?: return null
            if (abs(Duration.between(at(best), target).seconds) > COMPANION_TOLERANCE_S) {
                return null
            }
            pool.remove(best)
            return best
        }

        val weightSamples = weight.sortedBy { it.time }.map { w ->
            val fat = claimNearest(fatPool, w.time) { it.time }
            val lean = claimNearest(leanPool, w.time) { it.time }
            BodyMetricSample(
                time = w.time.toString(),
                weightKg = w.weight.inKilograms,
                bodyFatPct = fat?.percentage?.value,
                leanMassKg = lean?.mass?.inKilograms,
                // The pipe. Health Connect is a bus, so this alone does
                // not say which app wrote the record — see `origin`.
                source = "health_connect",
                origin = w.metadata.dataOrigin.packageName.takeIf { it.isNotBlank() },
            )
        }

        // Whatever went unclaimed is genuinely standalone — a body-fat
        // percentage typed in by hand, say — and is still worth keeping.
        val orphanFat = fatPool.map {
            BodyMetricSample(
                time = it.time.toString(),
                bodyFatPct = it.percentage.value,
                source = "health_connect",
                origin = it.metadata.dataOrigin.packageName.takeIf { p -> p.isNotBlank() },
            )
        }
        val orphanLean = leanPool.map {
            BodyMetricSample(
                time = it.time.toString(),
                leanMassKg = it.mass.inKilograms,
                source = "health_connect",
                origin = it.metadata.dataOrigin.packageName.takeIf { p -> p.isNotBlank() },
            )
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
