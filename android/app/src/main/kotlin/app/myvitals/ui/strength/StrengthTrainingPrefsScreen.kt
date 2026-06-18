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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.EquipmentPayload
import app.myvitals.sync.TrainingPreferences
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.launch
import timber.log.Timber

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
                    // "Auto".toIntOrNull() == null → auto sizing (WP-17).
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
            }
        }
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
