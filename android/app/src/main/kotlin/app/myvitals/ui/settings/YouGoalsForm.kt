package app.myvitals.ui.settings

import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.StepsSchedule
import java.time.LocalDate
import kotlin.math.roundToInt

/**
 * SETTINGS-C — the You & goals edit model, kept free of Compose so the one
 * thing that must never regress is unit-testable: a save sends ONLY what
 * the user changed.
 *
 * Why that matters: `PUT /profile` used to assign every field, so a client
 * that did not model one erased it on each save (the phone's reminder toggle
 * nulled the home location; every web save nulled the fasting target).
 * d22c3dd made the server apply only the fields it is SENT. That protection
 * only holds if the client stops sending the rest, so [profileDiff] compares
 * the form against the form it started from and emits nothing else. An
 * emptied field is sent as an explicit null, which the server treats as
 * "clear" — distinct from absent, which means "leave alone".
 *
 * Fields are held as the strings the user typed, in the user's units. The
 * comparison is on those strings, so opening the page and saving does not
 * round-trip 180.3 cm through feet and inches into 180.34 cm.
 */
data class YouGoalsForm(
    val birthDate: String = "",
    val sex: String? = null,
    /** Metric: centimetres. Imperial: feet. */
    val heightMain: String = "",
    /** Imperial only: inches. */
    val heightInches: String = "",
    val activityLevel: String? = null,
    val maxHr: String = "",
    val restingHr: String = "",
    /** In the user's weight unit. */
    val weightGoal: String = "",
    val stepsGoal: String = "",
    val sleepGoalH: String = "",
    val reminderEnabled: Boolean = false,
    val reminderHour: Int = 8,
    val fastProtocol: String = "16:8",
    val fastScheduled: Boolean = false,
    val fastEatStart: Int = 12,
    val fastEatEnd: Int = 20,
    val fastNotifications: Boolean = true,
    /** Per-weekday step overrides; blank = use the base goal (DOW-1). */
    val stepsByDay: Map<String, String> = emptyMap(),
)

private const val KG_PER_LB = 0.45359237   // same constant as data/Units.kt
private const val CM_PER_IN = 2.54

internal fun num(d: Double?, digits: Int = 1): String {
    if (d == null) return ""
    val r = "%.${digits}f".format(java.util.Locale.US, d).trimEnd('0').trimEnd('.')
    return r
}

/** Build the form a page opens with. */
fun youGoalsFormFrom(p: ProfileResponse, sched: StepsSchedule?, imperial: Boolean): YouGoalsForm {
    val fp = p.extra?.fastingPrefs.orEmpty()
    val (hMain, hIn) = when {
        p.heightCm == null -> "" to ""
        imperial -> {
            val totalIn = (p.heightCm / CM_PER_IN).roundToInt()
            (totalIn / 12).toString() to (totalIn % 12).toString()
        }
        else -> num(p.heightCm) to ""
    }
    return YouGoalsForm(
        birthDate = p.birthDate.orEmpty(),
        sex = p.sex,
        heightMain = hMain,
        heightInches = hIn,
        activityLevel = p.activityLevel,
        maxHr = num(p.maxHr, 0),
        restingHr = num(p.restingHrBaseline),
        weightGoal = num(p.weightGoalKg?.let { if (imperial) it / KG_PER_LB else it }),
        stepsGoal = p.extra?.stepsGoal?.toString().orEmpty(),
        sleepGoalH = num(p.extra?.sleepGoalH),
        reminderEnabled = p.extra?.workoutReminderEnabled == true,
        reminderHour = p.extra?.workoutReminderHour ?: 8,
        fastProtocol = fp["default_protocol"] as? String ?: "16:8",
        fastScheduled = fp["scheduled_mode_enabled"] as? Boolean ?: false,
        fastEatStart = (fp["eating_window_start_h"] as? Number)?.toInt() ?: 12,
        fastEatEnd = (fp["eating_window_end_h"] as? Number)?.toInt() ?: 20,
        fastNotifications = fp["notifications_enabled"] as? Boolean ?: true,
        stepsByDay = sched?.let { s -> s.weekdays.associateWith { s.schedule[it]?.toString() ?: "" } }
            ?: emptyMap(),
    )
}

/** Field → message. Save is disabled while this is non-empty. */
fun validateYouGoals(f: YouGoalsForm, imperial: Boolean): Map<String, String> {
    val e = linkedMapOf<String, String>()
    fun bad(v: String) = v.isNotBlank() && v.trim().toDoubleOrNull() == null
    if (f.birthDate.isNotBlank()) {
        val d = runCatching { LocalDate.parse(f.birthDate.trim()) }.getOrNull()
        if (d == null) e["birthDate"] = "Use YYYY-MM-DD, e.g. 1985-04-23"
        else if (d.isAfter(LocalDate.now())) e["birthDate"] = "That date is in the future"
    }
    if (bad(f.heightMain) || bad(f.heightInches)) e["height"] = "Numbers only"
    if (bad(f.maxHr)) e["maxHr"] = "Numbers only"
    else f.maxHr.trim().toDoubleOrNull()?.let { if (it !in 100.0..240.0) e["maxHr"] = "Between 100 and 240" }
    if (bad(f.restingHr)) e["restingHr"] = "Numbers only"
    else f.restingHr.trim().toDoubleOrNull()?.let { if (it !in 25.0..120.0) e["restingHr"] = "Between 25 and 120" }
    if (bad(f.weightGoal)) e["weightGoal"] = "Numbers only"
    if (f.stepsGoal.isNotBlank() && f.stepsGoal.trim().toIntOrNull() == null) e["stepsGoal"] = "Whole number of steps"
    if (bad(f.sleepGoalH)) e["sleepGoalH"] = "Numbers only"
    else f.sleepGoalH.trim().toDoubleOrNull()?.let { if (it !in 3.0..14.0) e["sleepGoalH"] = "Between 3 and 14 hours" }
    if (f.fastScheduled && f.fastEatEnd <= f.fastEatStart) e["fastWindow"] = "The window must end after it starts"
    for ((day, v) in f.stepsByDay) if (v.isNotBlank() && v.trim().toIntOrNull() == null) e["steps_$day"] = "Whole number"
    return e
}

