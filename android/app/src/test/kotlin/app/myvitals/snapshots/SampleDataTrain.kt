package app.myvitals.snapshots

import app.myvitals.sync.ActivityRow
import app.myvitals.sync.ActivityStatsOut
import app.myvitals.sync.MuscleVolumeResponse
import app.myvitals.sync.MuscleVolumeRow
import app.myvitals.sync.StrengthDailyVolume
import app.myvitals.sync.StrengthNextUp
import app.myvitals.sync.StrengthStats
import app.myvitals.sync.StrengthWeekDay
import app.myvitals.sync.StrengthWeekVolume
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.sync.TrainingConsistency
import app.myvitals.sync.UpcomingDay
import java.time.Instant
import java.time.ZoneId

/**
 * Invented sample data for the Train tab screenshots (UI-1). Public repo:
 * every number here is made up. "Today" is Wednesday 2026-09-23 at 18:00
 * Central, mid-session on a pull day.
 */
object SampleDataTrain {
    val zone: ZoneId = ZoneId.of("America/Chicago")
    val now: Instant = Instant.parse("2026-09-23T23:00:00Z")

    private fun mv(sets: Int, mev: Int, mav: Int, status: String, planned: Double? = null) =
        MuscleVolumeRow(sets = sets, mev = mev, mav = mav, status = status, setsPlanned = planned)

    val workout = StrengthWorkoutDetail(
        id = 101, date = "2026-09-23", generatedAt = "2026-09-23T11:00:00Z",
        splitFocus = "pull", status = "in_progress", seed = "sample",
        exercisesDone = 2, exercisesTotal = 6, setsDone = 8, setsTotal = 20,
        projectedMuscleVolume = mapOf(
            "lats" to mv(9, 10, 20, "under", planned = 6.0),
            "biceps" to mv(6, 8, 16, "under", planned = 4.0),
            "middle back" to mv(7, 8, 18, "under", planned = 3.0),
            "chest" to mv(12, 10, 20, "in_range", planned = 0.0),
        ),
        nextUp = StrengthNextUp(
            exerciseId = "one-arm-dumbbell-row", name = "One-arm dumbbell row",
            setNumber = 3, targetSets = 4, started = true,
        ),
    )

    val upcoming = listOf(
        UpcomingDay(date = "2026-09-23", isToday = true, splitFocus = "pull", exerciseCount = 6),
        UpcomingDay(date = "2026-09-24", splitFocus = "legs", exerciseCount = 5),
        UpcomingDay(date = "2026-09-25", splitFocus = "push", exerciseCount = 6),
        UpcomingDay(date = "2026-09-27", splitFocus = "cardio", exerciseCount = 0),
    )

    private val weekDays = listOf(
        Triple("2026-09-17", 0.0, 4100.0),
        Triple("2026-09-18", 5200.0, 0.0),
        Triple("2026-09-19", 0.0, 4800.0),
        Triple("2026-09-20", 3900.0, 3600.0),
        Triple("2026-09-21", 6100.0, 0.0),
        Triple("2026-09-22", 0.0, 5200.0),
        Triple("2026-09-23", 2800.0, 3300.0),
    ).map { (d, v, p) ->
        StrengthWeekDay(
            date = d, volumeLb = v, sets = if (v > 0) 18 else 0,
            prevDate = java.time.LocalDate.parse(d).minusDays(7).toString(), prevVolumeLb = p,
        )
    }

    val stats = StrengthStats(
        since = "2026-08-24", days = 30, nWorkouts = 14, nSets = 240, totalVolumeLb = 61200.0,
        daily = listOf(StrengthDailyVolume("2026-09-23", 2800.0, 8)),
        consistency = TrainingConsistency(sessionsLast7d = 4, sessionsLast28d = 15),
        week = StrengthWeekVolume(
            start = "2026-09-17", end = "2026-09-23", days = weekDays,
            totalLb = 18000.0, prevTotalLb = 21000.0, deltaPct = -14.3,
            better = "higher", direction = "worse", unweightedSets = 6,
        ),
    )

    val muscles = MuscleVolumeResponse(
        windowDays = 7,
        muscles = linkedMapOf(
            "chest" to mv(12, 10, 20, "in_range"),
            "lats" to mv(9, 10, 20, "under"),
            "shoulders" to mv(14, 8, 16, "in_range"),
            "quadriceps" to mv(22, 8, 18, "over"),
            "biceps" to mv(6, 8, 16, "under"),
            "triceps" to mv(10, 6, 14, "in_range"),
            "hamstrings" to mv(4, 6, 16, "under"),
            "calves" to mv(0, 8, 16, "untrained"),
            "abdominals" to mv(0, 0, 20, "untrained"),
        ),
    )

    val activities = listOf(
        ActivityRow(source = "healthconnect", sourceId = "a1", type = "ride", name = "Evening ride",
            startAt = "2026-09-23T00:30:00Z", durationS = 3120, distanceM = 18400.0, elevationGainM = 120.0),
        ActivityRow(source = "healthconnect", sourceId = "a2", type = "hike", name = "Ridge loop",
            startAt = "2026-09-20T15:00:00Z", durationS = 5400, distanceM = 7600.0, elevationGainM = 310.0),
        ActivityRow(source = "healthconnect", sourceId = "a3", type = "walk", name = null,
            startAt = "2026-09-19T13:10:00Z", durationS = 1800, distanceM = 2400.0, elevationGainM = null),
    )

    val yearWorkouts = listOf(
        StrengthWorkoutSummary(id = 99, date = "2026-09-21", splitFocus = "legs", status = "completed",
            completedAt = "2026-09-21T18:05:00Z", generatedAt = "2026-09-21T11:00:00Z"),
        StrengthWorkoutSummary(id = 98, date = "2026-09-18", splitFocus = "push", status = "completed",
            completedAt = "2026-09-18T17:40:00Z", generatedAt = "2026-09-18T11:00:00Z"),
    )

    val activityStats = ActivityStatsOut(consistency = TrainingConsistency(sessionsLast7d = 5))

    /** UI-F3: invented year-to-date comparison, in the server's shape. */
    val ytd = app.myvitals.sync.ActivityYtd(
        year = 2026, priorYear = 2025, through = "2026-09-22",
        metrics = listOf(
            app.myvitals.sync.YtdMetric("sessions", "Sessions", "", 142.0, 131.0, 11.0, 8.4, "up", "positive"),
            app.myvitals.sync.YtdMetric("distance_m", "Distance", "m", 1_602_000.0, 1_781_000.0, -179_000.0, -10.1, "down", "caution"),
        ),
    )
}
