package app.myvitals

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.LaunchedEffect
import app.myvitals.ui.neon.NeonAppShell
import app.myvitals.ui.neon.NeonTheme
import androidx.core.content.ContextCompat
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.data.AppDatabase
import app.myvitals.data.SettingsRepository
import app.myvitals.debug.LogUploadWorker
import app.myvitals.debug.LogViewerActivity
import app.myvitals.health.HealthConnectGateway
import app.myvitals.sync.SyncWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import timber.log.Timber

/** SA-P3 — how often the on-launch route backfill may actually run.
 *  Six hours: routes only appear when a session is recorded, and nobody
 *  records more than a handful a day. */
private const val ROUTE_BACKFILL_MIN_INTERVAL_S = 6L * 3600L

/** Matches SyncWorker.MAX_LOOKBACK_DAYS. Anything older is the job of a
 *  deliberate fetch from the activity's own Route card. */
private const val ROUTE_BACKFILL_WINDOW_DAYS = 14L

class MainActivity : ComponentActivity() {
    /** UX-P8 — every foreground-triggered sync goes through one unique
     *  chain ([SyncWorker.MANUAL_UNIQUE_NAME]). */
    private fun enqueueManualSync(policy: ExistingWorkPolicy) {
        WorkManager.getInstance(applicationContext).enqueueUniqueWork(
            SyncWorker.MANUAL_UNIQUE_NAME,
            policy,
            OneTimeWorkRequestBuilder<SyncWorker>().build(),
        )
    }

    // Re-route to the shortcut's target tab when the user taps a static
    // app shortcut while the app is already running (singleTop + new
    // intent). setIntent makes the new `shortcut_route` extra visible
    // to the next setContent recomposition path.
    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val settings = SettingsRepository(applicationContext)
        val gateway = HealthConnectGateway(applicationContext)

        val permissionLauncher = registerForActivityResult(
            gateway.permissionContract()
        ) { granted ->
            Timber.i("HC permissions returned; granted=%d/%d", granted.size, gateway.requiredPermissions.size)
            if (granted.containsAll(gateway.requiredPermissions)) {
                Timber.i("All HC perms granted — kicking off an immediate sync")
                enqueueManualSync(ExistingWorkPolicy.KEEP)
            }
        }

