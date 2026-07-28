package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.EquipmentPayload
import app.myvitals.sync.ProgramConfig
import app.myvitals.sync.ProgramLiftState
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.TrainingPreferences
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.launch
import timber.log.Timber

private val SCHEME_LABELS = mapOf(
    "greyskull" to "Greyskull LP", "linear" to "Linear", "double" to "Double",
)

// Mirror the backend PROGRAM_SCHEME_DEFAULTS so a lift seeded on the
// phone matches what the server would produce.
private fun applyScheme(lift: ProgramLiftState, scheme: String): ProgramLiftState = when (scheme) {
    "greyskull" -> lift.copy(
        scheme = scheme, sets = 3, repsLow = 5, repsHigh = 5, amrapLastSet = true,
        incrementLb = 5.0, failsBeforeDeload = 1, deloadPct = 0.10, restS = 180)
    "double" -> lift.copy(
        scheme = scheme, sets = 3, repsLow = 8, repsHigh = 12, amrapLastSet = false,
        incrementLb = 5.0, failsBeforeDeload = 3, deloadPct = 0.10, restS = 150)
    else -> lift.copy(
        scheme = scheme, sets = 3, repsLow = 5, repsHigh = 5, amrapLastSet = false,
        incrementLb = 5.0, failsBeforeDeload = 3, deloadPct = 0.10, restS = 180)
}

private fun fmtLb(x: Double): String =
    if (x == x.toLong().toDouble()) x.toLong().toString() else x.toString()

@Composable
fun StrengthTrainingPrefsScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    val repo = remember(settings) { StrengthRepository(context, settings) }

    val neon = settings.neonShellEnabled
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val good = if (neon) NeonMV.Lime else MV.Green
    val bad = if (neon) NeonMV.Bad else MV.Red
    val onAccent = if (neon) NeonMV.OnAccent else MV.OnSurface

    var equipment by remember { mutableStateOf<EquipmentPayload?>(null) }
    var catalog by remember { mutableStateOf<List<StrengthExerciseInfo>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    val equipmentType = remember { EquipmentPayload::class.java as java.lang.reflect.Type }

    LaunchedEffect(Unit) {
        app.myvitals.data.JsonCache.read<EquipmentPayload>(
            context, "strength_equipment", equipmentType,
        )?.let {
            equipment = it.value
            loading = false
        }
        try {
            val fresh = repo.equipment().payload
            equipment = fresh
            app.myvitals.data.JsonCache.write(
                context, "strength_equipment", equipmentType, fresh,
            )
        } catch (e: Exception) {
            Timber.w(e, "load equipment failed")
            if (equipment == null) error = e.message?.take(160)
        } finally { loading = false }
        // Catalog powers the program-lift picker (best-effort).
        try { catalog = repo.catalog().values.toList() }
        catch (e: Exception) { Timber.w(e, "catalog load failed") }
    }

    fun update(t: TrainingPreferences) {
        equipment = equipment?.copy(training = t)
    }

    fun save() {
        val eq = equipment ?: return
        scope.launch {
            saving = true; error = null; status = null
            try {
                repo.putEquipment(eq); status = "Saved."
            } catch (e: Exception) {
                Timber.w(e, "save failed"); error = e.message?.take(160)
            } finally { saving = false }
        }
    }

    Column(modifier = Modifier.fillMaxSize().background(bg).padding(horizontal = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = ink)
            }
            Text("Training preferences", color = ink, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold)
        }

        when {
            loading -> Text("Loading…", color = muted)
            equipment == null -> Text(error ?: "Could not load.", color = bad)
            else -> {
                val t = equipment!!.training
                Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
                    Section("Experience level", neon)
                    Segmented(
                        options = listOf("beginner", "intermediate", "advanced"),
                        selected = t.level,
                        onSelect = { update(t.copy(level = it)) },
                        neon = neon,
                    )

                    Section("Days per week", neon)
                    Segmented(
                        options = listOf("2", "3", "4", "5", "6"),
                        selected = t.daysPerWeek.toString(),
                        onSelect = { update(t.copy(daysPerWeek = it.toInt())) },
                        neon = neon,
                    )

                    Section("Split preference", neon)
                    Segmented(
                        options = listOf("auto", "full_body", "upper_lower", "ppl"),
                        selected = t.splitPreference,
                        labelMap = mapOf("full_body" to "full body", "upper_lower" to "upper-lower"),
                        onSelect = { update(t.copy(splitPreference = it)) },
                        neon = neon,
                    )

                    Section("Exercises per workout", neon)
                    Segmented(
                        options = listOf("Auto", "4", "5", "6", "7", "8"),
                        selected = t.exercisesPerWorkout?.toString() ?: "Auto",
                        onSelect = { update(t.copy(exercisesPerWorkout = it.toIntOrNull())) },
                        neon = neon,
                    )
                    Text(
                        "More adds accessory work for your under-trained muscles " +
                            "(core favored). Auto sizes each day to its split plus " +
                            "smart finishers. Mobility poses don't count.",
                        color = muted, fontSize = 11.sp,
                        modifier = Modifier.padding(top = 6.dp),
                    )

                    // ── PROG-1 program mode ──
                    ProgramModeSection(
                        program = t.program,
                        catalog = catalog,
                        onChange = { update(t.copy(program = it)) },
                        neon = neon, accent = accent, ink = ink, muted = muted,
                    )

                    Spacer(Modifier.height(20.dp))
                    Button(
                        onClick = ::save,
                        enabled = !saving,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = accent, contentColor = onAccent,
                        ),
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(if (saving) "Saving…" else "Save preferences") }
                    status?.let { Text(it, color = good, fontSize = 12.sp,
                        modifier = Modifier.padding(top = 6.dp)) }
                    error?.let { Text(it, color = bad, fontSize = 12.sp,
                        modifier = Modifier.padding(top = 6.dp)) }
                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }
}

