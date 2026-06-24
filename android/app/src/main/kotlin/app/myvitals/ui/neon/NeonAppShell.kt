package app.myvitals.ui.neon

import android.content.Intent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Adjust
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.MonitorHeart
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Terrain
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.myvitals.data.SettingsRepository
import app.myvitals.health.HealthConnectGateway

/**
 * Vitality Neon shell — the phone mirror of the web 6-tab redesign. Renders
 * ALONGSIDE the classic 5-tab Scaffold; MainActivity branches on the Settings
 * "Vitality Neon" toggle. The classic shell is left untouched.
 *
 * Top tabs (Today / Body / Train / Trails / You) drill into the SAME
 * existing detail screens the classic shell uses, so there's no second copy of
 * any detail screen — only a new front door + consolidated home screens.
 */

/** Neon top-level routes. */
object NeonRoutes {
    const val TODAY = "neon/today"
    const val BODY = "neon/body"
    const val TRAIN = "neon/train"
    const val TRAILS = "neon/trails"
    const val YOU = "neon/you"
}

private data class NeonTab(
    val route: String,
    val label: String,
    val color: Color,
    val icon: ImageVector,
    /** Stay lit while anywhere in this tab's domain (drilled into a detail). */
    val domain: (String?) -> Boolean,
)

private val NEON_TABS = listOf(
    NeonTab(NeonRoutes.TODAY, "Today", NeonMV.Lime, Icons.Outlined.Adjust) { it == NeonRoutes.TODAY },
    NeonTab(NeonRoutes.BODY, "Body", NeonMV.Cyan, Icons.Outlined.MonitorHeart) {
        it == NeonRoutes.BODY || it?.startsWith("vitals/") == true
    },
    NeonTab(NeonRoutes.TRAIN, "Train", NeonMV.Lime, Icons.Outlined.FitnessCenter) {
        it == NeonRoutes.TRAIN || it?.startsWith("workout/") == true ||
            it == "activities" || it?.startsWith("activity/") == true
    },
    NeonTab(NeonRoutes.TRAILS, "Trails", NeonMV.Amber, Icons.Outlined.Terrain) {
        it == NeonRoutes.TRAILS
    },
    NeonTab(NeonRoutes.YOU, "You", NeonMV.Cyan, Icons.Outlined.Person) {
        it == NeonRoutes.YOU || it in setOf("settings", "sober", "fasting", "journal")
    },
)

