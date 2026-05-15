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

/** WIDGET-5 — today's workout: split focus + status. */
class WorkoutWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, WorkoutWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_workout)
            val settings = SettingsRepository(ctx)
            val today = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        val r = api.strengthToday()
                        if (r.isSuccessful) r.body() else null
                    } catch (e: Exception) {
                        Timber.w(e, "workout widget fetch failed"); null
                    }
                }
            }
            val focus = today?.splitFocus
                ?.replace("_", " ")?.replaceFirstChar { it.titlecase() }
                ?: "—"
            val status = today?.status
            val statusLabel = when (status) {
                "completed" -> "complete"
                "in_progress" -> "in progress"
                "skipped" -> "skipped"
                "rest" -> "rest day"
                null -> "no plan"
                else -> status
            }
            rv.setTextViewText(R.id.widget_value, focus)
            rv.setTextViewText(R.id.widget_label, "WORKOUT")
            rv.setTextViewText(R.id.widget_sub, statusLabel.uppercase())
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "workout/today", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
