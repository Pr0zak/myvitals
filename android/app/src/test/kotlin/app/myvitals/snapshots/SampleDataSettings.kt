package app.myvitals.snapshots

import app.myvitals.sync.AiConfigOut
import app.myvitals.sync.DataHealth
import app.myvitals.sync.DataHealthOverview
import app.myvitals.sync.ImportJob
import app.myvitals.sync.IntegrationHealth
import app.myvitals.sync.ProfileDerived
import app.myvitals.sync.ProfileExtra
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.ServerVersion
import app.myvitals.sync.StepsSchedule
import app.myvitals.sync.StreamHealth
import app.myvitals.sync.UpdateCheck
import app.myvitals.sync.UpdateCronStatus
import app.myvitals.ui.settings.LocalPrefs
import app.myvitals.ui.settings.PhoneSyncFacts
import app.myvitals.ui.settings.SettingsHomeData
import java.time.Instant

/**
 * Invented sample data for the Settings screenshot tests (SETTINGS-C). The
 * repo is public: every value, address and version here is made up.
 */
object SampleDataSettings {
    val NOW: Instant = Instant.parse("2026-09-22T17:00:00Z")

    private val streams = listOf(
        StreamHealth("heart_rate", "Heart rate", "continuous", "watch", "2026-09-22T16:48:00Z", 0.2, "ok"),
        StreamHealth("steps", "Steps", "continuous", "watch", "2026-09-22T16:40:00Z", 0.33, "ok",
            canonicalSourceOnly = true),
        StreamHealth("sleep", "Sleep", "nightly", "watch", "2026-09-22T12:10:00Z", 4.8, "ok"),
        StreamHealth("weight", "Weight", "ad_hoc", "scale", "2026-08-30T13:00:00Z", 556.0, "ad_hoc"),
        StreamHealth("bp", "Blood pressure", "ad_hoc", "", null, null, "not_configured"),
    )
    private val integrations = listOf(
        IntegrationHealth("google_health", "Google Health", true, "2026-09-22T16:30:00Z", 0.5,
            status = "ok", lastItemAt = "2026-09-22T16:00:00Z", itemAgeHours = 1.0),
        IntegrationHealth("strava", "Strava", true, "2026-09-21T09:00:00Z", 32.0,
            status = "ok", lastItemAt = "2026-09-20T15:00:00Z", itemAgeHours = 50.0),
        IntegrationHealth("concept2", "Concept2", false, status = "not_configured"),
    )

    val healthOk = DataHealth(
        streams = streams, integrations = integrations, problemKeys = emptyList(), ok = true,
        overview = DataHealthOverview("positive", "Everything is arriving", 0, 2, 2,
            "2026-09-22T16:48:00Z"),
    )

    val healthCaution = DataHealth(
        streams = streams.map {
            if (it.key == "sleep") it.copy(status = "stale", ageHours = 41.0, lastAt = "2026-09-21T00:00:00Z") else it
        },
        integrations = integrations.map {
            if (it.key == "strava") it.copy(
                status = "error", lastError = "401 Unauthorized from strava.com",
                lastErrorKind = "auth", action = "Reconnect Strava on the web", needsReconnect = true,
            ) else it
        },
        problemKeys = listOf("sleep", "strava"), ok = false,
        overview = DataHealthOverview("caution", "Sleep not updated for 41h (+1 more)", 2, 1, 2,
            "2026-09-22T11:05:00Z"),
    )

    val profile = ProfileResponse(
        birthDate = "1984-03-10", sex = "male", heightCm = 178.0, weightGoalKg = 79.0,
        restingHrBaseline = null, maxHr = null, activityLevel = "moderate",
        extra = ProfileExtra(
            stepsGoal = 9000, sleepGoalH = 7.5, workoutReminderEnabled = true, workoutReminderHour = 7,
            fastingPrefs = mapOf("default_protocol" to "16:8", "scheduled_mode_enabled" to false,
                "eating_window_start_h" to 12.0, "eating_window_end_h" to 20.0,
                "notifications_enabled" to true),
        ),
        derived = ProfileDerived(age = 42, maxHrEstimated = 180, restingHrBaselineAuto = 57.4),
    )

    val schedule = StepsSchedule(
        base = 9000, schedule = mapOf("sat" to 6000, "sun" to 6000),
        weekdays = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
        effectiveToday = 9000,
    )

    val ai = AiConfigOut(enabled = true, apiKeySet = true, model = "claude-haiku-4-5-20251001",
        dailyCallLimit = 30, callsToday = 4, weeklyDigestEnabled = true, tone = "supportive")

    val version = ServerVersion("0.46.1", "abc1234", "2026-09-20T10:00:00Z")
    val updateNone = UpdateCheck(current = "0.46.1", latest = "0.46.1", updateAvailable = false)
    val updateAvail = UpdateCheck(current = "0.46.1", latest = "0.47.0", updateAvailable = true)

    val cron = UpdateCronStatus(
        logPresent = true, logModifiedAt = "2026-09-22T16:45:00Z", staleSeconds = 900,
        cronHealthy = true, triggerPending = false,
        tail = listOf(
            "2026-09-22T16:15:01 check: :latest digest unchanged",
            "2026-09-22T16:30:01 check: :latest digest unchanged",
            "2026-09-22T16:45:01 check: :latest digest unchanged",
            "2026-09-22T16:45:01 heartbeat ok",
        ),
    )

    val job = ImportJob(id = 3, kind = "google_takeout", filename = "takeout-example.zip",
        status = "done", startedAt = "2026-09-19T20:00:00Z", totalRows = 48_210)

    val home = SettingsHomeData(
        health = healthOk, version = version, update = updateNone, profile = profile,
        ai = ai, lastImport = job, jobsKnown = true,
    )

    val local = LocalPrefs(
        imperial = true, timeFormat = "auto", permissionsLost = false,
        lastSuccess = Instant.parse("2026-09-22T16:48:00Z"), configured = true,
    )

    val facts = PhoneSyncFacts(
        hcAvailable = true, permsGranted = true, permissionsLost = false,
        lastAttempt = Instant.parse("2026-09-22T16:48:00Z"),
        lastSuccess = Instant.parse("2026-09-22T16:48:00Z"),
    )
}
