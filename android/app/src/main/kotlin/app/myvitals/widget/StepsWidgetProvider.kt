package app.myvitals.widget

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.widget.RemoteViews
import app.myvitals.R
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import timber.log.Timber

/** WIDGET-2 — today steps + progress against the user's daily goal. */
class StepsWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, StepsWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_steps)
            val settings = SettingsRepository(ctx)
            val r = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        coroutineScope {
                            val today = async { api.summaryToday() }
                            val prof = async { runCatching { api.profile() }.getOrNull() }
                            today.await() to prof.await()
                        }
                    } catch (e: Exception) {
                        Timber.w(e, "steps widget fetch failed"); null
                    }
                }
            }
            val today = r?.first
            val profile = r?.second
            val steps = today?.stepsTotal ?: 0
            val goal = profile?.stepsGoal() ?: 10_000
            val pct = if (goal > 0) ((steps.toDouble() / goal) * 100.0).coerceIn(0.0, 100.0).toInt() else 0
            rv.setTextViewText(R.id.widget_value, "%,d".format(steps))
            rv.setTextViewText(R.id.widget_sub, "of %,d  ·  $pct%".format(goal))
            rv.setProgressBar(R.id.widget_progress, 100, pct, false)
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "vitals", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
