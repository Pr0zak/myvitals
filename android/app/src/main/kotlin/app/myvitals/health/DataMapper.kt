package app.myvitals.health

import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.StepsRecord
import app.myvitals.sync.HeartRateSample
import app.myvitals.sync.HrvSample
import app.myvitals.sync.IngestBatch
import app.myvitals.sync.StepsSample

object DataMapper {

    fun toBatch(
        heartRate: List<HeartRateRecord>,
        hrv: List<HeartRateVariabilityRmssdRecord>,
        steps: List<StepsRecord>,
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
    )
}
