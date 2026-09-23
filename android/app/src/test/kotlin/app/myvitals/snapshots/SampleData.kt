package app.myvitals.snapshots

import app.myvitals.sync.DailySummary
import app.myvitals.sync.FocusCount
import app.myvitals.sync.NarrativeEvent
import app.myvitals.sync.NarrativeSegment
import app.myvitals.sync.NarrativeStageTotal
import app.myvitals.sync.NarrativeStat
import app.myvitals.sync.ReadinessDetail
import app.myvitals.sync.ReadinessDriver
import app.myvitals.sync.ReadinessPoint
import app.myvitals.sync.TrainingLoad
import app.myvitals.sync.TrainingLoadDay
import app.myvitals.sync.VitalTile
import app.myvitals.sync.VitalTilePoint
import app.myvitals.sync.VitalTilesRollup
import app.myvitals.sync.WeekProgress

/**
 * Fixed, invented sample data for screenshot tests.
 *
 * This repo is public, so nothing here is a real reading. The SHAPES follow
 * the live API (keys, groups, kinds, statuses), so the screens render the
 * way they do on the phone; the numbers are made up and chosen to exercise
 * several states at once — a typical metric, a good one, a stale one, a
 * goal with distance to go.
 */
object SampleData {
    const val DATE = "2026-09-22"

    private fun series(base: Double, wobble: Double) = (0 until 14).map { i ->
        VitalTilePoint(date = "2026-09-%02d".format(9 + i), value = base + wobble * kotlin.math.sin(i * 0.9))
    }

    val tiles = listOf(
        VitalTile(key = "hrv", label = "HRV", unit = "ms", value = 42.1, kind = "baseline",
            higherIsBetter = true, baseline = 40.2, bandLow = 36.5, bandHigh = 44.0,
            group = "Sleep & recovery", delta = 1.9, z = 0.4, status = "typical",
            statusReason = "in your usual range", series = series(40.0, 3.0)),
        VitalTile(key = "resting_hr", label = "Resting HR", unit = "bpm", value = 58.4, kind = "baseline",
            higherIsBetter = false, baseline = 59.6, bandLow = 57.0, bandHigh = 62.0,
            group = "Sleep & recovery", delta = -1.2, z = -0.5, status = "typical",
            statusReason = "in your usual range", series = series(59.0, 1.5)),
        VitalTile(key = "sleep_duration", label = "Sleep", unit = "h", value = 7.6, kind = "target",
            target = 8.0, group = "Sleep & recovery", status = "good",
            statusReason = "close to your target", series = series(7.2, 0.6)),
        VitalTile(key = "recovery", label = "Recovery", unit = "", value = 68, kind = "target",
            target = 100.0, group = "Sleep & recovery", status = "typical", series = series(62.0, 8.0)),
        VitalTile(key = "steps", label = "Steps", unit = "", value = 4312, kind = "target",
            target = 10000.0, group = "Activity & body", status = "watch",
            statusReason = "behind your usual pace", series = series(8200.0, 2500.0)),
        VitalTile(key = "weight", label = "Weight", unit = "lb", value = 184.6, kind = "neutral",
            target = 175.0, goalNote = "9.6 lb to lose", group = "Activity & body",
            staleDays = 2, asOf = "2026-09-20", series = series(185.5, 0.8)),
        VitalTile(key = "blood_pressure", label = "Blood pressure", unit = "mmHg", value = "121/78",
            kind = "target", target = 130.0, group = "Activity & body", staleDays = 12,
            asOf = "2026-09-10", series = emptyList()),
        VitalTile(key = "skin_temp", label = "Skin temp", unit = "°C", value = 0.2, kind = "neutral",
            group = "Activity & body", staleDays = 1, asOf = "2026-09-21", series = series(0.0, 0.3)),
    )

