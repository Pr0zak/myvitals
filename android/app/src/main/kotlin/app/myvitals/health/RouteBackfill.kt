package app.myvitals.health

import android.content.Context
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.IngestBatch
import app.myvitals.sync.WorkoutSample
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.Instant

/**
 * SA-P3 — read exercise routes from Health Connect and deliver them, in
 * the FOREGROUND, on a user tap.
 *
 * ## Why this exists at all, rather than living in SyncWorker
 *
 * The obvious design is to let the 15-minute `SyncWorker` carry routes
 * along with everything else, and `SyncWorker` does now read them. It will
 * almost never get one. Google's exercise-routes guide is explicit:
 *
 *   "When your app runs in the background and tries to read an exercise
 *    route created by another app, Health Connect returns an
 *    ExerciseRouteResult.ConsentRequired response, even if your app has
 *    Always allow access to exercise route data."
 *
 * and
 *
 *   "We strongly recommend that you request routes upon deliberate user
 *    interaction with your app, when the user is actively engaged with
 *    your app's UI."
 *
 * Every exercise session on this install is written by another app —
 * `com.fitbit.FitbitMobile` and `nl.appyhapps.healthsync`, per the SA-P2
 * probe — so the background path is refused by design, permission or no
 * permission. A foreground read is the only one that can succeed, which is
 * why this is invoked from the Route card's own button and from
 * MainActivity on launch, never from a schedule.
 *
 * [run] is the pass that uses the all-routes grant, and is a no-op without
 * it. [deliverOne] is the path that works without it — and on Android 14
 * and below, where the grant does not exist at all.
 *
 * ## What it does NOT do
 *
 * It does not create activities and it does not touch anything but the
 * route. It posts `WorkoutSample`s through the ordinary `/ingest/batch`
 * endpoint, exactly as `SyncWorker` does, and lets the HC-1 promotion do
 * what it already does — the alternative was a second write path into
 * `activities`, and two mechanisms for one field is how the two clients
 * end up showing different maps.
 *
 * It also never posts a *bare* sample. A session whose route could not be
 * read contributes `route_state` and nothing else; a session that was
 * never asked contributes no key at all, so the backend's `is not None`
 * filters leave whatever is already stored alone. A backfill run twice
 * must not be able to blank a track the first run found.
 */
object RouteBackfill {

    /**
     * Outcome of one run. Counts, never coordinates — this is the type the
     * UI renders and the type that reaches the log.
     *
     * [tracks] is the only number that means a map appeared.
     * [consentRequired] is the actionable failure: Health Connect is
     * holding routes and will not release them, which after a successful
     * grant means the read was not treated as foreground.
     */
    data class Result(
        val sessions: Int = 0,
        val tracks: Int = 0,
        val consentRequired: Int = 0,
        val noData: Int = 0,
        val delivered: Boolean = false,
        val error: String? = null,
    ) {
        val learnedSomething: Boolean get() = tracks + consentRequired + noData > 0
    }

    /**
     * Widest span one run will sweep, measured back from [run]'s `until`.
     *
     * A bound on work, NOT a platform limit — an earlier draft of this
     * comment claimed the latter and it was wrong, so it is written out
     * here to stop the mistake coming back. Health Connect's history rule
     * is "up to 30 days prior to when any permission was first granted",
     * and this app's grant is from May, so essentially all of its Health
     * Connect history is readable without `READ_HEALTH_DATA_HISTORY`.
     * What the cap actually buys is a ceiling on binder round-trips: one
     * per session, and a sweep is not worth turning into a hundred of
     * them.
     *
     * It also does not restrict the per-activity button, which passes a
     * window around the session it was tapped on — the clamp is relative
     * to `until`, so an activity from May reads fine.
     */
    const val MAX_WINDOW_DAYS = 30L

