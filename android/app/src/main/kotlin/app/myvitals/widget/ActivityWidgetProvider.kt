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

/** WIDGET-7 — last activity (2×2): name, type, distance, duration, HR. */
class ActivityWidgetProvider : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) renderOne(ctx, mgr, id)
    }
    override fun onEnabled(context: Context) {
        WidgetsRefreshWorker.schedulePeriodicRefresh(context)
    }

    companion object {
        fun refreshAll(ctx: Context) {
            Widgets.refreshProvider(ctx, ActivityWidgetProvider::class.java) { id, mgr ->
                renderOne(ctx, mgr, id)
            }
        }

        private fun renderOne(ctx: Context, mgr: AppWidgetManager, id: Int) {
            val rv = RemoteViews(ctx.packageName, R.layout.widget_activity)
            val settings = SettingsRepository(ctx)
            val act = runBlocking {
                withTimeoutOrNull(4_000) {
                    if (!settings.isConfigured()) null else try {
                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                        api.activities(limit = 1).firstOrNull()
                    } catch (e: Exception) {
                        Timber.w(e, "activity widget fetch failed"); null
                    }
                }
            }
            if (act == null) {
                rv.setTextViewText(R.id.widget_title, "No activity")
                rv.setTextViewText(R.id.widget_type, "")
                rv.setTextViewText(R.id.widget_distance, "—")
                rv.setTextViewText(R.id.widget_duration, "—")
                rv.setTextViewText(R.id.widget_hr, "")
                rv.setTextViewText(R.id.widget_when, "")
            } else {
                rv.setTextViewText(R.id.widget_title, act.name ?: act.type)
                rv.setTextViewText(R.id.widget_type, act.type.uppercase())
                val miles = act.distanceM?.let { it / 1609.34 } ?: 0.0
                rv.setTextViewText(R.id.widget_distance, "%.1f mi".format(miles))
                val mins = act.durationS / 60
                val hrs = mins / 60
                rv.setTextViewText(R.id.widget_duration,
                    if (hrs > 0) "${hrs}h ${(mins % 60)}m" else "${mins}m")
                rv.setTextViewText(R.id.widget_hr,
                    act.avgHr?.let { "%.0f bpm avg".format(it) } ?: "")
                val ts = runCatching { Instant.parse(act.startAt) }.getOrNull()
                val rel = if (ts == null) "" else {
                    val mins = Duration.between(ts, Instant.now()).toMinutes()
                    when {
                        mins < 60 -> "${mins}m ago"
                        mins < 1440 -> "${mins / 60}h ago"
                        else -> "${mins / 1440}d ago"
                    }
                }
                rv.setTextViewText(R.id.widget_when, rel)
            }
            rv.setOnClickPendingIntent(
                R.id.widget_root, Widgets.openRoute(ctx, "activities", id),
            )
            mgr.updateAppWidget(id, rv)
        }
    }
}
