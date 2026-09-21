package app.myvitals

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.automirrored.outlined.DirectionsBike
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Terrain
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import app.myvitals.ui.neon.NeonAppShell
import app.myvitals.ui.neon.NeonTheme
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.data.AppDatabase
import app.myvitals.data.SettingsRepository
import app.myvitals.debug.LogUploadWorker
import app.myvitals.debug.LogViewerActivity
import app.myvitals.health.HealthConnectGateway
import app.myvitals.sync.SyncWorker
import app.myvitals.ui.MV
import app.myvitals.ui.JournalScreen
import app.myvitals.ui.SettingsScreen
import app.myvitals.ui.SoberHomeScreen
import app.myvitals.ui.strength.StrengthCatalogScreen
import app.myvitals.ui.strength.StrengthHistoryScreen
import app.myvitals.ui.strength.StrengthTodayScreen
import app.myvitals.ui.strength.StrengthEquipmentScreen
import app.myvitals.ui.strength.StrengthTrainingPrefsScreen
import app.myvitals.ui.trails.TrailsScreen
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import timber.log.Timber

private object Routes {
    const val VITALS = "vitals"
    const val VITAL_DETAIL = "vitals/{key}"
    fun vitalDetail(key: String) = "vitals/$key"
    const val SOBER = "sober"
    const val FASTING = "fasting"
    const val COACH = "coach"
    const val JOURNAL = "journal"
    const val WORKOUT = "workout/today"
    const val WORKOUT_HISTORY = "workout/history"
    const val WORKOUT_DAY = "workout/day/{date}"
    fun workoutDay(date: String) = "workout/day/$date"
    const val WORKOUT_CHARTS = "workout/charts"
    const val WORKOUT_CATALOG = "workout/catalog"
    const val WORKOUT_EQUIPMENT = "workout/equipment"
    const val WORKOUT_TRAINING_PREFS = "workout/training-prefs"
    const val ACTIVITIES = "activities"
    const val ACTIVITY_MAP = "activities/map"
    const val ACTIVITY_DETAIL = "activity/{source}/{sourceId}"
    fun activityDetail(source: String, sourceId: String) = "activity/$source/$sourceId"
    const val TRAILS = "trails"
    const val TRAIL_VISITS = "trails/{trailId}/visits"
    fun trailVisits(trailId: Long) = "trails/$trailId/visits"
    const val SETTINGS = "settings"
}

/** SA-P3 — how often the on-launch route backfill may actually run.
 *  Six hours: routes only appear when a session is recorded, and nobody
 *  records more than a handful a day. */
private const val ROUTE_BACKFILL_MIN_INTERVAL_S = 6L * 3600L

/** Matches SyncWorker.MAX_LOOKBACK_DAYS. Anything older is the job of a
 *  deliberate fetch from the activity's own Route card. */
private const val ROUTE_BACKFILL_WINDOW_DAYS = 14L

class MainActivity : ComponentActivity() {
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
                WorkManager.getInstance(applicationContext)
                    .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
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
                WorkManager.getInstance(applicationContext)
                    .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
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
                WorkManager.getInstance(applicationContext)
                    .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
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

/** Top-level tab routes, ordered to match the bottom-bar layout. */
private val TOP_TABS = listOf(
    Routes.VITALS, Routes.WORKOUT, Routes.ACTIVITIES, Routes.TRAILS, Routes.SETTINGS,
)

/**
 * Listen for horizontal flicks across the screen and navigate to the
 * adjacent top-level tab. Only fires while the user is *on* a top-level
 * tab — deep-link screens (workout history, catalog, etc.) keep their
 * own back-swipe behaviour.
 */
@androidx.compose.runtime.Composable
private fun Modifier.swipeBetweenTopTabs(nav: NavHostController): Modifier {
    val backStack by nav.currentBackStackEntryAsState()
    val current = backStack?.destination?.route
    val idx = TOP_TABS.indexOf(current)
    if (idx < 0) return this   // Not on a top-level tab — no-op
    val threshold = with(androidx.compose.ui.platform.LocalDensity.current) { 80.dp.toPx() }
    return this.pointerInput(current) {
        var totalDx = 0f
        detectHorizontalDragGestures(
            onDragStart = { totalDx = 0f },
            onHorizontalDrag = { _, dx -> totalDx += dx },
            onDragEnd = {
                if (totalDx <= -threshold && idx < TOP_TABS.lastIndex) {
                    nav.navigateTab(TOP_TABS[idx + 1])
                } else if (totalDx >= threshold && idx > 0) {
                    nav.navigateTab(TOP_TABS[idx - 1])
                }
            },
            onDragCancel = {},
        )
    }
}

private fun NavHostController.navigateTab(route: String) {
    navigate(route) {
        popUpTo(graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@androidx.compose.runtime.Composable
private fun BottomBar(nav: NavHostController) {
    val backStack by nav.currentBackStackEntryAsState()
    val current = backStack?.destination?.route ?: Routes.SOBER
    NavigationBar(containerColor = MV.SurfaceContainerLow) {
        Item(current, Routes.VITALS, "Vitals", Icons.Outlined.MonitorHeart,
            highlightAlsoFor = setOf(Routes.SOBER, Routes.VITAL_DETAIL)) {
            nav.navigateTab(Routes.VITALS)
        }
        Item(current, Routes.WORKOUT, "Workout", Icons.Outlined.FitnessCenter,
            highlightAlsoFor = setOf(
                Routes.WORKOUT_HISTORY,
                Routes.WORKOUT_CATALOG,
                Routes.WORKOUT_TRAINING_PREFS,
            )) { nav.navigateTab(Routes.WORKOUT) }
        Item(current, Routes.ACTIVITIES, "Activities", Icons.AutoMirrored.Outlined.DirectionsBike,
            highlightAlsoFor = setOf(Routes.ACTIVITY_DETAIL)) {
            nav.navigateTab(Routes.ACTIVITIES)
        }
        Item(current, Routes.TRAILS, "Trails", Icons.Outlined.Terrain) { nav.navigateTab(Routes.TRAILS) }
        Item(current, Routes.SETTINGS, "Settings", Icons.Outlined.Settings) { nav.navigateTab(Routes.SETTINGS) }
    }
}

@androidx.compose.runtime.Composable
private fun androidx.compose.foundation.layout.RowScope.Item(
    current: String, route: String, label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    highlightAlsoFor: Set<String> = emptySet(),
    onClick: () -> Unit,
) {
    NavigationBarItem(
        selected = current == route || current in highlightAlsoFor,
        onClick = onClick,
        icon = { Icon(icon, contentDescription = label) },
        label = { Text(label) },
        colors = NavigationBarItemDefaults.colors(
            selectedIconColor = MV.OnSurface,
            selectedTextColor = MV.OnSurface,
            unselectedIconColor = MV.OnSurfaceVariant,
            unselectedTextColor = MV.OnSurfaceVariant,
            indicatorColor = MV.BrandRed.copy(alpha = 0.3f),
        ),
    )
}
