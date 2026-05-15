package app.myvitals.fasting

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import app.myvitals.MainActivity
import app.myvitals.R
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FastingSession
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import timber.log.Timber
import java.time.Duration
import java.time.Instant
import java.util.concurrent.TimeUnit

/**
 * 2×1 home-screen widget for the active fast. RemoteViews-only — no
 * custom view classes, no Glance dep. Periodic refresh is driven by
 * a WorkManager job (FastingWidgetUpdateWorker) so the 15-min cadence
 * is below the system's 30-min `updatePeriodMillis` floor.
 *
 * Tap → opens MainActivity with shortcut_route=fasting.
 */
class FastingWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(
        context: Context, manager: AppWidgetManager, ids: IntArray,
    ) {
        for (id in ids) updateOne(context, manager, id)
    }

    override fun onEnabled(context: Context) {
        schedulePeriodicRefresh(context)
    }

    override fun onDisabled(context: Context) {
        WorkManager.getInstance(context).cancelUniqueWork(UNIQUE_REFRESH)
    }

    companion object {
        const val UNIQUE_REFRESH = "fasting_widget_refresh"
        const val ACTION_REFRESH = "app.myvitals.fasting.WIDGET_REFRESH"

        fun schedulePeriodicRefresh(context: Context) {
            val req = PeriodicWorkRequestBuilder<FastingWidgetUpdateWorker>(
                15, TimeUnit.MINUTES,
            ).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                UNIQUE_REFRESH, ExistingPeriodicWorkPolicy.KEEP, req,
            )
        }

        /** Repaint every active widget instance. Called from the worker
         * + from app code that wants an immediate refresh (start / end
         * a fast). */
        fun refreshAll(context: Context) {
            val mgr = AppWidgetManager.getInstance(context)
            val comp = ComponentName(context, FastingWidgetProvider::class.java)
            val ids = mgr.getAppWidgetIds(comp)
            for (id in ids) updateOne(context, mgr, id)
        }

        private fun updateOne(context: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(context.packageName, R.layout.widget_fasting)

            val settings = SettingsRepository(context)
            val state = runBlocking {
                withTimeoutOrNull(4_000) { fetchCurrent(settings) }
            }
            when {
                state == null -> {
                    rv.setTextViewText(R.id.widget_elapsed, "—h —m")
                    rv.setTextViewText(R.id.widget_stage, "NO ACTIVE FAST")
                    rv.setTextViewText(R.id.widget_pct, "")
                    rv.setProgressBar(R.id.widget_progress, 100, 0, false)
                }
                else -> {
                    val startMs = runCatching { Instant.parse(state.startedAt).toEpochMilli() }
                        .getOrDefault(System.currentTimeMillis())
                    val elapsedS = Duration.between(
                        Instant.ofEpochMilli(startMs), Instant.now(),
                    ).seconds.coerceAtLeast(0)
                    val targetH = state.targetHours ?: 16.0
                    val elapsedH = elapsedS / 3600.0
                    val pct = ((elapsedH / targetH) * 100.0).coerceIn(0.0, 100.0).toInt()
                    val wh = (elapsedS / 3600).toInt()
                    val wm = ((elapsedS % 3600) / 60).toInt()
                    rv.setTextViewText(R.id.widget_elapsed,
                        "${wh}h ${wm.toString().padStart(2, '0')}m")
                    val stage = state.currentStage.replace("_", " ").uppercase()
                    rv.setTextViewText(R.id.widget_stage, stage)
                    rv.setTextViewText(R.id.widget_pct, "$pct% of ${targetH.toInt()}h")
                    rv.setProgressBar(R.id.widget_progress, 100, pct, false)
                }
            }

            // Tap target — opens MainActivity at the fasting route.
            val intent = Intent(context, MainActivity::class.java).apply {
                action = Intent.ACTION_VIEW
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                putExtra("shortcut_route", "fasting")
            }
            val pi = PendingIntent.getActivity(
                context, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            rv.setOnClickPendingIntent(R.id.widget_root, pi)

            mgr.updateAppWidget(id, rv)
        }

        private suspend fun fetchCurrent(settings: SettingsRepository): FastingSession? {
            if (!settings.isConfigured()) return null
            return try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val resp = api.fastingCurrent()
                if (resp.isSuccessful) resp.body() else null
            } catch (e: Exception) {
                Timber.w(e, "widget fetch failed")
                null
            }
        }
    }
}
