package app.myvitals.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import app.myvitals.MainActivity
import app.myvitals.fasting.FastingWidgetProvider

/**
 * Shared utilities for the home-screen widget family.
 *
 * Each widget is its own AppWidgetProvider + layout pair (so users can
 * pick exactly which ones to place on the launcher), but they share a
 * single 15-min WorkManager refresh (WidgetsRefreshWorker) and a small
 * set of helpers here for the tap-target plumbing and per-instance
 * iteration.
 *
 * The fasting widget pre-dates this family and continues to be
 * refreshed by its own worker — left alone to avoid touching shipped
 * behaviour.
 */
internal object Widgets {

    /** Build a tap-target PendingIntent that opens MainActivity at the
     *  given top-level route via the existing shortcut_route extra. */
    fun openRoute(context: Context, route: String, requestCode: Int): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            action = Intent.ACTION_VIEW
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra("shortcut_route", route)
        }
        return PendingIntent.getActivity(
            context, requestCode, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    /** Repaint every active instance of a widget provider. */
    fun refreshProvider(
        context: Context,
        cls: Class<*>,
        renderOne: (Int, AppWidgetManager) -> Unit,
    ) {
        val mgr = AppWidgetManager.getInstance(context)
        val ids = mgr.getAppWidgetIds(ComponentName(context, cls))
        for (id in ids) renderOne(id, mgr)
    }

    /** Repaint every widget across the family + the existing fasting widget. */
    fun refreshAll(context: Context) {
        FastingWidgetProvider.refreshAll(context)
        SoberWidgetProvider.refreshAll(context)
        StepsWidgetProvider.refreshAll(context)
        ReadinessWidgetProvider.refreshAll(context)
        WeightWidgetProvider.refreshAll(context)
        WorkoutWidgetProvider.refreshAll(context)
        SleepWidgetProvider.refreshAll(context)
        ActivityWidgetProvider.refreshAll(context)
        HrWidgetProvider.refreshAll(context)
    }
}
