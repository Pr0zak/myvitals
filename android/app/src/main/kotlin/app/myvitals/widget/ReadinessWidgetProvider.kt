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

/** WIDGET-3 — today readiness + short verdict tone. */
class ReadinessWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, ReadinessWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_readiness)
            val settings = SettingsRepository(ctx)
            val today = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        api.summaryToday()
                    } catch (e: Exception) {
                        Timber.w(e, "readiness widget fetch failed"); null
                    }
                }
            }
            val score = today?.readinessScore
            val recovery = today?.recoveryScore
            rv.setTextViewText(R.id.widget_value,
                score?.toInt()?.toString() ?: "—")
            val tone = when {
                score == null -> "no data"
                score >= 80 -> "ready"
                score >= 60 -> "moderate"
                score >= 40 -> "low"
                else -> "recover"
            }
            rv.setTextViewText(R.id.widget_label, "READINESS")
            rv.setTextViewText(R.id.widget_sub, tone +
                (recovery?.let { "  ·  recovery ${it.toInt()}" } ?: ""))
            rv.setProgressBar(R.id.widget_progress, 100,
                score?.toInt()?.coerceIn(0, 100) ?: 0, false)
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "vitals", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
