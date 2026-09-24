package app.myvitals.ui.settings

import app.myvitals.sync.ProfileExtra
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.StepsSchedule
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SETTINGS-C — a save sends ONLY what changed. The server applies only the
 * fields it is sent (d22c3dd); these pin the client half of that contract.
 * Invented values throughout.
 */
class YouGoalsFormTest {
    private val profile = ProfileResponse(
        birthDate = "1985-04-23", sex = "male", heightCm = 180.0,
        weightGoalKg = 80.0, restingHrBaseline = 55.0, maxHr = 185.0,
        activityLevel = "moderate",
        extra = ProfileExtra(
            stepsGoal = 9000, sleepGoalH = 7.5,
            workoutReminderEnabled = false, workoutReminderHour = 8,
            fastingPrefs = mapOf(
                "default_protocol" to "16:8", "religious_calendar" to "lent",
                "eating_window_start_h" to 12.0, "eating_window_end_h" to 20.0,
            ),
        ),
    )
    private val sched = StepsSchedule(
        base = 9000, schedule = mapOf("sat" to 6000),
        weekdays = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    )

    @Test fun unchangedFormSendsNothing() {
        val f = youGoalsFormFrom(profile, sched, imperial = true)
        assertTrue(profileDiff(f, f, true, profile.extra?.fastingPrefs).isEmpty())
        assertNull(stepsScheduleDiff(f, f))
    }

    @Test fun oneEditSendsOneField() {
        val f = youGoalsFormFrom(profile, sched, imperial = false)
        val d = profileDiff(f, f.copy(maxHr = "190"), false, null)
        assertEquals(mapOf("max_hr" to 190.0), d)
    }

    @Test fun clearingAFieldSendsExplicitNull() {
        val f = youGoalsFormFrom(profile, sched, imperial = false)
        val d = profileDiff(f, f.copy(weightGoal = ""), false, null)
        assertTrue(d.containsKey("weight_goal_kg"))
        assertNull(d["weight_goal_kg"])
    }

    @Test fun imperialRoundTripDoesNotRewriteHeight() {
        // 180 cm shows as 5 ft 11 in; saving untouched must not send 180.34.
        val f = youGoalsFormFrom(profile, sched, imperial = true)
        assertEquals("5", f.heightMain); assertEquals("11", f.heightInches)
        assertFalse(profileDiff(f, f.copy(sex = "other"), true, null).containsKey("height_cm"))
        val d = profileDiff(f, f.copy(heightInches = "10"), true, null)
        assertEquals((5 * 12 + 10) * 2.54, d["height_cm"] as Double, 1e-9)
    }

    @Test fun weightGoalConvertsFromPounds() {
        val f = youGoalsFormFrom(profile, sched, imperial = true)
        val d = profileDiff(f, f.copy(weightGoal = "170"), true, null)
        assertEquals(170 * 0.45359237, d["weight_goal_kg"] as Double, 1e-9)
    }

    @Test fun extraCarriesOnlyChangedKeys() {
        val f = youGoalsFormFrom(profile, sched, imperial = false)
        val d = profileDiff(f, f.copy(sleepGoalH = "8"), false, null)
        assertEquals(mapOf("extra" to mapOf("sleep_goal_h" to 8.0)), d)
    }

    @Test fun fastingPrefsPreserveUnmodelledKeys() {
        val f = youGoalsFormFrom(profile, sched, imperial = false)
        val d = profileDiff(f, f.copy(fastProtocol = "18:6"), false, profile.extra?.fastingPrefs)
        @Suppress("UNCHECKED_CAST")
        val fp = (d["extra"] as Map<String, Any?>)["fasting_prefs"] as Map<String, Any?>
        assertEquals("18:6", fp["default_protocol"])
        assertEquals("lent", fp["religious_calendar"])   // web-only key kept
        assertEquals(12, fp["eating_window_start_h"])
    }

    @Test fun stepsScheduleIsSparse() {
        val f = youGoalsFormFrom(profile, sched, imperial = false)
        assertEquals("6000", f.stepsByDay["sat"]); assertEquals("", f.stepsByDay["mon"])
        val d = stepsScheduleDiff(f, f.copy(stepsByDay = f.stepsByDay + ("sat" to "")))!!
        assertNull(d["sat"]); assertNull(d["mon"])
    }

    @Test fun validationBlocksNonsense() {
        val f = youGoalsFormFrom(profile, sched, imperial = false)
        assertTrue(validateYouGoals(f, false).isEmpty())
        val bad = f.copy(birthDate = "23/04/1985", maxHr = "abc", sleepGoalH = "30")
        val e = validateYouGoals(bad, false)
        assertTrue(e.keys.containsAll(listOf("birthDate", "maxHr", "sleepGoalH")))
    }
}
