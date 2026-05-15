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
import java.time.Duration
import java.time.Instant

/** WIDGET-8 — most-recent BPM + relative time. */
class HrWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, HrWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_hr)
            val settings = SettingsRepository(ctx)
            val series = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        api.heartRateSeries(
                            since = Instant.now().minusSeconds(3 * 3600).toString(),
                        )
                    } catch (e: Exception) {
                        Timber.w(e, "hr widget fetch failed"); null
                    }
                }
            }
            val latest = series?.points?.lastOrNull()
            if (latest == null) {
                rv.setTextViewText(R.id.widget_value, "—")
                rv.setTextViewText(R.id.widget_label, "BPM")
                rv.setTextViewText(R.id.widget_sub, "no recent sample")
            } else {
                rv.setTextViewText(R.id.widget_value, "%.0f".format(latest.value))
                rv.setTextViewText(R.id.widget_label, "BPM")
                val ts = runCatching { Instant.parse(latest.time) }.getOrNull()
                val rel = if (ts == null) "—" else {
                    val mins = Duration.between(ts, Instant.now()).toMinutes()
                    when {
                        mins < 1 -> "just now"
                        mins < 60 -> "${mins}m ago"
                        mins < 1440 -> "${mins / 60}h ago"
                        else -> "${mins / 1440}d ago"
                    }
                }
                val avg = series.avg?.let { "  ·  avg ${it.toInt()}" } ?: ""
                rv.setTextViewText(R.id.widget_sub, "$rel$avg")
            }
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "vitals", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
