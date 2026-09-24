package app.myvitals.snapshots

import app.myvitals.sync.FastingSession
import app.myvitals.sync.FastingStage
import app.myvitals.sync.FastingStats
import app.myvitals.sync.FatAssessment
import app.myvitals.sync.LogDayOut
import app.myvitals.sync.LogEntryOut
import app.myvitals.sync.LogMealOut
import app.myvitals.sync.PrepBudgets
import app.myvitals.sync.PrepComponentOut
import app.myvitals.sync.PrepDayOut
import app.myvitals.sync.PrepMealOut
import app.myvitals.sync.PrepMealUse
import app.myvitals.sync.PrepPlanOut
import app.myvitals.sync.PrepTargetsOut
import app.myvitals.sync.RecentEntryOut
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.sync.SoberStreak
import java.time.Instant

/**
 * Invented sample data for the UI-6 screenshot tests (Sober, Fasting,
 * Meals Today, Prep). Public repo: none of this is a real reading. Shapes
 * follow the live API; numbers are made up to exercise several states at
 * once (a passed milestone and one ahead, a short fast beside completed
 * ones, every per-meal fat verdict including "unknown" and an empty slot).
 */
object SampleDataUi6 {
    /** The fixed "now" every screen renders against. */
    val NOW_MS: Long = Instant.parse("2026-09-22T18:00:00Z").toEpochMilli()
    const val TODAY = "2026-09-22"

    // ── Sober ──
    private val soberStart = "2026-08-11T10:30:00Z"   // 42d 7h30m before NOW
    val soberActive = SoberStreak(id = 9, addiction = "alcohol", startAt = soberStart, endAt = null,
        notes = null, days = 42.31)
    val soberCurrent = SoberCurrentResponse(
        active = soberActive, addiction = "alcohol", now = "2026-09-22T18:00:00Z",
        elapsedSeconds = 42L * 86400 + 7 * 3600 + 1800, days = 42, hours = 7, minutes = 30,
        milestones = listOf(7, 14, 30, 60, 90, 180, 365), milestonesReached = 3,
        nextMilestoneDays = 60, nextMilestoneAt = "2026-10-10T10:30:00Z",
        nextMilestoneInSeconds = 17L * 86400 + 16 * 3600 + 1800, milestoneProgress = 0.4870,
    )
    val soberNone = SoberCurrentResponse(
        active = null, addiction = "alcohol", milestones = listOf(7, 14, 30, 60, 90, 180, 365),
    )
    val soberHistory = listOf(
        soberActive,
        SoberStreak(8, "alcohol", "2026-06-02T09:00:00Z", "2026-08-11T10:30:00Z", null, 70.06),
        SoberStreak(7, "alcohol", "2026-05-10T09:00:00Z", "2026-06-02T09:00:00Z", null, 23.0),
        SoberStreak(6, "alcohol", "2026-03-01T09:00:00Z", "2026-05-10T09:00:00Z", null, 70.0),
        SoberStreak(5, "alcohol", "2026-02-18T09:00:00Z", "2026-03-01T09:00:00Z", null, 11.0),
        SoberStreak(4, "alcohol", "2026-01-05T09:00:00Z", "2026-02-18T09:00:00Z", null, 44.0),
    )

    // ── Fasting ──
    val stages = listOf(
        FastingStage("fed", "Fed state", 0.0), FastingStage("gut_rest", "Gut rest", 4.0),
        FastingStage("glycogen_depleting", "Glycogen depleting", 12.0),
        FastingStage("ketosis", "Ketosis", 16.0), FastingStage("autophagy", "Autophagy", 18.0),
        FastingStage("deep_autophagy", "Deep autophagy", 24.0),
        FastingStage("extended_36", "36h territory", 36.0), FastingStage("extended_48", "48h territory", 48.0),
        FastingStage("extended_72", "72h+ territory", 72.0),
    )
    val fastActive = FastingSession(
        id = 120, startedAt = "2026-09-22T03:42:00Z", endedAt = null, protocol = "16:8", mode = "active",
        targetHours = 16.0, targetEatingWindowH = 8.0, notes = null, elapsedH = 14.3,
        currentStage = "glycogen_depleting", nextStageAtH = 16.0, isActive = true,
        currentStageLabel = "Glycogen depleting", nextStage = "ketosis", nextStageLabel = "Ketosis",
        hoursToNextStage = 1.7, targetEndAt = "2026-09-22T19:42:00Z", reachedTarget = false, stages = stages,
    )
    val fastHistory: List<FastingSession> = (0 until 20).map { i ->
        val elapsed = listOf(16.4, 17.1, 12.5, 16.0, 18.3, 16.8, 9.2, 16.2, 20.1, 16.5)[i % 10]
        val target = if (i % 7 == 3) 18.0 else 16.0
        FastingSession(
            id = 119L - i, startedAt = "2026-09-%02dT03:00:00Z".format(21 - i), endedAt = "2026-09-%02dT20:00:00Z".format(21 - i),
            protocol = if (target == 18.0) "18:6" else "16:8", mode = "active", targetHours = target,
            targetEatingWindowH = 24 - target, notes = null, elapsedH = elapsed, currentStage = "ketosis",
            nextStageAtH = null, isActive = false, reachedTarget = elapsed >= target, stages = stages,
        )
    }
    val fastStats = FastingStats(sessionsCount = 42, completedCount = 36, avgDurationH = 16.2,
        medianDurationH = 16.4, longestH = 23.5, currentStreakDays = 6, lastCompletedAt = "2026-09-21T20:00:00Z")

