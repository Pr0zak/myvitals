package app.myvitals.widget

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.widget.RemoteViews
import app.myvitals.R
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import timber.log.Timber

/** WIDGET-4 — active weight goal progress (current / target + bar). */
class WeightWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, WeightWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_weight)
            val settings = SettingsRepository(ctx)
            val goal = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        api.aiGoals().firstOrNull { it.kind == "weight" && it.endedAt == null }
                    } catch (e: Exception) {
                        Timber.w(e, "weight widget fetch failed"); null
                    }
                }
            }
            if (goal == null) {
                rv.setTextViewText(R.id.widget_value, "—")
                rv.setTextViewText(R.id.widget_unit, "")
                rv.setTextViewText(R.id.widget_sub, "no weight goal")
                rv.setProgressBar(R.id.widget_progress, 100, 0, false)
            } else {
                val cur = goal.currentValue
                val target = goal.targetValue
                val unit = goal.targetUnit ?: ""
                rv.setTextViewText(R.id.widget_value,
                    cur?.let { "%.1f".format(it) } ?: "—")
                rv.setTextViewText(R.id.widget_unit, "kg")
                rv.setTextViewText(R.id.widget_sub,
                    target?.let { "target %s %s  ·  %d%%".format(
                        it.toString(), unit,
                        (goal.progressPct ?: 0.0).toInt(),
                    ) } ?: "no target")
                rv.setProgressBar(R.id.widget_progress, 100,
                    (goal.progressPct ?: 0.0).toInt().coerceIn(0, 100), false)
            }
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "vitals", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
