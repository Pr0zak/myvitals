package app.myvitals.snapshots

import app.myvitals.sync.ActivityRow
import app.myvitals.sync.ActivityYtd
import app.myvitals.sync.ActivityZones
import app.myvitals.sync.HrZone
import app.myvitals.sync.SessionSummary
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.sync.TimePoint
import app.myvitals.sync.Trail
import app.myvitals.sync.TrailStatusCounts
import app.myvitals.sync.YtdCumulative
import app.myvitals.sync.YtdMetric
import app.myvitals.sync.YtdWeek
import app.myvitals.ui.trails.TrailsUi
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Invented sample data for the UI-5 screenshot tests (Activities feed,
 * Activity detail, Trails). Public repo: every name, place and number here
 * is made up. The values are picked to exercise several states at once —
 * a year behind last year on distance but ahead on sessions, a metric with
 * no prior year ("new"), a strength day still in progress, a closed and a
 * delayed trail, a trail that has never been ridden.
 */
object SampleDataUi5 {
    val ZONE: ZoneId = ZoneId.of("America/Chicago")
    val TODAY: LocalDate = LocalDate.of(2026, 9, 24)
    val NOW_MS: Long = Instant.parse("2026-09-24T17:00:00Z").toEpochMilli()

    // ── Activities ────────────────────────────────────────────────────
    private fun act(id: String, type: String, name: String?, start: String, durS: Int,
                    distM: Double?, elevM: Double? = null, avgHr: Double? = null,
                    maxHr: Double? = null, kcal: Double? = null, polyline: String? = null,
                    trailId: Long? = null, trailName: String? = null, source: String = "strava") =
        ActivityRow(source = source, sourceId = id, type = type, name = name, startAt = start,
            durationS = durS, distanceM = distM, elevationGainM = elevM, avgHr = avgHr, maxHr = maxHr,
            kcal = kcal, polyline = polyline, trailId = trailId, trailName = trailName)

    val rows = listOf(
        act("a1", "Ride", "Lakeside loop", "2026-09-23T12:10:00Z", 5400, 32_400.0, 210.0, 138.0, 171.0, 820.0),
        act("a2", "Run", "Easy miles", "2026-09-22T11:30:00Z", 2460, 6_900.0, 40.0, 149.0, 168.0, 430.0),
        act("a3", "Walk", null, "2026-09-21T22:05:00Z", 1800, 2_300.0),
        act("a4", "MountainBikeRide", "Ridge singletrack", "2026-09-19T14:00:00Z", 6300, 24_100.0,
            480.0, 144.0, 179.0, 910.0, trailId = 3, trailName = "Ridge Park"),
        act("a5", "Hike", "Bluff trail", "2026-09-13T15:20:00Z", 7200, 9_800.0, 350.0),
        act("a6", "Ride", "Commute", "2026-09-10T12:45:00Z", 1500, 8_200.0),
    )

    val workouts = listOf(
        StrengthWorkoutSummary(id = 11, date = "2026-09-24", splitFocus = "push", status = "in_progress",
            startedAt = "2026-09-24T16:10:00Z", generatedAt = "2026-09-24T11:00:00Z"),
        StrengthWorkoutSummary(id = 10, date = "2026-09-20", splitFocus = "pull", status = "completed",
            startedAt = "2026-09-20T15:00:00Z", completedAt = "2026-09-20T15:52:00Z",
            generatedAt = "2026-09-20T11:00:00Z",
            sessionSummary = SessionSummary(netDurationS = 2940, workingSets = 16, totalReps = 150,
                totalVolumeLb = 11_450.0, kcalEst = 240.0, kcalMethod = "hr")),
        StrengthWorkoutSummary(id = 9, date = "2026-09-15", splitFocus = "yoga", status = "completed",
            startedAt = "2026-09-15T12:00:00Z", completedAt = "2026-09-15T12:25:00Z",
            generatedAt = "2026-09-15T11:00:00Z",
            sessionSummary = SessionSummary(netDurationS = 1500)),
    )

    /** A smooth-ish cumulative line: this year behind last year. */
    private fun cumulative(days: Int, perDay: Double, wobble: Double): List<Int> {
        var run = 0.0
        return (0 until days).map { i ->
            run += perDay * (1.0 + wobble * kotlin.math.sin(i / 11.0))
            run.toInt()
        }
    }

