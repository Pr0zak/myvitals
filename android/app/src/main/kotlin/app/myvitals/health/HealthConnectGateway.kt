package app.myvitals.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseRouteResult
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.HeartRateVariabilityRmssdRecord
import androidx.health.connect.client.records.LeanBodyMassRecord
import androidx.health.connect.client.records.OxygenSaturationRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.SkinTemperatureRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import kotlinx.coroutines.runBlocking
import timber.log.Timber
import java.time.Instant
import kotlin.reflect.KClass

/**
 * SA-P2: the three states Health Connect reports for one exercise
 * session's route — never the route itself, which this app never reads.
 *
 * - [AVAILABLE] — HC holds route data AND this app already has standing
 *   to read it. Since neither `READ_EXERCISE_ROUTE` nor a per-session
 *   consent grant has ever been requested as of this probe, this value
 *   is not expected to appear yet; if it does, something upstream
 *   already granted access.
 * - [CONSENT_REQUIRED] — HC holds route data for this session, but this
 *   app hasn't been granted it. This is the useful "yes": it proves the
 *   writing app (whatever wrote this session — Fitbit / Google Health /
 *   the phone) DOES attach a route to at least some sessions, discovered
 *   without requesting any new permission.
 * - [NO_DATA] — HC has no route for this session at all. If every recent
 *   outdoor session (running/walking/biking) comes back this way, that
 *   matches the historical belief that Fitbit doesn't write
 *   `ExerciseRoute`, and SA-P2 can close as a documented refusal instead
 *   of an open question.
 */
enum class RouteAvailability { AVAILABLE, CONSENT_REQUIRED, NO_DATA }

class HealthConnectGateway(private val context: Context) {

    val requiredPermissions: Set<String> = setOf(
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class),
        HealthPermission.getReadPermission(OxygenSaturationRecord::class),
        HealthPermission.getReadPermission(SkinTemperatureRecord::class),
        HealthPermission.getReadPermission(StepsRecord::class),
        // Originally requested only because HC seems to require READ_DISTANCE
        // when reading some Steps-related sources ("record type 11"
        // SecurityException) — asking for it preempted that rejection. Since
        // SA-P1 it is also read for real: distanceMetersFor() aggregates it
        // per exercise session for the activities feed.
        HealthPermission.getReadPermission(DistanceRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(WeightRecord::class),
        HealthPermission.getReadPermission(BodyFatRecord::class),
        HealthPermission.getReadPermission(LeanBodyMassRecord::class),
        HealthPermission.getReadPermission(BloodPressureRecord::class),
        // Background reads — WorkManager fires the sync every 15 min
        // while the phone is asleep. Without this, every record-type
        // request throws SecurityException despite per-record perms
        // being granted. Required on Android 14+ / HC 1.1+.
        HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND,
    )

    fun isAvailable(): Boolean =
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE

    private fun client(): HealthConnectClient = HealthConnectClient.getOrCreate(context)

    fun permissionContract() =
        PermissionController.createRequestPermissionResultContract()

    /**
     * Suspending permission check — the correct one for any coroutine/UI
     * caller. Talks to Health Connect over a binder; must NOT run on the main
     * thread. SettingsScreen resolves it via produceState; SyncWorker awaits it
     * directly. See [hasAllPermissions] for the legacy blocking variant.
     */
    suspend fun hasAllPermissionsAsync(): Boolean {
        if (!isAvailable()) return false
        val granted = client().permissionController.getGrantedPermissions()
        return granted.containsAll(requiredPermissions)
    }

    /**
     * Blocking variant. Retained for any non-coroutine caller, but prefer
     * [hasAllPermissionsAsync] — wrapping the binder IPC in runBlocking on the
     * main thread janks the UI (and risks an ANR if HC is cold).
     */
    fun hasAllPermissions(): Boolean {
        if (!isAvailable()) return false
        val granted = runBlocking { client().permissionController.getGrantedPermissions() }
        return granted.containsAll(requiredPermissions)
    }

    /**
     * The set of permissions we need but don't currently have. Empty set = all good.
     * Returns the simple record-type names (e.g. "HeartRateRecord") rather than the
     * full Health Connect permission strings — easier to read in logs / UI.
     */
    suspend fun missingPermissionShortNames(): List<String> {
        if (!isAvailable()) return requiredPermissions.map { it.substringAfterLast('.') }
        val granted = client().permissionController.getGrantedPermissions()
        return (requiredPermissions - granted).map { it.substringAfterLast('.') }.sorted()
    }

