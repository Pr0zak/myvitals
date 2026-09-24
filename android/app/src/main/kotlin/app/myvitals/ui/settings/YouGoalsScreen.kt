package app.myvitals.ui.settings

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.StepsSchedule
import app.myvitals.sync.StepsScheduleIn
import app.myvitals.ui.neon.NeonErrorBanner
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * You & goals (SETTINGS-C). Mirrors web `settings/SettingsYou.vue`.
 *
 * The phone had no way to edit the profile, goals or fasting preferences at
 * all — the weekday step editor told you to "leave blank to use your usual
 * goal" with no way to set that goal. Everything the web profile pane edits
 * is here now, plus the workout reminder, which is phone-only because it is
 * a phone notification.
 *
 * One save model for the whole page: edits accumulate in a draft, a sticky
 * Save / Discard bar appears while the draft differs from what loaded, and
 * Save sends ONLY the changed fields (see [profileDiff]). Leaving with
 * unsaved changes asks first, instead of dropping them silently.
 */
@Composable
fun YouGoalsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val imperial = settings.unitsImperial
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    var schedule by remember { mutableStateOf<StepsSchedule?>(null) }
    var base by remember { mutableStateOf<YouGoalsForm?>(null) }
    var draft by remember { mutableStateOf<YouGoalsForm?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var saveError by remember { mutableStateOf<String?>(null) }
    var confirmLeave by remember { mutableStateOf(false) }

    suspend fun load() {
        try {
            coroutineScope {
                val p = async { settings.call { profile() } }
                // The schedule is optional; a failure there must not block
                // editing the profile.
                val s = async { runCatching { settings.call { stepsSchedule() } }.getOrNull() }
                val prof = p.await()
                val sched = s.await()
                profile = prof; schedule = sched
                val form = youGoalsFormFrom(prof, sched, imperial)
                base = form; draft = form
                error = null
            }
        } catch (e: Exception) {
            Timber.w(e, "you & goals load failed")
            error = e.settingsMessage()
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    val dirty = base != null && draft != base
    BackHandler(enabled = dirty) { confirmLeave = true }
    if (confirmLeave) {
        SettingsConfirm(
            title = "Discard your changes?",
            text = "You have edits on this page that haven't been saved.",
            confirmLabel = "Discard",
            onConfirm = { draft = base; onBack() },
            onDismiss = { confirmLeave = false },
        )
    }

    YouGoalsContent(
        draft = draft,
        base = base,
        schedule = schedule,
        imperial = imperial,
        estimatedMaxHr = profile?.derived?.maxHrEstimated,
        autoRestingHr = profile?.derived?.restingHrBaselineAuto,
        loading = loading,
        refreshing = refreshing,
        error = error,
        saving = saving,
        saveError = saveError,
        onChange = { draft = it; saveError = null },
        onDiscard = { draft = base; saveError = null },
        onSave = save@{
            val b = base ?: return@save
            val d = draft ?: return@save
            scope.launch {
                saving = true; saveError = null
                try {
                    val body = profileDiff(b, d, imperial, profile?.extra?.fastingPrefs)
                    if (body.isNotEmpty()) {
                        settings.call { putProfilePartial(BackendClient.jsonBody(body)) }
                    }
                    stepsScheduleDiff(b, d)?.let { sched ->
                        settings.call { putStepsSchedule(StepsScheduleIn(sched)) }
                    }
                    Timber.i("you & goals saved: %s", body.keys)
                    load()   // re-read so the page shows what the server holds
                } catch (e: Exception) {
                    Timber.w(e, "you & goals save failed")
                    saveError = e.settingsMessage()
                } finally {
                    saving = false
                }
            }
        },
        onBack = { if (dirty) confirmLeave = true else onBack() },
        onRefresh = {
            // A refresh would overwrite the draft; with edits pending it is
            // declined rather than silently discarding them.
            if (!dirty) scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
    )
}

@Composable
fun YouGoalsContent(
    draft: YouGoalsForm?,
    base: YouGoalsForm?,
    schedule: StepsSchedule?,
    imperial: Boolean,
    estimatedMaxHr: Int?,
    autoRestingHr: Double?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    saving: Boolean,
    saveError: String?,
    onChange: (YouGoalsForm) -> Unit,
    onDiscard: () -> Unit,
    onSave: () -> Unit,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(0.dp),
) {
    val dirty = draft != null && base != null && draft != base
    val errors = draft?.let { validateYouGoals(it, imperial) }.orEmpty()
    Box(Modifier.fillMaxSize()) {
        NeonScreen(
            title = "You & goals",
            contentPadding = contentPadding,
            onBack = onBack,
            refreshing = refreshing,
            onRefresh = onRefresh,
        ) {
            val f = draft
            if (f == null) {
                if (error != null && !loading) {
                    NeonErrorBanner(error, title = "Couldn't load your profile") { onRefresh() }
                } else {
                    SettingsSkeleton(listOf(260.dp, 180.dp, 200.dp))
                }
                return@NeonScreen
            }
            if (error != null) {
                NeonErrorBanner(error, title = "Couldn't refresh — showing what loaded earlier") { onRefresh() }
            }
            val wUnit = if (imperial) "lb" else "kg"

            NeonEyebrow("About you")
            SettingsCard {
                SettingsTextField(
                    "Birth date", f.birthDate, { onChange(f.copy(birthDate = it)) },
                    placeholder = "YYYY-MM-DD", keyboardType = KeyboardType.Number,
                    help = "Used for age-based heart-rate zones and training rest.",
                    error = errors["birthDate"],
                )
                SettingsChoice("Sex", SEXES, f.sex, { onChange(f.copy(sex = it)) })
                if (imperial) {
                    Row(Modifier.fillMaxWidth()) {
                        SettingsTextField(
                            "Height", f.heightMain, { onChange(f.copy(heightMain = it)) },
                            modifier = Modifier.weight(1f), suffix = "ft",
                            keyboardType = KeyboardType.Number, error = errors["height"],
                        )
                        SettingsTextField(
                            " ", f.heightInches, { onChange(f.copy(heightInches = it)) },
                            modifier = Modifier.weight(1f), suffix = "in",
                            keyboardType = KeyboardType.Number,
                        )
                    }
                } else {
                    SettingsTextField(
                        "Height", f.heightMain, { onChange(f.copy(heightMain = it)) },
                        suffix = "cm", keyboardType = KeyboardType.Decimal, error = errors["height"],
                    )
                }
                SettingsChoice("Activity level", ACTIVITY_LEVELS, f.activityLevel,
                    { onChange(f.copy(activityLevel = it)) })
                SettingsTextField(
                    "Max heart rate", f.maxHr, { onChange(f.copy(maxHr = it)) },
                    suffix = "bpm", keyboardType = KeyboardType.Number,
                    placeholder = estimatedMaxHr?.let { "est. $it" },
                    help = "Every heart-rate zone is a share of this. Leave blank to use the age estimate.",
                    error = errors["maxHr"],
                )
                SettingsTextField(
                    "Resting heart rate baseline", f.restingHr, { onChange(f.copy(restingHr = it)) },
                    suffix = "bpm", keyboardType = KeyboardType.Decimal,
                    placeholder = autoRestingHr?.let { "auto ${num(it, 0)}" },
                    help = "Leave blank to use the baseline measured from your data.",
                    error = errors["restingHr"],
                )
            }

            NeonEyebrow("Goals")
            SettingsCard {
                SettingsTextField(
                    "Weight goal", f.weightGoal, { onChange(f.copy(weightGoal = it)) },
                    suffix = wUnit, keyboardType = KeyboardType.Decimal,
                    error = errors["weightGoal"],
                )
                SettingsTextField(
                    "Daily steps goal", f.stepsGoal, { onChange(f.copy(stepsGoal = it)) },
                    suffix = "steps", keyboardType = KeyboardType.Number, placeholder = "10000",
                    help = "Your usual goal. Days below can differ from it.",
                    error = errors["stepsGoal"],
                )
                if (schedule != null && f.stepsByDay.isNotEmpty()) {
                    StepsByDayEditor(f, schedule, errors) { onChange(it) }
                } else {
                    SettingsNote("The per-day step goals couldn't be loaded.", color = NeonMV.Amber)
                }
                SettingsDivider()
                SettingsTextField(
                    "Sleep goal", f.sleepGoalH, { onChange(f.copy(sleepGoalH = it)) },
                    suffix = "hours", keyboardType = KeyboardType.Decimal, placeholder = "8",
                    error = errors["sleepGoalH"],
                )
            }

            NeonEyebrow("Workout reminder")
            SettingsCard {
                SettingsSwitchRow(
                    "Daily reminder",
                    "A notification on workout days with the split and first exercises. On this phone only.",
                    f.reminderEnabled, { onChange(f.copy(reminderEnabled = it)) },
                )
                if (f.reminderEnabled) {
                    SettingsDivider()
                    HourPicker("Time", f.reminderHour, 5..21, { onChange(f.copy(reminderHour = it)) })
                }
            }

            NeonEyebrow("Fasting")
            SettingsCard {
                SettingsChoice("Default protocol", FASTING_PROTOCOLS, f.fastProtocol,
                    { onChange(f.copy(fastProtocol = it)) }, accent = NeonMV.Cyan)
                SettingsDivider()
                SettingsSwitchRow(
                    "Scheduled mode",
                    "Start and end fasts automatically at your eating-window edges. Starting one by hand always wins.",
                    f.fastScheduled, { onChange(f.copy(fastScheduled = it)) },
                )
                HourPicker("Eating window starts", f.fastEatStart, 0..23,
                    { onChange(f.copy(fastEatStart = it)) }, enabled = f.fastScheduled)
                HourPicker("Eating window ends", f.fastEatEnd, 1..24,
                    { onChange(f.copy(fastEatEnd = it)) }, enabled = f.fastScheduled)
                errors["fastWindow"]?.let { SettingsNote(it, color = NeonMV.Amber) }
                SettingsDivider()
                SettingsSwitchRow(
                    "Milestone notifications",
                    "Ketosis, autophagy and the other stages, on this phone.",
                    f.fastNotifications, { onChange(f.copy(fastNotifications = it)) },
                )
            }
            // Room for the sticky bar so it never hides the last control.
            Spacer(Modifier.height(if (dirty || saveError != null) 110.dp else 24.dp))
        }

        if (dirty || saveError != null) {
            SaveBar(
                saving = saving,
                canSave = dirty && errors.isEmpty(),
                error = saveError ?: if (errors.isNotEmpty()) "Fix the highlighted fields to save" else null,
                onDiscard = onDiscard,
                onSave = onSave,
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
}

/**
 * DOW-1 per-weekday overrides, under the base goal they fall back to.
 * Every field starts empty rather than pre-filled with the base — a
 * pre-filled field would write seven overrides the user never asked for.
 */
@Composable
private fun StepsByDayEditor(
    f: YouGoalsForm,
    schedule: StepsSchedule,
    errors: Map<String, String>,
    onChange: (YouGoalsForm) -> Unit,
) {
    val baseLabel = f.stepsGoal.trim().toIntOrNull() ?: schedule.base
    Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
        Text("Steps goal by day", color = NeonMV.Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        Text("Leave a day blank to use your usual goal (%,d).".format(baseLabel),
            color = NeonMV.Muted, fontSize = 11.sp)
    }
    for (chunk in schedule.weekdays.chunked(4)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
            for (day in chunk) {
                SettingsTextField(
                    day.replaceFirstChar { it.uppercase() },
                    f.stepsByDay[day].orEmpty(),
                    { v -> onChange(f.copy(stepsByDay = f.stepsByDay + (day to v.filter(Char::isDigit)))) },
                    modifier = Modifier.weight(1f),
                    horizontalPadding = 4.dp,
                    placeholder = "%,d".format(baseLabel).replace(",000", "k"),
                    keyboardType = KeyboardType.Number,
                    error = errors["steps_$day"],
                )
            }
            repeat(4 - chunk.size) { Spacer(Modifier.weight(1f)) }
        }
    }
    SettingsNote("Today's goal on the server: %,d steps.".format(schedule.effectiveToday))
}

@Composable
private fun SaveBar(
    saving: Boolean,
    canSave: Boolean,
    error: String?,
    onDiscard: () -> Unit,
    onSave: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp)
    Column(
        modifier
            .fillMaxWidth()
            .background(NeonMV.CardHigh, shape)
            .border(1.dp, NeonMV.Line, shape)
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        if (error != null) {
            Text(error, color = NeonMV.Amber, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp))
        }
        Row(verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Unsaved changes", color = NeonMV.Ink, fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            NeonButton("Discard", onDiscard, filled = false, accent = NeonMV.Muted, enabled = !saving)
            NeonButton(if (saving) "Saving…" else "Save", onSave, enabled = canSave && !saving)
        }
    }
}
