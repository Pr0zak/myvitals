package app.myvitals.snapshots

import app.myvitals.sync.DailySummary
import app.myvitals.sync.DatedValue
import app.myvitals.sync.HrHistBin
import app.myvitals.sync.HrZoneStats
import app.myvitals.sync.HrZoneTime
import app.myvitals.sync.RestingHrRangeStats
import app.myvitals.sync.SleepNight
import app.myvitals.sync.SleepRangeStats
import app.myvitals.sync.SleepRawSegment
import app.myvitals.sync.SleepStageBucket
import app.myvitals.sync.StepsRangeStats
import app.myvitals.sync.TimePoint
import app.myvitals.sync.TimeSeries
import app.myvitals.sync.VitalTile
import app.myvitals.sync.WeekdayMean
import app.myvitals.sync.WeightDelta
import app.myvitals.sync.WeightPointOut
import app.myvitals.sync.WeightSeriesOut
import app.myvitals.sync.WeightStats
import app.myvitals.sync.WeightTrend
import java.time.LocalDate
import java.time.ZoneId
import kotlin.math.PI
import kotlin.math.sin

/**
 * Invented sample data for the metric detail screenshot tests (UI-4). The
 * repo is public: every reading here is made up, generated from simple
 * formulas. The STAT blocks are hand-written to look like what the server
 * would return for these rows — the screens render them verbatim, which is
 * the point of the slice, so they are not re-derived here either.
 */
object SampleDataDetail {
    val TODAY: LocalDate = LocalDate.of(2026, 9, 22)
    private val zone: ZoneId = ZoneId.systemDefault()
    /** 15:30 local on TODAY — "now" for the HR trace. */
    val NOW_MS: Long = TODAY.atTime(15, 30).atZone(zone).toInstant().toEpochMilli()

    private fun iso(d: LocalDate, h: Int, m: Int = 0): String =
        d.atTime(h, m).atZone(zone).toInstant().toString()

    // ── Steps ────────────────────────────────────────────────────────────
    private val stepPattern = listOf(
        6200, 11800, 9400, 12600, 4100, 7300, 10900, 13200, 8800, 5600,
        10100, 9700, 14100, 3800, 7900, 11200, 10400, 6700, 12300, 9100,
        4500, 10800, 11600, 8300, 13900, 7400, 10200, 5100, 9900, 7342,
    )
    val stepRows: List<DailySummary> = stepPattern.mapIndexed { i, n ->
        val d = TODAY.minusDays((29 - i).toLong())
        DailySummary(
            date = d.toString(),
            stepsTotal = if (i == 13) null else n,           // a day the watch was off
            stepsGoal = if (d.dayOfWeek.value == 7) 7000 else 10000,
            restingHr = 58.0 + 3 * sin(i / 4.0) + (if (i % 6 == 0) 2 else 0),
        )
    }
    val stepStats = StepsRangeStats(
        avg = 9321, min = 3800, max = 14100, total = 270_318, daysWithData = 29, goalDays = 15,
        windowDays = 30,
        weekdayMeans = listOf(
            WeekdayMean("Sun", 8120.0, 4), WeekdayMean("Mon", 10450.0, 4), WeekdayMean("Tue", 9810.0, 5),
            WeekdayMean("Wed", 9020.0, 4), WeekdayMean("Thu", 10960.0, 4), WeekdayMean("Fri", 8740.0, 4),
            WeekdayMean("Sat", 7690.0, 4),
        ),
        rolling7d = stepRows.map { DatedValue(it.date, 9300.0) },
    )
    val stepsTile = VitalTile(
        key = "steps", label = "Steps", value = 7342.0, kind = "target", target = 10000.0,
        status = "typical", statusReason = "73% of 10,000",
    )
    val hourly: List<Int> = listOf(
        0, 0, 0, 0, 0, 0, 180, 920, 1240, 610, 430, 520, 1380, 690, 810, 562, 0, 0, 0, 0, 0, 0, 0, 0,
    )

