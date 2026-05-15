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

/** WIDGET-6 — last night sleep duration + stage breakdown teaser. */
class SleepWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, SleepWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_sleep)
            val settings = SettingsRepository(ctx)
            val night = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        val r = api.sleepLast()
                        if (r.isSuccessful) r.body() else null
                    } catch (e: Exception) {
                        Timber.w(e, "sleep widget fetch failed"); null
                    }
                }
            }
            if (night == null) {
                rv.setTextViewText(R.id.widget_value, "—h")
                rv.setTextViewText(R.id.widget_label, "SLEEP")
                rv.setTextViewText(R.id.widget_sub, "no data")
            } else {
                val totalS = night.totalS
                val h = totalS / 3600
                val m = (totalS % 3600) / 60
                rv.setTextViewText(R.id.widget_value, "${h}h ${m.toString().padStart(2, '0')}m")
                rv.setTextViewText(R.id.widget_label, "SLEEP")
                // Compute deep + rem totals for the subtitle teaser.
                val deepS = night.stages.firstOrNull { it.stage == "deep" }?.durationS ?: 0
                val remS = night.stages.firstOrNull { it.stage == "rem" }?.durationS ?: 0
                rv.setTextViewText(R.id.widget_sub,
                    "deep ${(deepS / 60)}m · rem ${(remS / 60)}m")
            }
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "vitals", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
