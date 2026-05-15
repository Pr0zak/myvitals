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

/** WIDGET-1 — current sober streak. */
class SoberWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }

    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, SoberWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_sober)
            val settings = SettingsRepository(ctx)
            val state = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        api.soberCurrent()
                    } catch (e: Exception) {
                        Timber.w(e, "sober widget fetch failed"); null
                    }
                }
            }
            if (state?.active != null) {
                val days = state.days ?: 0
                rv.setTextViewText(R.id.widget_value, "$days")
                rv.setTextViewText(R.id.widget_unit, if (days == 1) "day" else "days")
                val hrs = state.hours ?: 0
                rv.setTextViewText(R.id.widget_sub,
                    if (hrs > 0) "+${hrs}h sober" else "sober")
            } else {
                rv.setTextViewText(R.id.widget_value, "—")
                rv.setTextViewText(R.id.widget_unit, "days")
                rv.setTextViewText(R.id.widget_sub, "no streak")
            }
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "sober", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