    // ── Meals Today ──
    private fun entry(id: Long, slot: String, label: String, kcal: Double?, fat: Double?, q: Double? = null, u: String? = null) =
        LogEntryOut(id = id, day = TODAY, slot = slot, label = label, quantity = q, unit = u,
            nutrition = mapOf("kcal" to kcal, "fat_g" to fat), source = if (kcal == null) "none" else "catalog")
    val mealsDay = LogDayOut(
        day = TODAY,
        meals = listOf(
            LogMealOut("breakfast", listOf(entry(1, "breakfast", "Oatmeal", 300.0, 5.5, 1.0, "cup"),
                entry(2, "breakfast", "Banana", 105.0, 0.4, 1.0, "piece")),
                mapOf("kcal" to 405.0, "fat_g" to 5.9),
                FatAssessment(fatG = 5.9, verdict = "ok", basis = "target", targetG = 20.0)),
            LogMealOut("lunch", listOf(entry(3, "lunch", "Cheeseburger", 740.0, 31.0)),
                mapOf("kcal" to 740.0, "fat_g" to 31.0),
                FatAssessment(fatG = 31.0, verdict = "high", basis = "target", targetG = 20.0,
                    reason = "31 g — over your 20 g per-meal target")),
            LogMealOut("snack", listOf(entry(4, "snack", "Protein bar (from the wrapper)", null, null)),
                mapOf("kcal" to null, "fat_g" to null),
                FatAssessment(fatG = null, verdict = "unknown", basis = "none",
                    reason = "No fat figure for this snack, so it can't be judged")),
        ),
        totals = mapOf("kcal" to 1145.0, "fat_g" to 36.9), entryCount = 4, unresolvedCount = 1,
    )
    val mealsEmptyDay = LogDayOut(day = TODAY)
    val targets = PrepTargetsOut(ok = true, targetKcal = 2310, proteinG = 150)
    val noTargets = PrepTargetsOut(ok = false, reason = "Add your height and birth date to get an energy target.")
    val recents = listOf(
        RecentEntryOut(label = "Greek yogurt", foodId = 11, quantity = 170.0, unit = "g", usualSlot = "breakfast", times = 9),
        RecentEntryOut(label = "Chicken & rice bowl", recipeId = 3, servings = 1.0, usualSlot = "lunch", times = 6),
        RecentEntryOut(label = "Apple", foodId = 12, quantity = 1.0, unit = "piece", usualSlot = "snack", times = 5),
    )

    // ── Prep ──
    val prepPlan = PrepPlanOut(
        id = 4, startDay = "2026-09-21", days = 5, headline = "Chicken, rice and roast veg",
        components = listOf(
            PrepComponentOut(1, "Baked chicken breast", "protein", quantity = 1200.0, unit = "g", portions = 6,
                done = true, gramsPerPortion = 200.0, prepNote = "Season, 200°C for 22 minutes."),
            PrepComponentOut(2, "Brown rice", "grain", quantity = 3.0, unit = "cup", portions = 6, done = true,
                gramsPerPortion = 180.0),
            PrepComponentOut(3, "Roast broccoli", "veg", quantity = 900.0, unit = "g", portions = 6,
                gramsPerPortion = 150.0, prepNote = "Same tray, last 15 minutes."),
            PrepComponentOut(4, "Lemon yogurt sauce", "sauce", quantity = 300.0, unit = "g", portions = 6,
                gramsPerPortion = 50.0, unresolved = true, unresolvedReason = "no match for \"lemon yogurt sauce\""),
        ),
        schedule = listOf("Mon" to "2026-09-21", "Tue" to "2026-09-22", "Wed" to "2026-09-23",
            "Thu" to "2026-09-24", "Fri" to "2026-09-25").mapIndexed { i, (wd, d) ->
            PrepDayOut(
                day = d, weekday = wd,
                plannedKcal = listOf(1150.0, 1480.0, 1320.0, 900.0, 1400.0)[i], budgetKcal = 1500.0,
                meals = listOf(
                    PrepMealOut(id = 10L + i * 2, day = d, slot = "lunch", name = "Chicken rice bowl",
                        status = if (i == 0) "accepted" else "suggested",
                        uses = listOf(PrepMealUse(1, 1.0), PrepMealUse(2, 1.0)), estKcal = 620.0, estProteinG = 52.0,
                        estFatG = 9.0, fatAssessment = FatAssessment(fatG = 9.0, verdict = "ok", basis = "target", targetG = 20.0)),
                    PrepMealOut(id = 11L + i * 2, day = d, slot = "dinner", name = "Chicken, broccoli & sauce",
                        status = if (i == 3) "eating_out" else "suggested",
                        uses = listOf(PrepMealUse(1, 1.0), PrepMealUse(3, 1.0), PrepMealUse(4, 1.0)),
                        estKcal = 560.0, estProteinG = 48.0, estFatG = if (i == 2) 24.0 else null,
                        fatAssessment = if (i == 2) FatAssessment(fatG = 24.0, verdict = "high", basis = "target", targetG = 20.0)
                        else FatAssessment(verdict = "unknown"),
                        unresolvedCount = 1, assemblyNote = "Warm the chicken, spoon the sauce over cold."),
                ),
            )
        },
        budgets = PrepBudgets(slots = listOf("lunch", "dinner"), coveredShare = 0.65, uncoveredShare = 0.35, uncoveredKcal = 810),
        warnings = listOf("Chicken on Friday is day 5 — past the 4 days cooked chicken keeps. Freeze two portions."),
    )
}
