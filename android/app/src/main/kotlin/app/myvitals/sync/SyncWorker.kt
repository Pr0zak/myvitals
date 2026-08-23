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
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull
import timber.log.Timber
import java.time.Duration
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
            try {
                runSync(attemptAt)
            } catch (e: CancellationException) {
                state.errors += "cancelled before completion"
                throw e
            } catch (e: Throwable) {
                Timber.e(e, "SyncWorker runSync threw")
                state.errors += "${e.javaClass.simpleName}: ${e.message?.take(180) ?: "(no message)"}"
                Result.retry()
            }
        } finally {
            persistFlags()
            sendHeartbeat(attemptAt)
            kickAlertPollers()
        }
    }

    /** Drain offline strength buffers — set logs + workout status
     *  patches + exercise-pref toggles. Best-effort: a network failure
     *  inside StrengthRepository.flush* just leaves the rows for the
     *  next tick. The reason this is here (and not screen-only) is so
     *  buffered writes sync even if the user never re-opens the
     *  workout screen while back online. */
    private suspend fun flushStrengthBuffers() {
        try {
            val repo = app.myvitals.strength.StrengthRepository(applicationContext, settings)
            val sets = repo.flushBufferedSets()
            val writes = repo.flushBufferedWorkoutWrites()
            if (sets > 0 || writes > 0) {
                Timber.i("Flushed strength buffers: %d sets, %d writes", sets, writes)
            }
        } catch (e: Exception) {
            Timber.w(e, "flushStrengthBuffers failed")
            state.errors += "strength flush: ${e.javaClass.simpleName}"
        }
    }

    /** Enqueue one-shot trail + AI alert polls so any backend alerts
     *  surface within the same 15-min sync cycle instead of waiting
     *  for the next periodic tick (avg latency 7.5 min lower).
     *  Idempotent — WorkManager dedupes by unique name. */
    private fun kickAlertPollers() {
        try {
            val mgr = androidx.work.WorkManager.getInstance(applicationContext)
            val constraints = androidx.work.Constraints.Builder()
                .setRequiredNetworkType(androidx.work.NetworkType.CONNECTED)
                .build()
            mgr.enqueueUniqueWork(
                app.myvitals.trails.TrailAlertWorker.UNIQUE_NAME + "_oneshot",
                androidx.work.ExistingWorkPolicy.REPLACE,
                androidx.work.OneTimeWorkRequestBuilder<
                    app.myvitals.trails.TrailAlertWorker>()
                    .setConstraints(constraints).build(),
            )
            mgr.enqueueUniqueWork(
                app.myvitals.ai.AiAlertWorker.UNIQUE_NAME + "_oneshot",
                androidx.work.ExistingWorkPolicy.REPLACE,
                androidx.work.OneTimeWorkRequestBuilder<
                    app.myvitals.ai.AiAlertWorker>()
                    .setConstraints(constraints).build(),
            )
        } catch (e: Exception) {
            Timber.w(e, "kickAlertPollers failed")
        }
    }

    /**
     * Reconcile locally cached display preferences with the server's.
     *
     * The server is authoritative, so this overwrites the local cache
     * rather than merging. A change made on the phone was pushed at the
     * moment it was made, so by the time this runs the server already has
     * it — the only way the two differ here is if the web changed it.
     *
     * Best-effort: a 404 from a backend older than v0.11.1, or no network,
     * must leave the cached preference alone rather than reverting the
     * user to defaults.
     */
    private suspend fun syncDisplayPrefs() {
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val prefs = api.displayPrefs()
            val imperial = prefs.units != "metric"
            if (imperial != settings.unitsImperial) {
                settings.unitsImperial = imperial
                Timber.i("display prefs: units -> %s", prefs.units)
            }
            if (prefs.timeFormat != settings.timeFormat) {
                settings.timeFormat = prefs.timeFormat
            }
        } catch (e: Exception) {
            Timber.d("display prefs sync skipped: %s", e.message)
        }
    }

    private suspend fun runSync(now: Instant): Result {
        if (!settings.isConfigured()) {
            val msg = "Skipping sync: not configured (url='${settings.backendUrl}' tokenSet=${settings.bearerToken.isNotEmpty()})"
            Timber.w(msg)
            state.errors += msg
            return Result.success()
        }
        // Drain offline strength buffers (set logs + status patches +
        // pref toggles). These are independent of the HC ingest pipeline
        // and can flush even when HC perms are missing — they only need
        // the backend URL + token. Without this, a user who logged sets
        // offline must re-open the workout screen while online for them
        // to sync.
        flushStrengthBuffers()

        // DISP-1: pull display preferences down. Placed here — before the
        // Health Connect availability gate — because it needs only the URL
        // and token, so a device without HC still picks up a unit change
        // made on the web.
        syncDisplayPrefs()

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

        if (!gateway.hasAllPermissionsAsync()) {
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

        // Pre-flight: drop rows whose JSON exceeds the safe Room read size.
        // Android's CursorWindow is ~2 MB; a single >2 MB row causes
        // SQLiteBlobTooBigException on every subsequent buffered_batches read,
        // which silently breaks the whole SyncWorker. Without this guard, an
        // accumulated deep-sweep payload from a multi-day offline period can
        // permanently jam the pipe.
        val oversized = summaries.filter { it.json_len > MAX_SAFE_BUFFER_JSON_BYTES }
        if (oversized.isNotEmpty()) {
            val sizeList = oversized.joinToString { "id=${it.id}/bytes=${it.json_len}" }
            Timber.w("Dropping %d oversized buffered batches (>%d bytes): %s",
                oversized.size, MAX_SAFE_BUFFER_JSON_BYTES, sizeList)
            for (row in oversized) db.buffered().delete(row.id)
            state.errors += "dropped ${oversized.size} buffer row(s) over " +
                "${MAX_SAFE_BUFFER_JSON_BYTES / 1000}KB: $sizeList"
        }

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
        val rawSince = when {
            needDeepSweep -> {
                Timber.i("Deep sweep — pulling last 7 days of HC")
                now.minusSeconds(7 * 86400)
            }
            checkpoint.isBefore(safetyFloor) -> checkpoint
            else -> safetyFloor
        }

        // An explicit backfill is NOT checkpoint drift, and must not be
        // clamped like it.
        //
        // The clamp below exists for drift: a checkpoint left far in the
        // past by a crash or a long offline period would otherwise grow the
        // read window without bound. But the Settings screen also offers
        // "30 days", "1 year" and "All (10y)" buttons, and those set the
        // same checkpoint — so all three were clamped to a fortnight. The
        // screen said "Backfilling 1 year", the log said "sync window
        // clamped to 14d", and anything older was permanently unreachable.
        //
        // That is how weight readings from two months ago stayed invisible:
        // a watermark only moves forward, the 7-day sweep never reaches
        // them, and the one control that should have rescued them silently
        // read the last two weeks instead.
        val backfillFrom = settings.backfillFromEpochSeconds
            .takeIf { it > 0 }
            ?.let(Instant::ofEpochSecond)

        val since: Instant
        if (backfillFrom != null) {
            since = minOf(backfillFrom, rawSince)
            Timber.i(
                "Backfill requested: reading from %s (%d days) — clamp not applied",
                since, Duration.between(since, now).toDays(),
            )
        } else {
            // Anything older than this is either already sitting in the Room
            // buffer waiting to replay, or was dropped and is unrecoverable
            // regardless. Bounding the window keeps the app syncing.
            val maxLookback = now.minusSeconds(MAX_LOOKBACK_DAYS * 86400L)
            since = if (rawSince.isBefore(maxLookback)) {
                Timber.w(
                    "Sync window clamped: checkpoint %s is older than %d days; reading from %s",
                    rawSince, MAX_LOOKBACK_DAYS, maxLookback,
                )
                state.errors += "sync window clamped to ${MAX_LOOKBACK_DAYS}d " +
                    "(use Settings > Backfill to reach further back)"
                maxLookback
            } else {
                rawSince
            }
        }
        val until = now

        // Read and deliver in slices, oldest first.
        //
        // One read over a year-long window is not viable: Health Connect
        // returns heart-rate samples by the hundred thousand,
        // HealthConnectGateway.read() stops at 100 pages and RETURNS THE
        // PARTIAL LIST as if it were complete, and holding a year of
        // samples in memory on a phone is how the worker gets killed. So
        // the window is walked in SLICE_DAYS chunks and each one is
        // delivered before the next is read — bounded memory, bounded
        // POST size, and no silent truncation.
        //
        // Ordinary syncs are a single slice, so this costs them nothing.
        var earliestFailure: Instant? = null
        var anyDelivered = false
        var sliceStart = since
        var sliceIndex = 0
        val totalSlices = ((Duration.between(since, until).seconds /
            (SLICE_DAYS * 86400L)) + 1).toInt()

        while (sliceStart.isBefore(until)) {
            val sliceEnd = minOf(sliceStart.plusSeconds(SLICE_DAYS * 86400L), until)
            sliceIndex++
            if (totalSlices > 1) {
                Timber.i("Slice %d/%d: %s .. %s", sliceIndex, totalSlices, sliceStart, sliceEnd)
            }

            // Per-type try/catch: a SecurityException on one record type
            // should not block the others.
            val hr = safeRead(HeartRateRecord::class, sliceStart, sliceEnd)
            val hrv = safeRead(HeartRateVariabilityRmssdRecord::class, sliceStart, sliceEnd)
            val steps = safeRead(StepsRecord::class, sliceStart, sliceEnd)
            val sleep = safeRead(SleepSessionRecord::class, sliceStart, sliceEnd)
            val exercise = safeRead(ExerciseSessionRecord::class, sliceStart, sliceEnd)
            val weight = safeRead(WeightRecord::class, sliceStart, sliceEnd)
            val bodyFat = safeRead(BodyFatRecord::class, sliceStart, sliceEnd)
            val leanMass = safeRead(LeanBodyMassRecord::class, sliceStart, sliceEnd)
            val bp = safeRead(BloodPressureRecord::class, sliceStart, sliceEnd)
            val skinTemp = safeRead(SkinTemperatureRecord::class, sliceStart, sliceEnd)
            Timber.i(
                "HC reads %s..%s: hr=%d hrv=%d steps=%d sleep=%d exercise=%d weight=%d bodyFat=%d leanMass=%d bp=%d skinTemp=%d",
                sliceStart, sliceEnd, hr.size, hrv.size, steps.size, sleep.size,
                exercise.size, weight.size, bodyFat.size, leanMass.size, bp.size,
                skinTemp.size,
            )
            state.recordsPulled += hr.size + hrv.size + steps.size + sleep.size +
                exercise.size + weight.size + bodyFat.size + leanMass.size +
                bp.size + skinTemp.size

            val batch = DataMapper.toBatch(
                hr, hrv, steps, sleep, exercise,
                weight = weight, bodyFat = bodyFat, leanMass = leanMass,
                bloodPressure = bp, skinTemp = skinTemp,
            )

            if (!batch.isEmpty()) {
                try {
                    ingestChunked(api, batch)
                    anyDelivered = true
                } catch (e: Exception) {
                    Timber.e(e, "Ingest POST failed for slice %s..%s; buffering locally",
                        sliceStart, sliceEnd)
                    state.errors += "ingest POST: ${e.javaClass.simpleName}: " +
                        "${e.message?.take(200)}"
                    // Split the failed batch using the same per-type slicing
                    // as ingestChunked. A single Room row holding a full
                    // multi-day payload can exceed Android's ~2 MB
                    // CursorWindow and permanently jam every future
                    // buffered_batches read.
                    for (sub in splitForBuffer(batch)) {
                        db.buffered().insert(
                            BufferedBatch(
                                json = batchAdapter.toJson(sub),
                                createdAtEpochS = sliceEnd.epochSecond,
                            )
                        )
                    }
                    if (earliestFailure == null) earliestFailure = sliceStart
                }
            }
            sliceStart = sliceEnd
        }

        // Where the cursor lands.
        //
        // It used to stay put on ANY ingest failure. That is right — a
        // buffered batch can still be dropped (oversized rows are deleted,
        // and flushBuffer gives up after MAX_BUFFER_ATTEMPTS), and once the
        // cursor has moved past a window nothing can ever re-read it, which
        // is silent permanent loss of samples the watch recorded.
        //
        // With slices there is a better answer than redoing everything:
        // park the cursor at the START of the earliest slice that failed.
        // Everything before it demonstrably landed, everything from there
        // on is re-read next time. Re-reading costs nothing — the server's
        // _bulk_upsert is on_conflict_do_nothing — while losing data does.
        val newCheckpoint = earliestFailure ?: until
        settings.lastSyncEpochSeconds = newCheckpoint.epochSecond
        if (needDeepSweep && earliestFailure == null) {
            settings.lastDeepSweepEpochSeconds = until.epochSecond
        }
        if (backfillFrom != null) {
            if (earliestFailure == null) {
                // One-shot: the request has been served, so it must not
                // widen every subsequent sync forever.
                settings.backfillFromEpochSeconds = 0L
                Timber.i("Backfill complete (%d records pulled)", state.recordsPulled)
            } else {
                // Keep the request alive, narrowed to what is still missing.
                settings.backfillFromEpochSeconds = earliestFailure.epochSecond
                Timber.w("Backfill partially delivered; will resume from %s", earliestFailure)
            }
        }
        if (!anyDelivered) {
            Timber.i("Nothing new to send; checkpoint now %s", newCheckpoint)
        }
        state.success = true
        return Result.success()
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
     * Slice [batch] into sub-batches each holding at most [MAX_PER_TYPE]
     * records of any single record type. Used both for the staged POSTs in
     * [ingestChunked] and for buffering on POST failure — same slicing keeps
     * each Room row's JSON well under Android's CursorWindow ceiling.
     */
    internal fun splitForBuffer(batch: IngestBatch): List<IngestBatch> {
        val hr = batch.heartrate.chunked(MAX_PER_TYPE)
        val hrv = batch.hrv.chunked(MAX_PER_TYPE)
        val steps = batch.steps.chunked(MAX_PER_TYPE)
        val sleep = batch.sleepStages.chunked(MAX_PER_TYPE)
        val workouts = batch.workouts.chunked(MAX_PER_TYPE)
        val body = batch.bodyMetrics.chunked(MAX_PER_TYPE)
        val bp = batch.bloodPressure.chunked(MAX_PER_TYPE)
        val temp = batch.skinTemp.chunked(MAX_PER_TYPE)
        val sessions = batch.sleepSessions.chunked(MAX_PER_TYPE)
        val n = listOf(
            hr.size, hrv.size, steps.size, sleep.size, workouts.size,
            body.size, bp.size, temp.size, sessions.size,
        ).maxOrNull() ?: 0
        val out = ArrayList<IngestBatch>(n)
        for (i in 0 until n) {
            val sub = IngestBatch(
                heartrate = hr.getOrElse(i) { emptyList() },
                hrv = hrv.getOrElse(i) { emptyList() },
                steps = steps.getOrElse(i) { emptyList() },
                sleepStages = sleep.getOrElse(i) { emptyList() },
                workouts = workouts.getOrElse(i) { emptyList() },
                bodyMetrics = body.getOrElse(i) { emptyList() },
                bloodPressure = bp.getOrElse(i) { emptyList() },
                skinTemp = temp.getOrElse(i) { emptyList() },
                sleepSessions = sessions.getOrElse(i) { emptyList() },
            )
            if (!sub.isEmpty()) out += sub
        }
        return out
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

        /** Widest window a single sync will read from Health Connect.
         *
         *  A failed delivery no longer advances the cursor, so without this
         *  a long outage would grow the window without bound — and
         *  HealthConnectGateway.read() caps at 100 pages and returns the
         *  partial list as though it were complete, which fails silently
         *  rather than loudly. 14 days is twice the deep-sweep window. */
        private const val MAX_LOOKBACK_DAYS = 14

        /**
         * Widest window handed to a single Health Connect read.
         *
         * Not a policy limit — a mechanical one. `read()` walks at most
         * 100 pages of 5,000 and then returns what it has WITHOUT
         * saying so, so any window big enough to exceed that truncates
         * silently. Slicing keeps every individual read comfortably
         * inside the cap, and bounds peak memory to one slice.
         */
        private const val SLICE_DAYS = 14L
        private const val BUFFER_ENTRY_TIMEOUT_MS = 240_000L

        // Android's CursorWindow ceiling is ~2 MB; any single buffered_batches
        // row whose `json` column exceeds it throws SQLiteBlobTooBigException
        // on every read of that table. 1.5 MB gives margin for the
        // unaccounted-for cursor metadata + UTF-8 expansion.
        internal const val MAX_SAFE_BUFFER_JSON_BYTES = 1_500_000
    }
}
