package app.myvitals.sync

import android.content.Context
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.SkinTemperatureRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.myvitals.data.AppDatabase
import app.myvitals.data.BufferedBatch
import app.myvitals.data.SettingsRepository
import app.myvitals.health.DataMapper
import app.myvitals.health.HealthConnectGateway
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.withTimeoutOrNull
import timber.log.Timber
import java.time.Instant
import kotlin.reflect.KClass

class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    private val settings = SettingsRepository(context)
    private val gateway = HealthConnectGateway(context)
    private val db = AppDatabase.get(context)
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val batchAdapter = moshi.adapter(IngestBatch::class.java)

    override suspend fun doWork(): Result {
        Timber.d("SyncWorker.doWork()")

        if (!settings.isConfigured()) {
            Timber.w("Skipping sync: not configured (url='%s' tokenSet=%b)",
                settings.backendUrl, settings.bearerToken.isNotEmpty())
            return Result.success()
        }
        if (!gateway.isAvailable()) {
            Timber.w("Skipping sync: Health Connect not available on this device")
            return Result.success()
        }
        if (!gateway.hasAllPermissions()) {
            Timber.w("Skipping sync: HC permissions not granted")
            return Result.success()
        }

        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)

        // 1. Flush any buffered batches first.
        val summaries = db.buffered().summaries()
        Timber.d("Flushing buffer (count=%d): %s", summaries.size,
            summaries.joinToString { "id=${it.id}/bytes=${it.json_len}/attempts=${it.attempts}" })
        if (!flushBuffer(api)) {
            Timber.w("Buffer flush failed; will retry")
            return Result.retry()
        }

        // 2. Read fresh data since last sync (default: last 6 hours on first run).
        // Safety floor: always re-check the past 2 hours even if our checkpoint
        // is more recent. The Pixel Watch sometimes writes step/HR records into
        // Health Connect with timestamps an hour or more in the past (records
        // are queued on the watch and synced when bluetooth is available, so
        // they "arrive" later than their actual time). Without this, late
        // arrivals slip past our `since` filter and never get ingested.
        // Re-uploading already-stored records is a no-op thanks to ON CONFLICT
        // DO NOTHING on the time PK, so the cost is just bandwidth.
        val checkpoint = settings.lastSyncInstant() ?: Instant.now().minusSeconds(6 * 3600)
        val safetyFloor = Instant.now().minusSeconds(2 * 3600)
        val since = if (checkpoint.isBefore(safetyFloor)) checkpoint else safetyFloor
        val until = Instant.now()

        // Per-type try/catch: a SecurityException on one record type (e.g. HC's
        // "record type 11") should not block the others from ingesting.
        val hr = safeRead(HeartRateRecord::class, since, until)
        val hrv = safeRead(HeartRateVariabilityRmssdRecord::class, since, until)
        val steps = safeRead(StepsRecord::class, since, until)
        val sleep = safeRead(SleepSessionRecord::class, since, until)
        val exercise = safeRead(ExerciseSessionRecord::class, since, until)
        val weight = safeRead(WeightRecord::class, since, until)
        val bodyFat = safeRead(BodyFatRecord::class, since, until)
        val leanMass = safeRead(LeanBodyMassRecord::class, since, until)
        val bp = safeRead(BloodPressureRecord::class, since, until)
        val skinTemp = safeRead(SkinTemperatureRecord::class, since, until)
        Timber.i(
            "HC reads since %s: hr=%d hrv=%d steps=%d sleep=%d exercise=%d weight=%d bodyFat=%d leanMass=%d bp=%d skinTemp=%d",
            since, hr.size, hrv.size, steps.size, sleep.size, exercise.size,
            weight.size, bodyFat.size, leanMass.size, bp.size, skinTemp.size,
        )
        val batch = DataMapper.toBatch(
            hr, hrv, steps, sleep, exercise,
            weight = weight, bodyFat = bodyFat, leanMass = leanMass,
            bloodPressure = bp, skinTemp = skinTemp,
        )

        if (batch.isEmpty()) {
            Timber.i("Nothing new to send; advancing checkpoint to %s", until)
            settings.lastSyncEpochSeconds = until.epochSecond
            return Result.success()
        }

        return try {
            ingestChunked(api, batch)
            settings.lastSyncEpochSeconds = until.epochSecond
            Result.success()
        } catch (e: Exception) {
            Timber.e(e, "Ingest POST failed; buffering locally")
            db.buffered().insert(
                BufferedBatch(
                    json = batchAdapter.toJson(batch),
                    createdAtEpochS = until.epochSecond,
                )
            )
            settings.lastSyncEpochSeconds = until.epochSecond
            Result.success()
        }
    }

    private suspend fun <T : Record> safeRead(
        type: KClass<T>,
        since: Instant,
        until: Instant,
    ): List<T> {
        return try {
            gateway.read(type, since, until)
        } catch (e: Exception) {
            Timber.e(e, "HC read FAILED for %s — continuing with empty list", type.simpleName)
            emptyList()
        }
    }

    /**
     * Send [batch] to the backend in pieces no bigger than [MAX_PER_TYPE]
     * records of any single table per request. A 30-day backfill (~37k HR
     * samples) becomes ~10 small POSTs instead of one ~5 MB body that hangs
     * OkHttp/Moshi serialisation.
     *
     * Throws on the first failed POST so the caller can buffer the *original*
     * un-chunked batch for later retry.
     */
    private suspend fun ingestChunked(api: BackendApi, batch: IngestBatch) {
        val hrChunks = batch.heartrate.chunked(MAX_PER_TYPE)
        val hrvChunks = batch.hrv.chunked(MAX_PER_TYPE)
        val stepsChunks = batch.steps.chunked(MAX_PER_TYPE)
        val sleepChunks = batch.sleepStages.chunked(MAX_PER_TYPE)
        val workoutChunks = batch.workouts.chunked(MAX_PER_TYPE)
        val bodyChunks = batch.bodyMetrics.chunked(MAX_PER_TYPE)
        val bpChunks = batch.bloodPressure.chunked(MAX_PER_TYPE)
        val tempChunks = batch.skinTemp.chunked(MAX_PER_TYPE)

        val n = listOf(
            hrChunks.size, hrvChunks.size, stepsChunks.size,
            sleepChunks.size, workoutChunks.size,
            bodyChunks.size, bpChunks.size, tempChunks.size,
        ).maxOrNull() ?: 0

        var totHr = 0; var totHrv = 0; var totSteps = 0; var totSleep = 0; var totWorkouts = 0
        var totBody = 0; var totBp = 0; var totTemp = 0
        for (i in 0 until n) {
            val sub = IngestBatch(
                heartrate = hrChunks.getOrElse(i) { emptyList() },
                hrv = hrvChunks.getOrElse(i) { emptyList() },
                steps = stepsChunks.getOrElse(i) { emptyList() },
                sleepStages = sleepChunks.getOrElse(i) { emptyList() },
                workouts = workoutChunks.getOrElse(i) { emptyList() },
                bodyMetrics = bodyChunks.getOrElse(i) { emptyList() },
                bloodPressure = bpChunks.getOrElse(i) { emptyList() },
                skinTemp = tempChunks.getOrElse(i) { emptyList() },
            )
            if (sub.isEmpty()) continue
            Timber.d(
                "POST chunk %d/%d: hr=%d hrv=%d steps=%d sleep=%d workouts=%d body=%d bp=%d temp=%d",
                i + 1, n, sub.heartrate.size, sub.hrv.size, sub.steps.size,
                sub.sleepStages.size, sub.workouts.size,
                sub.bodyMetrics.size, sub.bloodPressure.size, sub.skinTemp.size,
            )
            val resp = api.ingestBatch(sub)
            totHr += resp.heartrate; totHrv += resp.hrv; totSteps += resp.steps
            totSleep += resp.sleepStages; totWorkouts += resp.workouts
            totBody += resp.bodyMetrics; totBp += resp.bloodPressure; totTemp += resp.skinTemp
        }
        Timber.i(
            "Ingest OK (%d chunks): hr=%d hrv=%d steps=%d sleep_stages=%d workouts=%d body=%d bp=%d skin_temp=%d",
            n, totHr, totHrv, totSteps, totSleep, totWorkouts, totBody, totBp, totTemp,
        )
    }

    private suspend fun flushBuffer(api: BackendApi): Boolean {
        val pending = db.buffered().oldest()
        if (pending.isEmpty()) return true
        Timber.d("Buffer: %d pending entries to flush", pending.size)
        for (b in pending) {
            // Drop poison entries that have failed too many times. Better to lose
            // some samples than to permanently jam the queue.
            if (b.attempts >= MAX_BUFFER_ATTEMPTS) {
                Timber.w("Dropping buffered batch id=%d after %d failed attempts",
                    b.id, b.attempts)
                db.buffered().delete(b.id)
                continue
            }

            // Bound each entry's processing so a hung Moshi/OkHttp call can't
            // block the worker forever (and so we always increment attempts).
            val ok = withTimeoutOrNull(BUFFER_ENTRY_TIMEOUT_MS) {
                processBufferEntry(api, b)
            }

            when (ok) {
                true -> {} // entry handled, continue to next
                false -> return false   // POST failed, stop and retry next sync
                null -> {                // hit the timeout
                    Timber.w("Buffer id=%d timed out after %dms — incrementing attempts",
                        b.id, BUFFER_ENTRY_TIMEOUT_MS)
                    db.buffered().incrementAttempts(b.id)
                    return false
                }
            }
        }
        return true
    }

    /**
     * Returns true on success, false on POST failure (caller stops the loop and
     * lets WorkManager retry). Throws nothing — exceptions are caught inline.
     */
    private suspend fun processBufferEntry(api: BackendApi, b: BufferedBatch): Boolean {
        Timber.d("Buffer id=%d: parsing %d-byte payload", b.id, b.json.length)
        val batch = try {
            batchAdapter.fromJson(b.json)
        } catch (e: Exception) {
            Timber.w(e, "Buffer id=%d: JSON parse threw — dropping", b.id)
            db.buffered().delete(b.id)
            return true
        }
        if (batch == null) {
            Timber.w("Dropping malformed buffered batch id=%d", b.id)
            db.buffered().delete(b.id)
            return true
        }
        Timber.d(
            "Buffer id=%d: posting hr=%d hrv=%d steps=%d sleep=%d workouts=%d",
            b.id, batch.heartrate.size, batch.hrv.size, batch.steps.size,
            batch.sleepStages.size, batch.workouts.size,
        )
        return try {
            ingestChunked(api, batch)
            db.buffered().delete(b.id)
            Timber.d("Flushed buffered batch id=%d", b.id)
            true
        } catch (e: Exception) {
            Timber.w(e, "Buffered batch id=%d still failing (attempt=%d)", b.id, b.attempts + 1)
            db.buffered().incrementAttempts(b.id)
            false
        }
    }

    companion object {
        const val UNIQUE_NAME = "myvitals_periodic_sync"
        // Records of any one type per POST. 5 types * 4000 = 20k records max.
        // Backend chunks the INSERT at 4000/chunk too.
        private const val MAX_PER_TYPE = 4000
        // After this many failed attempts the entry is dropped to unjam the queue.
        private const val MAX_BUFFER_ATTEMPTS = 3
        // Per-entry hard wall (parse + ALL its chunked POSTs). Bigger than
        // OkHttp callTimeout (180s) so it doesn't fire spuriously.
        private const val BUFFER_ENTRY_TIMEOUT_MS = 240_000L
    }
}