        val notifLauncher = registerForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { granted -> Timber.i("POST_NOTIFICATIONS granted=%b", granted) }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val state = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            )
            if (state != PackageManager.PERMISSION_GRANTED) {
                Timber.d("Asking for POST_NOTIFICATIONS")
                notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        val activity: ComponentActivity = this

        // Anyone who had "Neon Refined" selected is migrated to Vitality Neon
        // — the shell it was a variant of — rather than left pointing at a
        // mode that no longer exists.
        settings.clearRetiredRefinedHomeFlag()

        setContent {
            // Settings actions, defined once for the single shell.
            val onRequestPermissions: () -> Unit = {
                Timber.d("Requesting HC permissions: %s", gateway.requiredPermissions)
                permissionLauncher.launch(gateway.requiredPermissions)
            }
            val onSyncNow: () -> Unit = {
                Timber.i("Manual sync triggered")
                // UX-P8: unique work, KEEP. A second tap while one is queued
                // or running is a no-op rather than a second overlapping
                // run; Settings observes this chain for its live state
                // instead of toasting "queued" blind.
                enqueueManualSync(ExistingWorkPolicy.KEEP)
            }
            val onSyncLogs: () -> Unit = {
                Timber.i("Manual log upload triggered")
                WorkManager.getInstance(applicationContext)
                    .enqueue(OneTimeWorkRequestBuilder<LogUploadWorker>().build())
            }
            val onBackfill: (Int) -> Unit = { days ->
                val newCheckpoint = System.currentTimeMillis() / 1000 - days * 24L * 3600L
                settings.lastSyncEpochSeconds = newCheckpoint
                // Record the request explicitly as well. Moving the
                // checkpoint alone is not enough: SyncWorker cannot tell a
                // deliberate backfill from a checkpoint that drifted after
                // an outage, and it clamps drift to a fortnight — so
                // "1 year" and "All (10y)" both silently read 14 days.
                settings.backfillFromEpochSeconds = newCheckpoint
                Timber.i("Backfill: requested T-%dd (epoch=%d), enqueueing sync", days, newCheckpoint)
                // APPEND_OR_REPLACE, not KEEP: a backfill must run AFTER any
                // sync already in flight (which would otherwise finish by
                // writing its own checkpoint over the one just set), and
                // must never be silently dropped because one was queued.
                enqueueManualSync(ExistingWorkPolicy.APPEND_OR_REPLACE)
            }
            val onOpenLogs: () -> Unit = { LogViewerActivity.start(activity) }
            val onClearBuffer: () -> Unit = {
                Timber.w("User cleared sync buffer")
                CoroutineScope(Dispatchers.IO).launch {
                    AppDatabase.get(applicationContext).buffered().clear()
                }
            }

            // APK update notification deep-link — works under either shell
            // (ApkDownloader.start needs no nav controller).
            val apkUrl = intent?.getStringExtra("apk_update_url")
            val apkName = intent?.getStringExtra("apk_update_name")
            LaunchedEffect(apkUrl, apkName) {
                if (!apkUrl.isNullOrEmpty() && !apkName.isNullOrEmpty()) {
                    app.myvitals.update.ApkDownloader.start(activity, apkUrl, apkName)
                    intent?.removeExtra("apk_update_url")
                    intent?.removeExtra("apk_update_name")
                    intent?.removeExtra("apk_update_tag")
                }
            }

            // SA-P3 — collect exercise routes, here, because here is the
            // only place it can be done.
            //
            // Health Connect refuses a route written by ANOTHER app to a
            // caller running in the background, whatever permission is
            // held: "When your app runs in the background and tries to
            // read an exercise route created by another app, Health
            // Connect returns an ExerciseRouteResult.ConsentRequired
            // response, even if your app has Always allow access to
            // exercise route data." Every exercise session on this install
            // is written by another app, so SyncWorker's 15-minute tick
            // can never be the thing that produces a map. Launching the
            // app can, and does — otherwise every walk would need its own
            // tap on its own detail screen forever.
            //
            // Three deliberate restraints, because a silent network+HC
            // pass on every launch is exactly the kind of thing that
            // becomes a battery complaint:
            //   - only when the grant is ALREADY held. This never prompts.
            //     Asking is the detail screen's job, on a tap, where the
            //     user can see what they are agreeing to.
            //   - throttled to once every ROUTE_BACKFILL_MIN_INTERVAL_S,
            //     so ten app switches in an afternoon is one pass.
            //   - a 14-day window, matching SyncWorker.MAX_LOOKBACK_DAYS
            //     rather than RouteBackfill's 30-day ceiling: this is the
            //     routine top-up, and the wider sweep belongs to a
            //     deliberate action.
            LaunchedEffect(Unit) {
                val now = System.currentTimeMillis() / 1000
                val due = now - settings.lastRouteBackfillEpochSeconds >=
                    ROUTE_BACKFILL_MIN_INTERVAL_S
                if (!due || !settings.isConfigured()) return@LaunchedEffect
                val granted = runCatching { gateway.hasRoutePermission() }
                    .getOrDefault(false)
                if (!granted) return@LaunchedEffect
                // Stamped BEFORE the run, not after: a pass that fails
                // should back off like one that succeeded, or a broken
                // backend turns into a read on every single launch.
                settings.lastRouteBackfillEpochSeconds = now
                val result = app.myvitals.health.RouteBackfill.run(
                    applicationContext, settings,
                    since = java.time.Instant.now()
                        .minusSeconds(ROUTE_BACKFILL_WINDOW_DAYS * 86_400L),
                )
                Timber.i(
                    "Route backfill on launch: %d session(s), %d track(s), " +
                        "%d withheld, %d with no route%s",
                    result.sessions, result.tracks, result.consentRequired,
                    result.noData, result.error?.let { " — $it" } ?: "",
                )
            }

            // ONE shell. The Classic / Vitality Neon choice is retired: both
            // rendered the same cards after the redesign, so the setting
            // chose between two navigations of the same app while costing a
            // second implementation of every screen it touched.
            run {
                NeonTheme {
                    NeonAppShell(
                        settings = settings,
                        gateway = gateway,
                        intent = intent,
                        isHealthConnectAvailable = gateway.isAvailable(),
                        hasPermissions = { gateway.hasAllPermissionsAsync() },
                        onRequestPermissions = onRequestPermissions,
                        onSyncNow = onSyncNow,
                        onSyncLogs = onSyncLogs,
                        onBackfill = onBackfill,
                        onOpenLogs = onOpenLogs,
                        onClearBuffer = onClearBuffer,
                    )
                }
                return@setContent
            }

            
        }
    }
}