    val groupOrder = listOf("Sleep & recovery", "Activity & body")
    val week = WeekProgress(label = "Weekly steps", done = 31_480, goal = 70_000, pct = 45.0)
    val rollup = VitalTilesRollup(judged = 5, inRange = 4, total = 8)
    val focus = mapOf(
        "heart" to FocusCount(3, 3), "sleep" to FocusCount(1, 1),
        "vitals" to FocusCount(4, 5), "fitness" to FocusCount(1, 1),
    )

    val readiness = ReadinessDetail(
        date = DATE, score = 71.0, band = "high",
        drivers = listOf(
            ReadinessDriver("hrv", "HRV", 42.1, "ms", 0.4, 58.0, 0.4, 40.2, true),
            ReadinessDriver("rhr", "Resting HR", 58.4, "bpm", -0.5, 61.0, 0.3, 59.6, false),
            ReadinessDriver("sleep_score", "Sleep score", 88.0, "", 0.6, 80.0, 0.15, 82.0, true),
            ReadinessDriver("sleep_duration", "Sleep", 7.6, "h", 0.2, 72.0, 0.15, 7.3, true),
        ),
        series = (16..22).map { ReadinessPoint("2026-09-$it", 60.0 + (it % 4) * 4) },
        weights = mapOf("hrv" to 0.4, "rhr" to 0.3, "sleep_score" to 0.15, "sleep_duration" to 0.15),
    )

    val summary = DailySummary(
        date = DATE, restingHr = 58.4, hrvAvg = 42.1, recoveryScore = 68.0,
        sleepDurationS = 27_360, sleepScore = 88.0, stepsTotal = 4312,
        // Relative to the real clock: the screen renders "Synced Xm ago"
        // from now(), so a fixed instant would drift the image every run.
        lastSync = java.time.Instant.now().minusSeconds(25 * 60).toString(),
    )

    val sleepEvent = NarrativeEvent(
        id = "sleep:2026-09-22T04:10:00+00:00", kind = "sleep",
        headline = "Sleep tracked",
        detail = "You slept 7 hr 36 min, starting at 11:10 PM. Deep sleep was a little above your usual.",
        start = "2026-09-22T04:10:00+00:00", end = "2026-09-22T11:46:00+00:00",
        durationS = 27_360,
        stats = listOf(
            NarrativeStat("Sleep score", "88", "Good", "good"),
            NarrativeStat("Deep", "1 hr 22 min", "Typical", "typical"),
        ),
        stages = listOf(
            NarrativeStageTotal("awake", 1_500), NarrativeStageTotal("light", 14_400),
            NarrativeStageTotal("deep", 4_920), NarrativeStageTotal("rem", 6_540),
        ),
        segments = listOf(
            NarrativeSegment("2026-09-22T04:10:00+00:00", "awake", 600),
            NarrativeSegment("2026-09-22T04:20:00+00:00", "light", 3_600),
            NarrativeSegment("2026-09-22T05:20:00+00:00", "deep", 2_400),
            NarrativeSegment("2026-09-22T06:00:00+00:00", "rem", 1_800),
            NarrativeSegment("2026-09-22T06:30:00+00:00", "light", 5_400),
            NarrativeSegment("2026-09-22T08:00:00+00:00", "deep", 2_520),
            NarrativeSegment("2026-09-22T08:42:00+00:00", "rem", 4_740),
            NarrativeSegment("2026-09-22T10:01:00+00:00", "light", 5_400),
            NarrativeSegment("2026-09-22T11:31:00+00:00", "awake", 900),
        ),
    )

    val trainingLoad = TrainingLoad(
        weekLoad = 312.0, targetLow = 250.0, targetHigh = 420.0, acwr = 1.08, band = "optimal",
        ctl = 48.0, atl = 52.0,
        daily = listOf(40.0, 0.0, 95.0, 60.0, 0.0, 117.0, 0.0).mapIndexed { i, l ->
            TrainingLoadDay("2026-09-%02d".format(16 + i), l)
        },
    )
}
