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
import app.myvitals.BuildConfig
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

/**
 * Per-attempt diagnostic state. Mutated as the worker runs; posted to the
 * backend as a heartbeat at the end of every doWork() invocation, even if
 * the worker exited early (not configured / no perms / HC unavailable).
 *
 * Lets the dashboard tell the difference between
 *   - "phone tried 3 min ago but every HC read 401'd" (perms_lost)
 *   - "phone hasn't checked in for 6 hours" (last_attempt is old)
 *   - "phone is syncing fine but watch hasn't pushed new data" (success +
 *     records_pulled = 0).
 */
private data class AttemptState(
    var success: Boolean = false,
    var permissionsLost: Boolean = false,
    var permsGranted: Int? = null,
    var permsRequired: Int? = null,
    var permsMissing: List<String>? = null,
    val errors: MutableList<String> = mutableListOf(),
    var recordsPulled: Int = 0,
)

class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    private val settings = SettingsRepository(context)
    private val gateway = HealthConnectGateway(context)
    private val db = AppDatabase.get(context)
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val batchAdapter = moshi.adapter(IngestBatch::class.java)
    private val state = AttemptState()

    override suspend fun doWork(): Result {
        Timber.d("SyncWorker.doWork()")
        val attemptAt = Instant.now()
        return try {
            runSync(attemptAt)
        } finally {
            persistFlags()
            sendHeartbeat(attemptAt)
        }
    }

    private suspend fun runSync(now: Instant): Result {
        if (!settings.isConfigured()) {
            val msg = "Skipping sync: not configured (url='${settings.backendUrl}' tokenSet=${settings.bearerToken.isNotEmpty()})"
            Timber.w(msg)
            state.errors += msg
            return Result.success()
        }
        if (!gateway.isAvailable()) {
            val msg = "Skipping sync: Health Connect not available on this device"
            Timber.w(msg)
            state.errors += msg
            return Result.success()
        }

        // Permission inventory — log explicit granted vs missing list every
        // run. Way easier to diagnose revocations than chasing SecurityException
        // stack traces.
        try {
            val missing = gateway.missingPermissionShortNames()
            state.permsRequired = gateway.requiredPermissions.size
            state.permsGranted = state.permsRequired!! - missing.size
            state.permsMissing = missing.takeIf { it.isNotEmpty() }
            if (missing.isEmpty()) {
                Timber.i("Perms: %d/%d granted", state.permsGranted, state.permsRequired)
            } else {
                Timber.w("Perms: %d/%d granted; MISSING %s",
                    state.permsGranted, state.permsRequired, missing.joinToString())
            }
        } catch (e: Exception) {
            Timber.w(e, "Permission inventory failed")
            state.errors += "perm inventory: ${e.javaClass.simpleName}: ${e.message?.take(160)}"
        }

        if (!gateway.hasAllPermissions()) {
            val msg = "Skipping sync: HC permissions not granted (missing=${state.permsMissing ?: "?"})"
            Timber.w(msg)
            state.errors += msg
            state.permissionsLost = true
            return Result.success()
        }

        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)

        // 1. Flush any buffered batches first.
        val summaries = db.buffered().summaries()
        Timber.d("Flushing buffer (count=%d): %s", summaries.size,
            summaries.joinToString { "id=${it.id}/bytes=${it.json_len}/attempts=${it.attempts}" })
        if (!flushBuffer(api)) {
            Timber.w("Buffer flush failed; will retry")
            state.errors += "buffer flush failed"
            return Result.retry()
        }

        // 2. Read fresh data since last sync (default: last 6 hours on first run).
        //
        // Safety floor: always re-check the past 48 hours even if our
        // checkpoint is more recent. The Pixel Watch batches HR/sleep
        // records and pushes them to Health Connect when bluetooth /
        // wifi is stable — sometimes a day or more after the records'
        // actual timestamps.
        //
        // Plus every 6h a 7-day deep sweep covers anything that fell
        // through the 48h floor (e.g. samples that arrived 3+ days late).
        val checkpoint = settings.lastSyncInstant() ?: now.minusSeconds(6 * 3600)
        val safetyFloor = now.minusSeconds(48 * 3600)
        val needDeepSweep = (now.epochSecond - settings.lastDeepSweepEpochSeconds) > 6 * 3600
        val since = when {
            needDeepSweep -> {
                Timber.i("Deep sweep — pulling last 7 days of HC")
                now.minusSeconds(7 * 86400)
            }
            checkpoint.isBefore(safetyFloor) -> checkpoint
            else -> safetyFloor
        }
        val until = now

        // Per-type try/catch: a SecurityException on one record type should
        // not block the others.
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
        state.recordsPulled = hr.size + hrv.size + steps.size + sleep.size + exercise.size +
            weight.size + bodyFat.size + leanMass.size + bp.size + skinTemp.size

        val batch = DataMapper.toBatch(
            hr, hrv, steps, sleep, exercise,
            weight = weight, bodyFat = bodyFat, leanMass = leanMass,
            bloodPressure = bp, skinTemp = skinTemp,
        )

        if (batch.isEmpty()) {
            Timber.i("Nothing new to send; advancing checkpoint to %s", until)
            settings.lastSyncEpochSeconds = until.epochSecond
            if (needDeepSweep) settings.lastDeepSweepEpochSeconds = until.epochSecond
            state.success = true
            return Result.success()
        }

        return try {
            ingestChunked(api, batch)
            settings.lastSyncEpochSeconds = until.epochSecond
            if (needDeepSweep) settings.lastDeepSweepEpochSeconds = until.epochSecond
            state.success = true
            Result.success()
        } catch (e: Exception) {
            Timber.e(e, "Ingest POST failed; buffering locally")
            state.errors += "ingest POST: ${e.javaClass.simpleName}: ${e.message?.take(200)}"
            db.buffered().insert(
                BufferedBatch(
                    json = batchAdapter.toJson(batch),
                    createdAtEpochS = until.epochSecond,
                )
            )
            settings.lastSyncEpochSeconds = until.epochSecond
            // Don't advance the deep-sweep checkpoint when the request fails —
            // we want to retry the deep sweep on the next periodic run.
            Result.success()
        }
    }

    private fun persistFlags() {
        if (state.success) {
            settings.lastSuccessEpochSeconds = Instant.now().epochSecond
            settings.permissionsLost = false
        } else if (state.permissionsLost) {
            settings.permissionsLost = true
        }
    }

    private suspend fun sendHeartbeat(attemptAt: Instant) {
        if (!settings.isConfigured()) return
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val errorSummary = state.errors.joinToString("\n")
                .take(1800)
                .ifEmpty { null }
            api.heartbeat(
                HeartbeatPayload(
                    attemptAt = attemptAt.toString(),
                    success = state.success,
                    permissionsLost = state.permissionsLost,
                    permsGranted = state.permsGranted,
                    permsRequired = state.permsRequired,
                    permsMissing = state.permsMissing,
                    lastSuccessAt = settings.lastSuccessInstant()?.toString(),
                    errorSummary = errorSummary,
                    recordsPulled = state.recordsPulled.takeIf { it > 0 },
                    appVersion = BuildConfig.VERSION_NAME,
                )
            )
        } catch (e: Exception) {
            Timber.w(e, "Heartbeat POST failed (non-fatal)")
        }
    }

    private suspend fun <T : Record> safeRead(
        type: KClass<T>,
        since: Instant,
        until: Instant,
    ): List<T> {
        return try {
            gateway.read(type, since, until)
        } catch (e: SecurityException) {
            // HC denied — almost always means the user revoked perms (or the
            // grant got dropped on app upgrade). Track it so the dashboard
            // can surface a clear "re-grant permissions" prompt.
            state.permissionsLost = true
            val concise = "HC ${type.simpleName} denied: ${e.message?.lineSequence()?.firstOrNull()?.take(180)}"
            Timber.e(concise)
            state.errors += concise
            emptyList()
        } catch (e: Exception) {
            Timber.e(e, "HC read FAILED for %s — continuing with empty list", type.simpleName)
            state.errors += "HC ${type.simpleName}: ${e.javaClass.simpleName}: ${e.message?.take(160)}"
            emptyList()
        }
    }

    /**
     * Send [batch] to the backend in pieces no bigger than [MAX_PER_TYPE]
     * records of any single table per request.
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
        val sessionChunks = batch.sleepSessions.chunked(MAX_PER_TYPE)

        val n = listOf(
            hrChunks.size, hrvChunks.size, stepsChunks.size,
            sleepChunks.size, workoutChunks.size,
            bodyChunks.size, bpChunks.size, tempChunks.size, sessionChunks.size,
        ).maxOrNull() ?: 0

        var totHr = 0; var totHrv = 0; var totSteps = 0; var totSleep = 0; var totWorkouts = 0
        var totBody = 0; var totBp = 0; var totTemp = 0; var totSessions = 0
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
                sleepSessions = sessionChunks.getOrElse(i) { emptyList() },
            )
            if (sub.isEmpty()) continue
            Timber.d(
                "POST chunk %d/%d: hr=%d hrv=%d steps=%d sleep_stages=%d sleep_sess=%d workouts=%d body=%d bp=%d temp=%d",
                i + 1, n, sub.heartrate.size, sub.hrv.size, sub.steps.size,
                sub.sleepStages.size, sub.sleepSessions.size, sub.workouts.size,
                sub.bodyMetrics.size, sub.bloodPressure.size, sub.skinTemp.size,
            )
            val resp = api.ingestBatch(sub)
            totHr += resp.heartrate; totHrv += resp.hrv; totSteps += resp.steps
            totSleep += resp.sleepStages; totWorkouts += resp.workouts
            totBody += resp.bodyMetrics; totBp += resp.bloodPressure; totTemp += resp.skinTemp
            totSessions += resp.sleepSessions
        }
        Timber.i(
            "Ingest OK (%d chunks): hr=%d hrv=%d steps=%d sleep_stages=%d sleep_sess=%d workouts=%d body=%d bp=%d skin_temp=%d",
            n, totHr, totHrv, totSteps, totSleep, totSessions, totWorkouts, totBody, totBp, totTemp,
        )
    }

    private suspend fun flushBuffer(api: BackendApi): Boolean {
        val pending = db.buffered().oldest()
        if (pending.isEmpty()) return true
        Timber.d("Buffer: %d pending entries to flush", pending.size)
        for (b in pending) {
            if (b.attempts >= MAX_BUFFER_ATTEMPTS) {
                Timber.w("Dropping buffered batch id=%d after %d failed attempts",
                    b.id, b.attempts)
                db.buffered().delete(b.id)
                continue
            }

            val ok = withTimeoutOrNull(BUFFER_ENTRY_TIMEOUT_MS) {
                processBufferEntry(api, b)
            }

            when (ok) {
                true -> {}
                false -> return false
                null -> {
                    Timber.w("Buffer id=%d timed out after %dms — incrementing attempts",
                        b.id, BUFFER_ENTRY_TIMEOUT_MS)
                    db.buffered().incrementAttempts(b.id)
                    return false
                }
            }
        }
        return true
    }

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
        private const val MAX_PER_TYPE = 4000
        private const val MAX_BUFFER_ATTEMPTS = 3
        private const val BUFFER_ENTRY_TIMEOUT_MS = 240_000L
    }
}
