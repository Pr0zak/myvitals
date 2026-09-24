package app.myvitals.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.ExerciseRoute
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
 * SA-P3: one session's route, read rather than merely classified.
 *
 * Replaces SA-P2's `RouteAvailability` enum, which only named the three
 * states. That was the right shape while the question was "does a route
 * exist"; the probe answered it (CONSENT_REQUIRED, from both writers, on
 * the 2026-09-19 walk) and the question is now "give me the track". The
 * enum is gone rather than kept beside this, so there is one vocabulary
 * for the three states and not two that can drift.
 *
 * Deliberately not `ExerciseRoute?` — null would collapse the two ways of
 * having no track back into one, which is the exact mistake the Route card
 * made by simply vanishing. A withheld route and an indoor session are
 * different facts and the user can act on only one of them.
 *
 * [Track.polyline] is already ENCODED. The raw coordinates never leave
 * [HealthConnectGateway.routeFor]: nothing upstream of it has a use for a
 * list of lat/lngs, and a value that cannot be held cannot be logged by
 * accident.
 */
sealed interface RouteRead {
    /** A drawable track, Google-encoded at precision 5. [points] is the
     *  number of fixes it was built from — a count, never a coordinate. */
    data class Track(val polyline: String, val points: Int) : RouteRead

    /** Health Connect holds a route and will not release it yet. */
    data object ConsentRequired : RouteRead

    /** Health Connect was asked and has no route for this session. */
    data object NoData : RouteRead

    /** The wire value for `WorkoutSample.route_state`, or null for a
     *  [Track] — a row with a polyline needs no excuse for not having
     *  one. Kept next to the states themselves so the two clients and the
     *  backend column cannot drift apart into different spellings. */
    val wireState: String?
        get() = when (this) {
            is Track -> null
            ConsentRequired -> "consent_required"
            NoData -> "none"
        }