@Composable
fun NeonAppShell(
    settings: SettingsRepository,
    gateway: HealthConnectGateway,
    intent: Intent?,
    isHealthConnectAvailable: Boolean,
    hasPermissions: suspend () -> Boolean,
    onRequestPermissions: () -> Unit,
    onSyncNow: () -> Unit,
    onSyncLogs: () -> Unit,
    onBackfill: (Int) -> Unit,
    onOpenLogs: () -> Unit,
    onClearBuffer: () -> Unit,
    neonShellEnabled: Boolean,
    onToggleNeonShell: (Boolean) -> Unit,
) {
    val nav = rememberNavController()

    // Static app-shortcut deep-link (res/xml/shortcuts.xml). Map the classic
    // shortcut routes onto the neon shell's equivalents.
    val routeFromShortcut = intent?.getStringExtra("shortcut_route")
    LaunchedEffect(routeFromShortcut) {
        when (routeFromShortcut) {
            "workout/today" -> nav.navigate("workout/today")
            "trails" -> nav.navigateTopTab(NeonRoutes.TRAILS)
            "vitals" -> nav.navigateTopTab(NeonRoutes.BODY)
            "activities" -> nav.navigate("activities")
            "settings" -> nav.navigate("settings")
            "sober" -> nav.navigate("sober")
            "fasting" -> nav.navigate("fasting")
            "journal" -> nav.navigate("journal")
        }
        if (!routeFromShortcut.isNullOrEmpty()) intent?.removeExtra("shortcut_route")
    }

    Scaffold(
        bottomBar = { NeonBottomBar(nav) },
        containerColor = NeonMV.Bg,
    ) { inner ->
        Column(modifier = Modifier.fillMaxSize().padding(inner)) {
            app.myvitals.ui.common.ConnectionBanner()
            val open: (String) -> Unit = { route -> nav.navigate(route) }
            val pad = PaddingValues(0.dp)
            NavHost(
                navController = nav,
                startDestination = NeonRoutes.TODAY,
                modifier = Modifier.fillMaxSize().weight(1f),
            ) {
                // ---- Neon top-level home screens ----
                composable(NeonRoutes.TODAY) { RingsScreen(settings, pad, open) }
                composable(NeonRoutes.BODY) { BodyScreen(settings, pad, open) }
                composable(NeonRoutes.TRAIN) { TrainHubScreen(settings, pad, open) }
                // The Trails tab IS the full Trails screen — map button,
                // recency sort within status groups, and per-trail inline map
                // drill-down. (Replaced the old NeonTrailsScreen status board,
                // which had no map button, sorted by status not recency, and
                // pushed a SECOND full trails list on tap.)
                composable(NeonRoutes.TRAILS) {
                    app.myvitals.ui.trails.TrailsScreen(settings = settings)
                }
                composable(NeonRoutes.YOU) { YouScreen(settings, pad, open) }

                // ---- Existing detail screens, reused as drill-downs ----
                composable(
                    "vitals/{key}",
                    arguments = listOf(navArgument("key") { type = NavType.StringType }),
                ) { entry ->
                    val key = entry.arguments?.getString("key") ?: "HR"
                    val vital = runCatching { app.myvitals.ui.vitals.Vital.valueOf(key) }
                        .getOrDefault(app.myvitals.ui.vitals.Vital.HR)
                    app.myvitals.ui.vitals.VitalsDetailScreen(
                        settings = settings, vital = vital, onBack = { nav.popBackStack() },
                    )
                }
                composable("sober") {
                    app.myvitals.ui.SoberHomeScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("fasting") {
                    app.myvitals.ui.FastingScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("coach") {
                    app.myvitals.ui.CoachScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("journal") {
                    app.myvitals.ui.JournalScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("workout/today") {
                    app.myvitals.ui.strength.StrengthTodayScreen(
                        settings = settings,
                        onOpenHistory = { nav.navigate("workout/history") },
                        onOpenCatalog = { nav.navigate("workout/catalog") },
                        onOpenTrainingPrefs = { nav.navigate("workout/training-prefs") },
                        onOpenEquipment = { nav.navigate("workout/equipment") },
                        onOpenCoach = { nav.navigate("coach") },
                        onOpenDay = { date -> nav.navigate("workout/day/$date") },
                        onOpenCharts = { nav.navigate("workout/charts") },
                    )
                }
                composable("workout/history") {
                    app.myvitals.ui.strength.StrengthHistoryScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("workout/charts") {
                    app.myvitals.ui.strength.WorkoutChartsScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable(
                    "workout/day/{date}",
                    arguments = listOf(navArgument("date") { type = NavType.StringType }),
                ) { entry ->
                    app.myvitals.ui.strength.StrengthDayViewScreen(
                        settings = settings,
                        dateIso = entry.arguments?.getString("date") ?: "",
                        onBack = { nav.popBackStack() },
                    )
                }
                composable("workout/catalog") {
                    app.myvitals.ui.strength.StrengthCatalogScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("workout/training-prefs") {
                    app.myvitals.ui.strength.StrengthTrainingPrefsScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("workout/equipment") {
                    app.myvitals.ui.strength.StrengthEquipmentScreen(settings = settings, onBack = { nav.popBackStack() })
                }
                composable("activities") {
                    app.myvitals.ui.activities.ActivitiesScreen(
                        settings = settings,
                        onOpenActivity = { source, sourceId -> nav.navigate("activity/$source/$sourceId") },
                        onOpenStrengthDay = { date -> nav.navigate("workout/day/$date") },
                    )
                }
                composable(
                    "activity/{source}/{sourceId}",
                    arguments = listOf(
                        navArgument("source") { type = NavType.StringType },
                        navArgument("sourceId") { type = NavType.StringType },
                    ),
                ) { entry ->
                    app.myvitals.ui.activities.ActivityDetailScreen(
                        settings = settings,
                        source = entry.arguments?.getString("source") ?: "",
                        sourceId = entry.arguments?.getString("sourceId") ?: "",
                        onBack = { nav.popBackStack() },
                    )
                }
                composable("settings") {
                    app.myvitals.ui.SettingsScreen(
                        settings = settings,
                        isHealthConnectAvailable = isHealthConnectAvailable,
                        hasPermissions = hasPermissions,
                        onRequestPermissions = onRequestPermissions,
                        onSyncNow = onSyncNow,
                        onSyncLogs = onSyncLogs,
                        onBackfill = onBackfill,
                        onOpenLogs = onOpenLogs,
                        onClearBuffer = onClearBuffer,
                        neonShellEnabled = neonShellEnabled,
                        onToggleNeonShell = onToggleNeonShell,
                    )
                }
            }
        }
    }
}

@Composable
private fun NeonBottomBar(nav: NavHostController) {
    val backStack by nav.currentBackStackEntryAsState()
    val current = backStack?.destination?.route
    NavigationBar(containerColor = Color(0xFF14161E)) {
        NEON_TABS.forEach { tab ->
            val selected = tab.domain(current)
            NavigationBarItem(
                selected = selected,
                onClick = { nav.navigateTopTab(tab.route) },
                icon = { Icon(tab.icon, contentDescription = tab.label) },
                label = { Text(tab.label) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = tab.color,
                    selectedTextColor = tab.color,
                    unselectedIconColor = NeonMV.Muted,
                    unselectedTextColor = NeonMV.Muted,
                    indicatorColor = tab.color.copy(alpha = 0.16f),
                ),
            )
        }
    }
}

/** Tab navigation with state save/restore, mirroring the classic shell. */
private fun NavHostController.navigateTopTab(route: String) {
    navigate(route) {
        popUpTo(graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