private fun dbl(s: String): Double? = s.trim().toDoubleOrNull()

/**
 * The PUT /profile body: ONLY changed fields, explicit null for a cleared
 * one. Empty map = nothing to send. [existingFastingPrefs] is merged under
 * the edited keys so a key this build does not model (the religious
 * calendar, set on the web) is echoed back untouched — `extra` merges one
 * level deep on the server, so `fasting_prefs` is replaced as a whole.
 */
fun profileDiff(
    base: YouGoalsForm,
    draft: YouGoalsForm,
    imperial: Boolean,
    existingFastingPrefs: Map<String, Any?>?,
): Map<String, Any?> {
    val out = linkedMapOf<String, Any?>()
    if (draft.birthDate != base.birthDate) out["birth_date"] = draft.birthDate.trim().ifBlank { null }
    if (draft.sex != base.sex) out["sex"] = draft.sex
    if (draft.heightMain != base.heightMain || draft.heightInches != base.heightInches) {
        out["height_cm"] = if (imperial) {
            val ft = dbl(draft.heightMain)
            val inch = dbl(draft.heightInches)
            if (ft == null && inch == null) null
            else ((ft ?: 0.0) * 12 + (inch ?: 0.0)) * CM_PER_IN
        } else dbl(draft.heightMain)
    }
    if (draft.activityLevel != base.activityLevel) out["activity_level"] = draft.activityLevel
    if (draft.maxHr != base.maxHr) out["max_hr"] = dbl(draft.maxHr)
    if (draft.restingHr != base.restingHr) out["resting_hr_baseline"] = dbl(draft.restingHr)
    if (draft.weightGoal != base.weightGoal) {
        out["weight_goal_kg"] = dbl(draft.weightGoal)?.let { if (imperial) it * KG_PER_LB else it }
    }

    val extra = linkedMapOf<String, Any?>()
    if (draft.stepsGoal != base.stepsGoal) extra["steps_goal"] = draft.stepsGoal.trim().toIntOrNull()
    // `sleep_goal_h` — since d22c3dd the server also mirrors it into the
    // `sleep_target_h` column analytics read, and syncs the sleep goal.
    if (draft.sleepGoalH != base.sleepGoalH) extra["sleep_goal_h"] = dbl(draft.sleepGoalH)
    if (draft.reminderEnabled != base.reminderEnabled) extra["workout_reminder_enabled"] = draft.reminderEnabled
    if (draft.reminderHour != base.reminderHour) extra["workout_reminder_hour"] = draft.reminderHour
    val fastChanged = draft.fastProtocol != base.fastProtocol ||
        draft.fastScheduled != base.fastScheduled ||
        draft.fastEatStart != base.fastEatStart ||
        draft.fastEatEnd != base.fastEatEnd ||
        draft.fastNotifications != base.fastNotifications
    if (fastChanged) {
        extra["fasting_prefs"] = LinkedHashMap(existingFastingPrefs.orEmpty()).apply {
            put("default_protocol", draft.fastProtocol)
            put("scheduled_mode_enabled", draft.fastScheduled)
            put("eating_window_start_h", draft.fastEatStart)
            put("eating_window_end_h", draft.fastEatEnd)
            put("notifications_enabled", draft.fastNotifications)
        }
    }
    if (extra.isNotEmpty()) out["extra"] = extra
    return out
}

/** The PUT /profile/steps-schedule body, or null when unchanged. Sparse:
 *  a blank day is sent as null ("use the base goal"). */
fun stepsScheduleDiff(base: YouGoalsForm, draft: YouGoalsForm): Map<String, Int?>? {
    if (draft.stepsByDay == base.stepsByDay) return null
    return draft.stepsByDay.mapValues { (_, v) -> v.trim().toIntOrNull() }
}

val FASTING_PROTOCOLS = listOf(
    "16:8" to "16:8", "18:6" to "18:6", "20:4" to "20:4", "omad" to "OMAD",
    "extended_24" to "24 h", "extended_36" to "36 h", "extended_48" to "48 h",
    "extended_72" to "72 h",
)

val ACTIVITY_LEVELS = listOf(
    "sedentary" to "Sedentary", "light" to "Light", "moderate" to "Moderate",
    "active" to "Active", "athlete" to "Athlete",
)

val SEXES = listOf("male" to "Male", "female" to "Female", "other" to "Other")