    /** The probe vocabulary SA-P2 shipped, preserved verbatim so the
     *  existing `HCRouteProbe` log lines stay greppable across the
     *  change — a regression here is meant to be visible in the same
     *  query that found the original answer. */
    val probeLabel: String
        get() = when (this) {
            is Track -> "AVAILABLE"
            ConsentRequired -> "CONSENT_REQUIRED"
            NoData -> "NO_DATA"
        }
}

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

    /**
     * SA-P3 — the all-routes grant. Declared, checked, and NEVER
     * requested, because requesting it does nothing.
     *
     * The platform javadoc for
     * `android.health.connect.HealthPermissions.READ_EXERCISE_ROUTES` is
     * explicit: "This permission can only be granted manually by a user in
     * Health Connect settings or in the route request activity which can
     * be launched using ACTION_REQUEST_EXERCISE_ROUTE. **Attempts to
     * request the permission by applications will be ignored.**" It is
     * also API 35+, where minSdk here is 28. So the ordinary permission
     * sheet is not a path to it on any device, and on most devices there
     * is no such permission at all — which is why the button on the Route
     * card launches [ExerciseRouteRequestContract] (that is
     * ACTION_REQUEST_EXERCISE_ROUTE, verified by decompiling the contract)
     * rather than a permission request, and why the copy names Health
     * Connect settings as the other way in.
     *
     * Declaring it still matters: without the manifest entry the grant
     * cannot be turned on in Health Connect settings either, and when it
     * IS on, [routeFor] returns every route in one foreground pass instead
     * of one dialog per walk.
     *
     * Held SEPARATELY from [requiredPermissions] on purpose.
     *
     * Adding it to the required set would have made
     * [hasAllPermissionsAsync] PERMANENTLY false — unrequestable, and on
     * pre-Android-15 devices not even defined — and that is the gate
     * `SyncWorker` checks before reading anything at all — so one declined map would have stopped heart
     * rate, HRV, sleep, steps and body metrics from syncing, and reported
     * itself through the "Health Connect permissions lost" banner as
     * though the whole grant had been revoked. CLAUDE.md already records
     * that HC grants break across APK upgrades; this is the same failure
     * with a self-inflicted trigger. Routes are a nice-to-have on top of
     * telemetry that is not.
     *
     * The string is spelled out rather than taken from a constant because
     * androidx.health.connect:connect-client 1.1.0-alpha11 does not define
     * one: `HealthPermission` carries `PERMISSION_WRITE_EXERCISE_ROUTE`
     * and no read counterpart (checked by decompiling the AAR, not
     * guessed). The platform does —
     * `android.health.connect.HealthPermissions.READ_EXERCISE_ROUTES` in
     * the API 35 android.jar, whose value is exactly this — but that class
     * needs API 34+, and minSdk here is 28.
     *
     * [hasRoutePermission] can still see it once the user turns it on:
     * `getGrantedPermissions()` on API 34+ reports back anything under the
     * `android.permission.health.` prefix that the package manager says is
     * granted, with no allowlist filtering (checked by decompiling
     * `HealthConnectClientUpsideDownImpl`, not assumed).
     */
    val routePermission: String = "android.permission.health.READ_EXERCISE_ROUTES"

    /**
     * True when the all-routes grant is held. Its own check rather than a
     * member of [missingPermissionShortNames] so the permission banner —
     * which means "telemetry is not reaching the server" — never lights up
     * over a map.
     */
    suspend fun hasRoutePermission(): Boolean {
        if (!isAvailable()) return false
        return routePermission in client().permissionController.getGrantedPermissions()
    }

    fun isAvailable(): Boolean =
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE

    private fun client(): HealthConnectClient = HealthConnectClient.getOrCreate(context)

    fun permissionContract() =
        PermissionController.createRequestPermissionResultContract()

    /**
     * Suspending permission check — the correct one for any coroutine/UI
     * caller. Talks to Health Connect over a binder; must NOT run on the main
     * thread. Settings (ConnectionSyncScreen, the shell HC banner) resolve it via produceState; SyncWorker awaits it
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
     * SA-P3 — the probe's read, now taking the track when there is one.
     *
     * Same single-record round trip [routeAvailabilityFor] always made:
     * `exerciseRouteResult` is populated only on a record fetched by ID via
     * [HealthConnectClient.readRecord], never on the paged `readRecords()`
     * list [read] uses. Call it once per session.
     *
     * **This will return [RouteRead.ConsentRequired] from a background
     * worker no matter what is granted**, when the route was written by
     * another app — which is every route on this install. Google:
     * "When your app runs in the background and tries to read an exercise
     * route created by another app, Health Connect returns an
     * ExerciseRouteResult.ConsentRequired response, even if your app has
     * Always allow access to exercise route data." So `SyncWorker` calling
     * this is worth doing (it costs one round-trip, it keeps the
     * `HCRouteProbe` line, and it records the state the UI explains) but
     * it is not the path that produces a map. `RouteBackfill`, run from
     * the foreground on a user tap, is.
     *
     * The coordinates are encoded here and discarded. Nothing above this
     * function ever holds a lat/lng, which is the cheapest way to keep one
     * out of a log line: [RouteRead.Track] carries a polyline and a point
     * count and has nowhere to put a position.
     */
    suspend fun routeFor(sessionId: String): RouteRead {
        val session = client().readRecord(ExerciseSessionRecord::class, sessionId).record
        return when (val result = session.exerciseRouteResult) {
            is ExerciseRouteResult.Data -> {
                val points = result.exerciseRoute.route
                    // Health Connect orders `route` by time already, but it
                    // is a plain list and nothing in the contract promises
                    // it. Sorting is cheap and a track drawn in the wrong
                    // order is a scribble, not a path.
                    .sortedBy { it.time }
                    .map { it.latitude to it.longitude }
                Polylines.encodeOrNull(points)
                    ?.let { RouteRead.Track(it, points.size) }
                // A Data result carrying fewer than two fixes draws
                // nothing. Reporting it as a track would put an empty map
                // card on the screen, which is worse than the honest
                // "there is no route here".
                    ?: RouteRead.NoData
            }
            is ExerciseRouteResult.ConsentRequired -> RouteRead.ConsentRequired
            is ExerciseRouteResult.NoData -> RouteRead.NoData
            else -> RouteRead.NoData
        }
    }

    /**
     * Every exercise session in the window, by ID, so a foreground
     * backfill can resolve which Health Connect record corresponds to an
     * activity the feed already shows. Returns the session's start instant
     * alongside its ID, because `activities.source_id` for a promoted
     * Health Connect session IS that start instant's isoformat — that is
     * the natural key `promote_health_connect_workouts` writes.
     */
    suspend fun exerciseSessionsIn(
        since: Instant,
        until: Instant = Instant.now(),
    ): List<ExerciseSessionRecord> = read(ExerciseSessionRecord::class, since, until)

    /**
     * The Health Connect session behind one activity row, found by its
     * start instant.
     *
     * `activities.source_id` for a promoted Health Connect session IS the
     * session's start instant in isoformat — that is the natural key
     * `promote_health_connect_workouts` writes — so this is a lookup, not
     * a heuristic. It is still tolerant to [TOLERANCE_S], because the
     * instant makes a round trip through Pydantic and Postgres on the way
     * to the client and back, and an equality test on a re-parsed
     * timestamp is the kind of thing that works until it does not.
     *
     * Nearest start wins, so two sessions inside the tolerance cannot
     * silently resolve to the wrong one.
     */
    suspend fun sessionStartingAt(start: Instant): ExerciseSessionRecord? =
        exerciseSessionsIn(
            start.minusSeconds(TOLERANCE_S), start.plusSeconds(TOLERANCE_S),
        ).minByOrNull { kotlin.math.abs(it.startTime.epochSecond - start.epochSecond) }

    /**
     * Encode a route handed back by the per-session request activity.
     *
     * Same encoder and the same "fewer than two fixes is not a route"
     * rule as [routeFor], so the two paths into `activities.polyline`
     * cannot produce different geometry for the same track.
     */
    fun encodeRoute(route: ExerciseRoute): RouteRead {
        val points = route.route.sortedBy { it.time }
            .map { it.latitude to it.longitude }
        return Polylines.encodeOrNull(points)
            ?.let { RouteRead.Track(it, points.size) }
            ?: RouteRead.NoData
    }

    companion object {
        /** Window either side of an activity's start when resolving its
         *  Health Connect session. Two minutes: wide enough for any
         *  serialisation drift, far tighter than the gap between two real
         *  sessions. */
        private const val TOLERANCE_S = 120L
    }
}