    /**
     * Read routes for every exercise session between [since] and [until]
     * and post what was learned.
     *
     * Must be called while an Activity is in the foreground. Returns
     * rather than throws: this is invoked from a button, and the caller
     * renders [Result.error] beside the card rather than crashing a
     * screen over a map.
     */
    suspend fun run(
        context: Context,
        settings: SettingsRepository,
        since: Instant,
        until: Instant = Instant.now(),
    ): Result {
        val gateway = HealthConnectGateway(context)
        if (!gateway.isAvailable()) {
            return Result(error = "Health Connect is not available on this device.")
        }
        if (!settings.isConfigured()) {
            return Result(error = "Backend not configured.")
        }
        val floor = until.minusSeconds(MAX_WINDOW_DAYS * 86_400L)
        val from = if (since.isBefore(floor)) floor else since

        val sessions = try {
            gateway.exerciseSessionsIn(from, until)
        } catch (e: SecurityException) {
            Timber.tag(TAG).w("exercise read denied: %s", e.message?.take(160))
            return Result(error = "Health Connect denied the exercise read.")
        } catch (e: Exception) {
            Timber.tag(TAG).w(e, "exercise read failed")
            return Result(error = "Could not read sessions: ${e.javaClass.simpleName}")
        }

        var tracks = 0
        var consent = 0
        var none = 0
        val samples = mutableListOf<WorkoutSample>()
        for (session in sessions) {
            val route = try {
                gateway.routeFor(session.metadata.id)
            } catch (e: SecurityException) {
                // The all-routes grant is missing or was revoked. Nothing
                // to report per-session and nothing to post: leave every
                // stored route_state where it is rather than rewriting
                // them all to a value this run did not actually measure.
                Timber.tag(TAG).w("route read denied: %s", e.message?.take(160))
                return Result(
                    sessions = sessions.size,
                    error = "Health Connect denied route access.",
                )
            } catch (e: Exception) {
                Timber.tag(TAG).w(e, "route read failed for one session")
                continue
            }
            when (route) {
                is RouteRead.Track -> tracks++
                RouteRead.ConsentRequired -> consent++
                RouteRead.NoData -> none++
            }
            Timber.tag(TAG).i(
                "type=%s writer=%s duration_s=%d result=%s points=%d",
                DataMapper.exerciseTypeName(session.exerciseType),
                session.metadata.dataOrigin.packageName.takeIf { it.isNotBlank() }
                    ?: "unknown",
                session.endTime.epochSecond - session.startTime.epochSecond,
                route.probeLabel,
                (route as? RouteRead.Track)?.points ?: 0,
            )
            samples += WorkoutSample(
                time = session.startTime.toString(),
                type = DataMapper.exerciseTypeName(session.exerciseType),
                durationS = (
                    session.endTime.epochSecond - session.startTime.epochSecond
                    ).toInt(),
                polyline = (route as? RouteRead.Track)?.polyline,
                routeState = route.wireState,
                source = session.metadata.dataOrigin.packageName
                    .takeIf { it.isNotBlank() },
                title = session.title,
            )
        }

        if (samples.isEmpty()) {
            return Result(sessions = sessions.size)
        }

        return try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                api.ingestBatch(IngestBatch(workouts = samples))
            }
            Timber.tag(TAG).i(
                "delivered %d session(s): %d track(s), %d withheld, %d with no route",
                samples.size, tracks, consent, none,
            )
            Result(
                sessions = sessions.size, tracks = tracks,
                consentRequired = consent, noData = none, delivered = true,
            )
        } catch (e: Exception) {
            Timber.tag(TAG).w(e, "route delivery failed")
            Result(
                sessions = sessions.size, tracks = tracks,
                consentRequired = consent, noData = none,
                error = "Could not reach the server: ${e.javaClass.simpleName}",
            )
        }
    }

    /**
     * Deliver ONE route obtained from the per-session request activity
     * (`ACTION_REQUEST_EXERCISE_ROUTE`), which hands back an
     * `ExerciseRoute` directly rather than granting a permission.
     *
     * This is the path that works on every device. The all-routes grant is
     * API 35+ and, per the platform javadoc, cannot be requested by an app
     * at all — so a walk on anything older, or on a phone whose owner has
     * not been into Health Connect settings, is reachable only through the
     * per-session dialog.
     *
     * Posts through the same `/ingest/batch` + HC-1 promotion as everything
     * else, so there is exactly one way a polyline reaches `activities`.
     */
    suspend fun deliverOne(
        context: Context,
        settings: SettingsRepository,
        session: androidx.health.connect.client.records.ExerciseSessionRecord,
        route: androidx.health.connect.client.records.ExerciseRoute,
    ): Result {
        if (!settings.isConfigured()) {
            return Result(sessions = 1, error = "Backend not configured.")
        }
        val gateway = HealthConnectGateway(context)
        val read = gateway.encodeRoute(route)
        val track = read as? RouteRead.Track
        Timber.tag(TAG).i(
            "type=%s writer=%s duration_s=%d result=%s points=%d (per-session)",
            DataMapper.exerciseTypeName(session.exerciseType),
            session.metadata.dataOrigin.packageName.takeIf { it.isNotBlank() }
                ?: "unknown",
            session.endTime.epochSecond - session.startTime.epochSecond,
            read.probeLabel,
            track?.points ?: 0,
        )
        val sample = WorkoutSample(
            time = session.startTime.toString(),
            type = DataMapper.exerciseTypeName(session.exerciseType),
            durationS = (
                session.endTime.epochSecond - session.startTime.epochSecond
                ).toInt(),
            polyline = track?.polyline,
            // A dialog the user approved that yielded fewer than two fixes
            // says "there is no drawable route here", which is exactly
            // `none`. Nothing is left implying consent is still pending,
            // or the card would keep offering a dialog that just answered.
            routeState = read.wireState,
            source = session.metadata.dataOrigin.packageName.takeIf { it.isNotBlank() },
            title = session.title,
        )
        return try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                api.ingestBatch(IngestBatch(workouts = listOf(sample)))
            }
            Result(
                sessions = 1,
                tracks = if (track != null) 1 else 0,
                noData = if (track == null) 1 else 0,
                delivered = true,
            )
        } catch (e: Exception) {
            Timber.tag(TAG).w(e, "single-route delivery failed")
            Result(
                sessions = 1,
                tracks = if (track != null) 1 else 0,
                error = "Could not reach the server: ${e.javaClass.simpleName}",
            )
        }
    }

    /**
     * Same tag SA-P2's probe used, so one query over `app_logs` covers
     * both the background classification and the foreground read. A route
     * that stops being released should be findable the way the original
     * answer was found.
     */
    private const val TAG = "HCRouteProbe"
}
