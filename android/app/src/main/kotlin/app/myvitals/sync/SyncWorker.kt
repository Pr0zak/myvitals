package app.myvitals.sync

import android.content.Context
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import app.myvitals.data.AppDatabase
import app.myvitals.data.BufferedBatch
import app.myvitals.data.SettingsRepository
import app.myvitals.health.DataMapper
import app.myvitals.health.HealthConnectGateway
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import timber.log.Timber
import java.time.Instant

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
        Timber.d("Flushing buffer (count=%d)", db.buffered().count())
        if (!flushBuffer(api)) {
            Timber.w("Buffer flush failed; will retry")
            return Result.retry()
        }

        // 2. Read fresh data since last sync (default: last 6 hours on first run).
        val since = settings.lastSyncInstant() ?: Instant.now().minusSeconds(6 * 3600)
        val until = Instant.now()

        val batch = try {
            val hr = gateway.read(HeartRateRecord::class, since, until)
            val hrv = gateway.read(HeartRateVariabilityRmssdRecord::class, since, until)
            val steps = gateway.read(StepsRecord::class, since, until)
            Timber.i("HC reads since %s: hr=%d hrv=%d steps=%d",
                since, hr.size, hrv.size, steps.size)
            DataMapper.toBatch(hr, hrv, steps)
        } catch (e: Exception) {
            Timber.e(e, "HC read failed; retry later")
            return Result.retry()
        }

        if (batch.isEmpty()) {
            Timber.i("Nothing new to send; advancing checkpoint to %s", until)
            settings.lastSyncEpochSeconds = until.epochSecond
            return Result.success()
        }

        return try {
            val resp = api.ingestBatch(batch)
            Timber.i("Ingest OK: hr=%d hrv=%d steps=%d", resp.heartrate, resp.hrv, resp.steps)
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

    private suspend fun flushBuffer(api: BackendApi): Boolean {
        val pending = db.buffered().oldest()
        for (b in pending) {
            val batch = batchAdapter.fromJson(b.json)
            if (batch == null) {
                Timber.w("Dropping malformed buffered batch id=%d", b.id)
                db.buffered().delete(b.id)
                continue
            }
            try {
                api.ingestBatch(batch)
                db.buffered().delete(b.id)
                Timber.d("Flushed buffered batch id=%d", b.id)
            } catch (e: Exception) {
                Timber.w(e, "Buffered batch id=%d still failing (attempt=%d)", b.id, b.attempts + 1)
                db.buffered().incrementAttempts(b.id)
                return false
            }
        }
        return true
    }

    companion object {
        const val UNIQUE_NAME = "myvitals_periodic_sync"
    }
}
