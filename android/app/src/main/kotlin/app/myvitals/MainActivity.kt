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
import androidx.compose.material.icons.filled.FitnessCenter
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
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
import app.myvitals.ui.MyVitalsTheme
import app.myvitals.ui.SettingsScreen
import app.myvitals.ui.SoberHomeScreen
import app.myvitals.ui.strength.StrengthHistoryScreen
import app.myvitals.ui.strength.StrengthTodayScreen
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import timber.log.Timber

private object Routes {
    const val SOBER = "sober"
    const val WORKOUT = "workout/today"
    const val WORKOUT_HISTORY = "workout/history"
    const val SETTINGS = "settings"
}

class MainActivity : ComponentActivity() {
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

        setContent {
            MyVitalsTheme {
                val nav = rememberNavController()
                Scaffold(
                    bottomBar = { BottomBar(nav) },
                    containerColor = MV.Bg,
                ) { padding ->
                    NavHost(
                        navController = nav,
                        startDestination = Routes.SOBER,
                        modifier = Modifier.fillMaxSize().padding(padding),
                    ) {
                        composable(Routes.SOBER) {
                            SoberHomeScreen(
                                settings = settings,
                                onOpenSettings = { nav.navigateTab(Routes.SETTINGS) },
                            )
                        }
                        composable(Routes.WORKOUT) {
                            StrengthTodayScreen(
                                settings = settings,
                                onOpenHistory = { nav.navigate(Routes.WORKOUT_HISTORY) },
                            )
                        }
                        composable(Routes.WORKOUT_HISTORY) {
                            StrengthHistoryScreen(
                                settings = settings,
                                onBack = { nav.popBackStack() },
                            )
                        }
                        composable(Routes.SETTINGS) {
                            SettingsScreen(
                                settings = settings,
                                isHealthConnectAvailable = gateway.isAvailable(),
                                hasPermissions = { gateway.hasAllPermissions() },
                                onRequestPermissions = {
                                    Timber.d("Requesting HC permissions: %s", gateway.requiredPermissions)
                                    permissionLauncher.launch(gateway.requiredPermissions)
                                },
                                onSyncNow = {
                                    Timber.i("Manual sync triggered")
                                    WorkManager.getInstance(applicationContext)
                                        .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
                                },
                                onSyncLogs = {
                                    Timber.i("Manual log upload triggered")
                                    WorkManager.getInstance(applicationContext)
                                        .enqueue(OneTimeWorkRequestBuilder<LogUploadWorker>().build())
                                },
                                onBackfill = { days ->
                                    val newCheckpoint = System.currentTimeMillis() / 1000 - days * 24L * 3600L
                                    settings.lastSyncEpochSeconds = newCheckpoint
                                    Timber.i("Backfill: reset checkpoint to T-%dd (epoch=%d), enqueueing sync", days, newCheckpoint)
                                    WorkManager.getInstance(applicationContext)
                                        .enqueue(OneTimeWorkRequestBuilder<SyncWorker>().build())
                                },
                                onOpenLogs = { LogViewerActivity.start(activity) },
                                onClearBuffer = {
                                    Timber.w("User cleared sync buffer")
                                    CoroutineScope(Dispatchers.IO).launch {
                                        AppDatabase.get(applicationContext).buffered().clear()
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
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
        Item(current, Routes.SOBER, "Sober", Icons.Filled.Refresh) { nav.navigateTab(Routes.SOBER) }
        Item(current, Routes.WORKOUT, "Workout", Icons.Filled.FitnessCenter,
            highlightAlsoFor = setOf(Routes.WORKOUT_HISTORY)) { nav.navigateTab(Routes.WORKOUT) }
        Item(current, Routes.SETTINGS, "Settings", Icons.Filled.Settings) { nav.navigateTab(Routes.SETTINGS) }
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