    val ytd = ActivityYtd(
        year = 2026, priorYear = 2025, through = "2026-09-24",
        metrics = listOf(
            YtdMetric("sessions", "Sessions", "", current = 164.0, prior = 151.0, delta = 13.0,
                pctChange = 8.6, direction = "improved", tone = "positive"),
            YtdMetric("distance_m", "Distance", "m", current = 2_410_000.0, prior = 2_760_000.0,
                delta = -350_000.0, pctChange = -12.7, direction = "worse", tone = "caution"),
            YtdMetric("duration_s", "Moving time", "s", current = 468_000.0, prior = 470_000.0,
                delta = -2000.0, pctChange = -0.4, direction = "flat", tone = "neutral"),
            YtdMetric("elevation_m", "Climbed", "m", current = 18_300.0, prior = 0.0,
                delta = 18_300.0, pctChange = null, direction = "new", tone = "positive", note = "new"),
        ),
        cumulative = YtdCumulative(
            thisYear = cumulative(267, 9_030.0, 0.35),
            lastYear = cumulative(365, 10_300.0, 0.25),
        ),
        thisWeek = YtdWeek("2026-09-21", sessions = 4, durationS = 16_020),
        weeks = listOf(
            YtdWeek("2026-09-21", 4, 16_020),
            YtdWeek("2026-09-14", 3, 12_000),
            YtdWeek("2026-09-07", 1, 1500),
        ),
    )

    // ── Activity detail ───────────────────────────────────────────────
    val ride = rows[3].copy(avgPowerW = 182.0, notes = "Dry and fast after two days of sun.")
    val walkNoRoute = act("hc1", "Walk", "Evening walk", "2026-09-21T22:05:00Z", 1800, 2_300.0,
        avgHr = 101.0, maxHr = 118.0, source = "manual")

    val zones = ActivityZones(
        maxHr = 186, maxHrSource = "profile", sampled = true, totalSeconds = 6300,
        zones = listOf(
            HrZone("Z1", "Recovery", 0, 111, seconds = 620, pct = 9.8),
            HrZone("Z2", "Endurance", 112, 130, seconds = 1890, pct = 30.0),
            HrZone("Z3", "Tempo", 131, 148, seconds = 2270, pct = 36.0),
            HrZone("Z4", "Threshold", 149, 167, seconds = 1200, pct = 19.0),
            HrZone("Z5", "VO2", 168, null, seconds = 320, pct = 5.1),
        ),
    )

    /** A 105-minute ride's heart rate, one sample every 30s, invented. */
    val hrPoints: List<TimePoint> = run {
        val start = Instant.parse("2026-09-19T14:00:00Z")
        (0 until 210).map { i ->
            val base = 128.0 + 18.0 * kotlin.math.sin(i / 17.0) + 10.0 * kotlin.math.sin(i / 5.0)
            val climb = if (i in 140..160) 30.0 * kotlin.math.sin((i - 140) / 20.0 * Math.PI) else 0.0
            TimePoint(start.plusSeconds(i * 30L).toString(), (base + climb).coerceIn(95.0, 181.0))
        }
    }

    val trailsForDetail = listOf(
        Trail(id = 3, extension = 103, name = "Ridge Park", slug = "ridge-park",
            lastSeenAt = "2026-09-24T16:55:00Z", latitude = 39.1, longitude = -94.6,
            status = "open", visitsTotal = 27, lastVisitAt = "2026-09-19T14:00:00Z"),
    )

    // ── Trails ────────────────────────────────────────────────────────
    private fun trail(id: Long, name: String, status: String?, srcTs: String, sub: Boolean = false,
                      visits: Int = 0, last: String? = null, comment: String? = null,
                      city: String? = "Riverton", pinned: Boolean = true) =
        Trail(id = id, extension = 100 + id.toInt(), name = name, slug = name.lowercase().replace(' ', '-'),
            lastSeenAt = "2026-09-24T16:55:00Z",
            latitude = if (pinned) 39.0 + id * 0.01 else null,
            longitude = if (pinned) -94.6 - id * 0.01 else null,
            city = city, state = "KS", subscribed = sub, status = status, comment = comment,
            sourceTs = srcTs, fetchedAt = "2026-09-24T16:56:00Z",
            visitsTotal = visits, lastVisitAt = last)

    val trails = listOf(
        trail(3, "Ridge Park", "open", "2026-09-24T12:00:00Z", sub = true, visits = 27,
            last = "2026-09-19T14:00:00Z", comment = "Dry, fast, some leaf cover on the descents."),
        trail(4, "Mill Creek", "open", "2026-09-24T11:30:00Z", sub = true, visits = 9,
            last = "2026-07-02T14:00:00Z"),
        trail(5, "Cedar Hollow", "open", "2026-09-23T20:00:00Z", visits = 2, last = "2026-02-11T15:00:00Z"),
        trail(6, "Lone Pine", "open", "2026-09-23T18:00:00Z", sub = true),
        trail(7, "Blue River Bottoms", "delayed", "2026-09-24T13:10:00Z",
            comment = "Standing water near the bridge; check back at noon."),
        trail(8, "Quarry Loop", "closed", "2026-09-22T09:00:00Z", comment = "Closed for bridge repair."),
        trail(9, "Hawk Ridge", "open", "2026-09-22T08:00:00Z", pinned = false),
        trail(10, "Old Orchard", null, "2026-09-01T08:00:00Z"),
    )

    val trailsUi = TrailsUi(
        trails = trails.sortedBy { it.name },
        counts = TrailStatusCounts(open = 5, delayed = 1, closed = 1, other = 1),
        syncedAt = "2026-09-24T16:56:00Z",
    )
}