@Composable
private fun ProgramModeSection(
    program: ProgramConfig,
    catalog: List<StrengthExerciseInfo>,
    onChange: (ProgramConfig) -> Unit,
    neon: Boolean,
    accent: androidx.compose.ui.graphics.Color,
    ink: androidx.compose.ui.graphics.Color,
    muted: androidx.compose.ui.graphics.Color,
) {
    val nameById = remember(catalog) { catalog.associate { it.id to it.name } }
    // Core weighted compound lifts — the movements a program is built on.
    val candidates = remember(catalog) {
        catalog.filter {
            it.isCompound && !it.isTimed &&
                (it.equipment.contains("dumbbell") || it.equipment.contains("barbell") ||
                    it.equipment.contains("cable"))
        }.sortedBy { it.name }
    }
    var menuOpen by remember { mutableStateOf(false) }

    Section("Program mode", neon)
    Text(
        "Put chosen core lifts on a fixed linear-progression scheme " +
            "(e.g. +5 lb/session, AMRAP last set, deload on failure) instead " +
            "of the recovery-aware generator. Other exercises are unaffected.",
        color = muted, fontSize = 11.sp,
        modifier = Modifier.padding(bottom = 6.dp),
    )
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Enable program mode", color = ink, fontSize = 13.sp,
            modifier = Modifier.weight(1f))
        Switch(
            checked = program.enabled,
            onCheckedChange = { onChange(program.copy(enabled = it)) },
            colors = SwitchDefaults.colors(checkedTrackColor = accent),
        )
    }

    if (program.enabled) {
        for (lift in program.lifts) {
            key(lift.exerciseId) {
                ProgramLiftCard(
                    lift = lift,
                    name = nameById[lift.exerciseId] ?: lift.exerciseId,
                    onScheme = { s ->
                        onChange(program.copy(lifts = program.lifts.map {
                            if (it.exerciseId == lift.exerciseId) applyScheme(it, s) else it
                        }))
                    },
                    onWeight = { w ->
                        onChange(program.copy(lifts = program.lifts.map {
                            if (it.exerciseId == lift.exerciseId) it.copy(currentWeightLb = w) else it
                        }))
                    },
                    onRemove = {
                        onChange(program.copy(
                            lifts = program.lifts.filter { it.exerciseId != lift.exerciseId }))
                    },
                    neon = neon, accent = accent, ink = ink, muted = muted,
                )
            }
        }
        if (program.lifts.isEmpty()) {
            Text("No lifts yet — add your core barbell/dumbbell movements.",
                color = muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 4.dp, bottom = 4.dp))
        }

        val used = program.lifts.map { it.exerciseId }.toSet()
        val available = candidates.filter { it.id !in used }
        Box(Modifier.padding(top = 8.dp)) {
            TextButton(onClick = { menuOpen = true }, enabled = available.isNotEmpty()) {
                Text(if (available.isEmpty()) "All core lifts added" else "+ Add a lift",
                    color = accent, fontSize = 13.sp)
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false },
                modifier = Modifier.heightIn(max = 320.dp)) {
                for (ex in available) {
                    DropdownMenuItem(
                        text = { Text(ex.name) },
                        onClick = {
                            menuOpen = false
                            onChange(program.copy(lifts = program.lifts + applyScheme(
                                ProgramLiftState(exerciseId = ex.id), "linear")))
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ProgramLiftCard(
    lift: ProgramLiftState,
    name: String,
    onScheme: (String) -> Unit,
    onWeight: (Double?) -> Unit,
    onRemove: () -> Unit,
    neon: Boolean,
    accent: androidx.compose.ui.graphics.Color,
    ink: androidx.compose.ui.graphics.Color,
    muted: androidx.compose.ui.graphics.Color,
) {
    val cellBg = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val cellBorder = if (neon) NeonMV.Line else MV.OutlineVariant
    val bad = if (neon) NeonMV.Bad else MV.Red

    var weightText by remember(lift.exerciseId) {
        mutableStateOf(lift.currentWeightLb?.let { fmtLb(it) } ?: "")
    }

    val detail = when (lift.scheme) {
        "greyskull" -> "${lift.sets}×${lift.repsLow}, last set AMRAP · +${fmtLb(lift.incrementLb)} lb " +
            "(double at ${lift.repsLow * 2}+) · 1 miss → deload"
        "double" -> "${lift.sets}×${lift.repsLow}-${lift.repsHigh} · +${fmtLb(lift.incrementLb)} lb " +
            "once every set hits ${lift.repsHigh}"
        else -> "${lift.sets}×${lift.repsLow} · +${fmtLb(lift.incrementLb)} lb/session · " +
            "${lift.failsBeforeDeload} misses → deload"
    }

    Column(
        Modifier.fillMaxWidth().padding(top = 8.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(cellBg)
            .border(1.dp, cellBorder, RoundedCornerShape(10.dp))
            .padding(10.dp),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(name, color = ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f))
            TextButton(onClick = onRemove) { Text("Remove", color = bad, fontSize = 12.sp) }
        }
        Spacer(Modifier.height(4.dp))
        Segmented(
            options = listOf("greyskull", "linear", "double"),
            selected = lift.scheme,
            labelMap = SCHEME_LABELS,
            onSelect = onScheme,
            neon = neon,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = weightText,
            onValueChange = {
                weightText = it
                onWeight(it.toDoubleOrNull())
            },
            label = { Text("Working weight (lb)") },
            placeholder = { Text("auto") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        Text(detail, color = muted, fontSize = 11.sp,
            modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
private fun Section(title: String, neon: Boolean = false) {
    Text(
        title.uppercase(),
        color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant, fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
        modifier = Modifier.padding(top = 16.dp, bottom = 4.dp),
    )
}

@Composable
private fun Segmented(
    options: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    labelMap: Map<String, String> = emptyMap(),
    neon: Boolean = false,
) {
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val cellBg = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val cellBorder = if (neon) NeonMV.Line else MV.OutlineVariant
    val onSel = if (neon) NeonMV.OnAccent else MV.OnSurface
    val offText = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for (opt in options) {
            val on = selected == opt
            val label = labelMap[opt] ?: opt
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(40.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (on) accent else cellBg)
                    .border(
                        1.dp,
                        if (on) accent else cellBorder,
                        RoundedCornerShape(8.dp),
                    )
                    .clickable { onSelect(opt) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label,
                    color = if (on) onSel else offText,
                    fontSize = 12.sp,
                    fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
        }
    }
}