    /**
     * Reads ALL records of [type] in the time range, walking HC's pageToken.
     * pageSize=5000 (HC max) keeps round-trips down. Hard cap at 100 pages
     * (≤ 500k records) to avoid runaway loops on bad data.
     */
    suspend fun <T : Record> read(
        type: KClass<T>,
        since: Instant,
        until: Instant = Instant.now(),
    ): List<T> {
        val all = mutableListOf<T>()
        var pageToken: String? = null
        var page = 0
        do {
            val request = ReadRecordsRequest(
                recordType = type,
                timeRangeFilter = TimeRangeFilter.between(since, until),
                pageSize = 5000,
                pageToken = pageToken,
            )
            val response = client().readRecords(request)
            all.addAll(response.records)
            pageToken = response.pageToken
            page++
            if (page >= 100) {
                Timber.w("HC %s: 100-page safety cap hit (records=%d)", type.simpleName, all.size)
                break
            }
        } while (pageToken != null)
        return all
    }

    /**
     * Total distance covered in [since]..[until], via Health Connect's
     * aggregate API (`DistanceRecord.DISTANCE_TOTAL`) rather than paging
     * through raw [DistanceRecord]s and summing them by hand — the same
     * bounded window an [ExerciseSessionRecord] already reports its own
     * start/end for, so this is meant to be called once per session, not
     * once for the whole sync range. Being a single aggregate call, it
     * has none of [read]'s 100-page truncation risk.
     *
     * Returns null — never 0.0 — when Health Connect has no distance data
     * for the window, e.g. an indoor strength session. A caller must not
     * turn that into a measured zero; see [DataMapper] and
     * `WorkoutSample.distanceM`. Throws on the same conditions [read]
     * does (a denied permission, HC unavailable) so callers apply the
     * same try/catch idiom as `SyncWorker.safeRead`.
     */
    suspend fun distanceMetersFor(since: Instant, until: Instant): Double? {
        val response = client().aggregate(
            AggregateRequest(
                metrics = setOf(DistanceRecord.DISTANCE_TOTAL),
                timeRangeFilter = TimeRangeFilter.between(since, until),
            )
        )
        return response[DistanceRecord.DISTANCE_TOTAL]?.inMeters
    }

    /**
     * SA-P2 probe. Resolves which of the three [RouteAvailability] states
     * applies to one exercise session — a category, never a coordinate.
     * Deliberately does NOT touch `ExerciseRouteResult.Data.exerciseRoute`
     * (the actual list of lat/lng points): only the sealed subtype of the
     * result is inspected, so a GPS point can never reach this function's
     * caller, let alone a log line.
     *
     * `exerciseRouteResult` is populated only on a record fetched
     * INDIVIDUALLY by ID via [HealthConnectClient.readRecord] — per HC's
     * documented "read exercise route" workflow, the bulk
     * `readRecords()` path [read] uses above does not carry route data
     * (it's excluded from paged/list projections). So this deliberately
     * costs one binder round-trip per session, the same shape as
     * [distanceMetersFor] / `SyncWorker.safeDistance` — call it once per
     * session, never once for a whole sync window.
     *
     * No new permission is requested or required for this: reading the
     * session itself only needs `READ_EXERCISE` (already granted), and
     * [RouteAvailability.CONSENT_REQUIRED] is exactly HC's way of saying
     * "a route exists but you don't have standing to see it" WITHOUT
     * that standing ever being requested. Declaring
     * `READ_EXERCISE_ROUTE` only becomes a real question once this probe
     * says the answer is worth having — see SA-P2 in
     * `docs/sa-findings.json` for why that's deliberately deferred.
     *
     * Throws on the same conditions [read] does (a denied permission, HC
     * unavailable) so callers apply the same try/catch idiom as
     * `SyncWorker.safeRead`.
     */
    suspend fun routeAvailabilityFor(sessionId: String): RouteAvailability {
        val session = client().readRecord(ExerciseSessionRecord::class, sessionId).record
        return when (session.exerciseRouteResult) {
            is ExerciseRouteResult.Data -> RouteAvailability.AVAILABLE
            is ExerciseRouteResult.ConsentRequired -> RouteAvailability.CONSENT_REQUIRED
            is ExerciseRouteResult.NoData -> RouteAvailability.NO_DATA
            else -> RouteAvailability.NO_DATA
        }
    }
}
