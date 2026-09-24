package app.myvitals.snapshots

import app.myvitals.sync.HrByActivity
import app.myvitals.sync.HrByTypeRow
import app.myvitals.sync.WeightBin
import app.myvitals.sync.WeightHistogram
import app.myvitals.sync.WeightSeriesOut
import app.myvitals.sync.WindowChange
import app.myvitals.snapshots.SampleDataDetail as D

/**
 * UI-F1 — invented data for the detail-screen extras (resting HR vs the
 * previous window, HR by activity type, the weight distribution and days at
 * min). Layered on UI-4's SampleDataDetail; never real readings.
 */
object SampleDataUiF1 {
    /** Resting HR went UP a little vs the previous 30 days: amber, not rose. */
    val restingStats = D.restingStats.copy(
        vsPrevious = WindowChange(
            avgNow = 58.6, avgBefore = 56.9, delta = 1.7, better = "down", tone = "caution",
            daysNow = 30, daysBefore = 28,
        ),
    )

    val hrByActivity = HrByActivity(
        types = listOf(
            HrByTypeRow("run", "Run", n = 4, avgBpm = 152),
            HrByTypeRow("ride", "Ride", n = 9, avgBpm = 134),
            HrByTypeRow("row", "Row", n = 3, avgBpm = 128),
            HrByTypeRow("walk", "Walk", n = 6, avgBpm = 101),
        ),
        sparse = listOf(HrByTypeRow("hike", "Hike", n = 1)),
        minN = 2,
    )

    val weight: WeightSeriesOut = D.weight.copy(
        stats = D.weight.stats!!.copy(
            histogram = WeightHistogram(
                binKg = 0.5,
                bins = listOf(
                    WeightBin(82.0, 82.5, 2), WeightBin(82.5, 83.0, 3), WeightBin(83.0, 83.5, 5),
                    WeightBin(83.5, 84.0, 4), WeightBin(84.0, 84.5, 1),
                ),
            ),
            daysAtMin = 2,
        ),
    )
}
