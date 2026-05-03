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
        if (!settings.isConfigured() || !gateway.isAvailable() || !gateway.hasAllPermissions()) {
            return Result.success()  // not yet set up; nothing to do
        }

        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)

        // 1. Flush any buffered batches first.
        if (!flushBuffer(api)) return Result.retry()

        // 2. Read fresh data since last sync (default: last 6 hours on first run).
        val since = settings.lastSyncInstant() ?: Instant.now().minusSeconds(6 * 3600)
        val until = Instant.now()

        val batch = try {
            DataMapper.toBatch(
                heartRate = gateway.read(HeartRateRecord::class, since, until),
                hrv = gateway.read(HeartRateVariabilityRmssdRecord::class, since, until),
                steps = gateway.read(StepsRecord::class, since, until),
            )
        } catch (e: Exception) {
            return Result.retry()
        }

        if (batch.isEmpty()) {
            settings.lastSyncEpochSeconds = until.epochSecond
            return Result.success()
        }

        return try {
            api.ingestBatch(batch)
            settings.lastSyncEpochSeconds = until.epochSecond
            Result.success()
        } catch (e: Exception) {
            db.buffered().insert(
                BufferedBatch(
                    json = batchAdapter.toJson(batch),
                    createdAtEpochS = until.epochSecond,
                )
            )
            // Buffered locally; treat as success so we don't retry the same window
            // tightly — next periodic run will flush.
            settings.lastSyncEpochSeconds = until.epochSecond
            Result.success()
        }
    }

    private suspend fun flushBuffer(api: BackendApi): Boolean {
        val pending = db.buffered().oldest()
        for (b in pending) {
            val batch = batchAdapter.fromJson(b.json) ?: run {
                db.buffered().delete(b.id)
                continue
            }
            try {
                api.ingestBatch(batch)
                db.buffered().delete(b.id)
            } catch (e: Exception) {
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