    // ── Heart rate ───────────────────────────────────────────────────────
    val hrPoints: List<TimePoint> = buildList {
        val start = TODAY.atStartOfDay(zone).toInstant()
        var t = start
        var i = 0
        while (t.toEpochMilli() < NOW_MS) {
            val hour = i * 2 / 60.0
            val base = if (hour < 6.5) 54.0 else 68.0 + 6 * sin(hour / 3.0)
            // A ride from 07:10 to 08:00.
            val ride = if (hour in 7.17..8.0) 70 * sin((hour - 7.17) / 0.83 * PI) else 0.0
            add(TimePoint(time = t.toString(), value = base + ride + 3 * sin(i * 0.7)))
            t = t.plusSeconds(120); i++
        }
    }
    val hrZones = HrZoneStats(
        timeInZone = listOf(
            HrZoneTime("Z1", "Recovery", 0, 108, 50_400, 90.2),
            HrZoneTime("Z2", "Endurance", 108, 126, 2_880, 5.2),
            HrZoneTime("Z3", "Tempo", 126, 144, 1_320, 2.4),
            HrZoneTime("Z4", "Threshold", 144, 162, 960, 1.7),
            HrZoneTime("Z5", "VO2 Max", 162, null, 300, 0.5),
        ),
        trackedS = 55_860,
        histogram = (50..145 step 5).map { lo ->
            HrHistBin(lo, lo + 5, when {
                lo < 55 -> 180.0; lo < 65 -> 240.0; lo < 75 -> 300.0; lo < 90 -> 60.0; else -> 8.0
            })
        },
        maxHr = 180, maxHrSource = "estimated",
    )
    val hrLive = TimeSeries(points = hrPoints, avg = 66.4, minBpm = 49.0, maxBpm = 163.0, stats = hrZones)
    val restingTile = VitalTile(
        key = "resting_hr", label = "Resting HR", unit = "bpm", value = 57.0, kind = "baseline",
        baseline = 58.4, bandLow = 55.5, bandHigh = 61.3, status = "typical",
        statusReason = "in your usual range",
    )
    val restingStats = RestingHrRangeStats(
        avg = 58.6, min = 54.2, max = 63.1, latest = 57.0, latestVsAvg = -1.6, daysWithData = 30,
        weekdayMeans = listOf(
            WeekdayMean("Sun", 57.1, 4), WeekdayMean("Mon", 59.8, 4), WeekdayMean("Tue", 58.9, 5),
            WeekdayMean("Wed", 58.2, 4), WeekdayMean("Thu", 58.7, 4), WeekdayMean("Fri", 59.4, 4),
            WeekdayMean("Sat", 57.6, 5),
        ),
    )

    // ── Sleep ────────────────────────────────────────────────────────────
    val sleepRaw: List<SleepRawSegment> = buildList {
        val cycle = listOf("light" to 25, "deep" to 35, "light" to 20, "rem" to 20, "awake" to 4)
        var t = TODAY.minusDays(1).atTime(22, 50).atZone(zone).toInstant()
        repeat(5) { c ->
            for ((st, mins) in cycle) {
                val m = if (st == "deep") mins - c * 6 else if (st == "rem") mins + c * 4 else mins
                add(SleepRawSegment(time = t.toString(), stage = st, durationS = m * 60))
                t = t.plusSeconds(m * 60L)
            }
        }
    }
    val sleepNights: List<SleepNight> = (13 downTo 0).map { back ->
        val end = TODAY.minusDays(back.toLong())
        val total = (6.3 + 1.4 * sin(back / 2.0)) * 3600
        val deep = (total * 0.17).toInt()
        val rem = (total * 0.22).toInt()
        val light = total.toInt() - deep - rem
        SleepNight(
            date = end.toString(),
            start = iso(end.minusDays(1), 22, 50),
            end = iso(end, 6, 40),
            totalS = total.toInt(),
            stages = listOf(
                SleepStageBucket("light", light), SleepStageBucket("deep", deep),
                SleepStageBucket("rem", rem), SleepStageBucket("awake", 1200),
            ),
        )
    }
    val sleepStats = SleepRangeStats(avgS = 22_950, minS = 17_700, maxS = 27_700, nights = 14, naps = 1)
    val sleepTile = VitalTile(
        key = "sleep_duration", label = "Sleep", unit = "h", value = 7.2, kind = "target",
        target = 8.0, status = "typical", statusReason = "0.8 h under target",
    )

    // ── Weight ───────────────────────────────────────────────────────────
    val weight: WeightSeriesOut = WeightSeriesOut(
        points = (28 downTo 0 step 2).map { back ->
            val d = TODAY.minusDays(back.toLong())
            WeightPointOut(time = iso(d, 7, 10), weightKg = 84.0 - (29 - back) * 0.05 + 0.3 * sin(back.toDouble()))
        },
        stats = WeightStats(
            count = 15, firstKg = 83.7, latestKg = 82.55, deltaKg = -1.15,
            minKg = 82.3, maxKg = 84.1, avgKg = 83.2, goalKg = 79.4, goalGapKg = 3.15,
            tone = "positive",
            trend = WeightTrend(
                startTime = iso(TODAY.minusDays(28), 7, 10), startKg = 84.0,
                endTime = iso(TODAY, 7, 10), endKg = 82.6, perWeekKg = -0.34,
            ),
            delta7d = WeightDelta(-0.41, "neutral"),
            delta30d = WeightDelta(-1.19, "positive"),
        ),
    )
    val weightTile = VitalTile(
        key = "weight", label = "Weight", unit = "lb", value = 182.0, kind = "neutral",
        target = 175.0, goalNote = "7 lb to lose",
    )
}
