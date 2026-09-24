package app.myvitals.snapshots

import app.myvitals.sync.ActivityRecord
import app.myvitals.sync.ActivityRecordRef
import app.myvitals.sync.ActivityRecordsOut
import app.myvitals.sync.ActivityStatsOut
import app.myvitals.sync.YtdMonth

/**
 * Invented sample data for the UI-F2 screenshots (period stats row,
 * personal-records card, month headers) on top of [SampleDataUi5]. Public
 * repo: every name and number is made up. The records point at the UI-5
 * sample rows so a tile names an activity that is in the feed below it;
 * `highest_suffer` is null to show a record nothing qualifies for is left
 * out, not printed as 0.
 */
object SampleDataUiF2 {
    val stats = ActivityStatsOut(
        periodLabel = "Since Jun 27",
        nActivities = 41,
        totalDistanceM = 612_400.0,
        totalDurationS = 131_400,
        totalElevationM = 5_820.0,
        totalKcal = 0.0,
        nStrength = 12,
        nWithDistance = 27,
        nWithElevation = 19,
        // Nothing in the window carried kcal: the tile must read "—".
        nWithKcal = 0,
        windowSince = "2026-06-27",
        category = "all",
    )

    private fun ref(id: String, name: String, type: String, date: String) =
        ActivityRecordRef(source = "strava", sourceId = id, name = name, type = type,
            startAt = "${date}T12:00:00Z", date = date)

    val records = ActivityRecordsOut(
        category = "all",
        nConsidered = 29,
        records = listOf(
            ActivityRecord("longest_distance", "Longest distance", "m", 32_400.0,
                ref("a1", "Lakeside loop", "Ride", "2026-09-23")),
            ActivityRecord("longest_duration", "Longest time", "s", 7200.0,
                ref("a5", "Bluff trail", "Hike", "2026-09-13")),
            ActivityRecord("most_elevation", "Most climbing", "m", 480.0,
                ref("a4", "Ridge singletrack", "MountainBikeRide", "2026-09-19")),
            ActivityRecord("highest_suffer", "Highest suffer score", "", null, null),
        ),
    )

    val ytd = SampleDataUi5.ytd.copy(
        months = listOf(
            YtdMonth("2026-09-01", sessions = 9, durationS = 36_960),
            YtdMonth("2026-08-01", sessions = 14, durationS = 51_300),
        ),
    )
}
