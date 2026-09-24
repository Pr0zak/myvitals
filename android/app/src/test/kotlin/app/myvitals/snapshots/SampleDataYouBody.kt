package app.myvitals.snapshots

import app.myvitals.sync.AiGoal
import app.myvitals.sync.FastingSession
import app.myvitals.sync.ProfileDerived
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.SoberStreak
import app.myvitals.sync.VitalTile
import app.myvitals.sync.VitalTilePoint
import app.myvitals.sync.VitalTilesResponse
import app.myvitals.sync.VitalTilesRollup
import app.myvitals.ui.neon.YouData

/**
 * Invented sample data for the You and Body screenshot tests (UI-3). The
 * repo is public: every number here is made up. Shapes follow the live API
 * so the screens render as they do on the phone, and the values are picked
 * to exercise several states at once — a goal advancing, one gone the
 * wrong way, one with no reading; a stale weigh-in, a cuff reading twelve
 * days old.
 */
object SampleDataYouBody {
    // ── You ────────────────────────────────────────────────────────────
    val profile = ProfileResponse(
        sex = "male", heightCm = 180.0, activityLevel = "moderately_active",
        derived = ProfileDerived(age = 41),
    )

    val fasting = FastingSession(
        id = 1, startedAt = "2026-09-22T20:00:00-05:00", endedAt = null,
        protocol = "16:8", mode = "time_restricted", targetHours = 16.0,
        targetEatingWindowH = 8.0, notes = null, elapsedH = 14.3,
        currentStage = "glycogen_depleting", nextStageAtH = 16.0, isActive = true,
    )

    val sober = SoberCurrentResponse(
        active = SoberStreak(
            id = 3, addiction = "alcohol", startAt = "2026-05-02T09:00:00-05:00",
            endAt = null, notes = null, days = 143.4,
        ),
        addiction = "alcohol", days = 143, hours = 10, minutes = 12,
    )

    val goals = listOf(
        AiGoal(id = 1, kind = "steps", title = "Daily steps", targetValue = 10000.0,
            targetUnit = "steps", startedAt = "2026-09-01", currentValue = 7200.0,
            progressPct = 72.0, progressState = "advancing", stateTone = "positive"),
        AiGoal(id = 2, kind = "weight", title = "Reach 175 lb", targetValue = 175.0,
            targetUnit = "lb", startedAt = "2026-08-01", currentValue = 187.2,
            progressPct = 0.0, baselineValue = 184.0, progressState = "moved_away",
            stateTone = "caution", deltaValue = 3.2),
        AiGoal(id = 3, kind = "sleep", title = "Sleep 8 hours", targetValue = 8.0,
            targetUnit = "h", startedAt = "2026-09-15", progressPct = null,
            progressState = "no_data", stateTone = "unknown"),
    )

    val you = YouData(
        fasting = fasting, fastingKnown = true, sober = sober, goals = goals, profile = profile,
    )

    // ── Body ───────────────────────────────────────────────────────────
    private fun daily(base: Double, wobble: Double) = (0 until 14).map { i ->
        VitalTilePoint(date = "2026-09-%02d".format(9 + i), value = base + wobble * kotlin.math.sin(i * 0.9))
    }

    /** Readings only on the given day offsets (0 = oldest of 14). */
    private fun sparse(base: Double, days: Set<Int>) = (0 until 14).map { i ->
        VitalTilePoint(date = "2026-09-%02d".format(9 + i), value = if (i in days) base + i * 0.1 else null)
    }

    val tiles = listOf(
        VitalTile(key = "hrv", label = "HRV", unit = "ms", value = 46.3, kind = "baseline",
            higherIsBetter = true, baseline = 43.0, bandLow = 38.7, bandHigh = 47.3,
            group = "Sleep & recovery", delta = 3.3, status = "typical",
            statusReason = "in your usual range", series = daily(43.0, 4.0), cadence = "daily"),
        VitalTile(key = "resting_hr", label = "Resting HR", unit = "bpm", value = 61.0, kind = "baseline",
            higherIsBetter = false, baseline = 58.5, bandLow = 55.6, bandHigh = 61.4,
            group = "Sleep & recovery", delta = 2.5, status = "typical",
            statusReason = "in your usual range", series = daily(59.0, 2.0), cadence = "daily"),
        VitalTile(key = "sleep_duration", label = "Sleep", unit = "h", value = 6.9, kind = "target",
            higherIsBetter = true, target = 8.0, group = "Sleep & recovery", status = "typical",
            statusReason = "near your target", series = daily(7.1, 0.7), cadence = "daily"),
        VitalTile(key = "recovery", label = "Recovery", unit = "", value = 71.0, kind = "target",
            higherIsBetter = true, target = 100.0, bandLow = 65.0, bandHigh = 100.0,
            group = "Sleep & recovery", status = "good", statusReason = "recovered",
            series = daily(64.0, 9.0), cadence = "daily"),
        VitalTile(key = "steps", label = "Steps", unit = "", value = 6480.0, kind = "target",
            higherIsBetter = true, target = 9000.0, group = "Activity & body", status = "watch",
            statusReason = "below goal", series = daily(7600.0, 2200.0), cadence = "daily"),
        VitalTile(key = "skin_temp", label = "Skin temp", unit = "°C", value = -0.2, kind = "neutral",
            group = "Activity & body", staleDays = 3, asOf = "2026-09-19",
            series = sparse(-0.1, setOf(2, 3, 5, 6, 9, 10)), cadence = "intermittent"),
        VitalTile(key = "weight", label = "Weight", unit = "lb", value = 187.2, kind = "neutral",
            target = 175.0, goalNote = "12.2 lb to lose", group = "Activity & body",
            staleDays = 2, asOf = "2026-09-20", series = sparse(186.5, setOf(1, 4, 8, 11)),
            cadence = "intermittent"),
        VitalTile(key = "blood_pressure", label = "Blood pressure", unit = "mmHg", value = "124/79",
            kind = "target", higherIsBetter = false, target = 130.0, group = "Activity & body",
            status = "typical", statusReason = "elevated range", staleDays = 12, asOf = "2026-09-10",
            series = sparse(124.0, setOf(1)), cadence = "intermittent"),
    )

    val tilesResponse = VitalTilesResponse(
        date = "2026-09-22",
        tiles = tiles,
        summary = VitalTilesRollup(judged = 6, inRange = 5, total = 8),
        groupOrder = listOf("Sleep & recovery", "Activity & body"),
        lastSync = "2026-09-22T10:48:00-05:00",
    )

    /** "now" for the sync-age line, 12 minutes after [tilesResponse]'s sync. */
    val NOW_MS: Long = java.time.OffsetDateTime.parse("2026-09-22T11:00:00-05:00")
        .toInstant().toEpochMilli()

    val ZONE: java.time.ZoneId = java.time.ZoneId.of("America/Chicago")
}
