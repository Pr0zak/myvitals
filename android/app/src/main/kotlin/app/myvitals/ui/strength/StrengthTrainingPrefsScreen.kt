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

    var equipment by remember { mutableStateOf<EquipmentPayload?>(null) }
    var loading by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        try {
            equipment = repo.equipment().payload
        } catch (e: Exception) {
            Timber.w(e, "load equipment failed"); error = e.message?.take(160)
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

    Column(modifier = Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = MV.OnSurface)
            }
            Text("Training preferences", color = MV.OnSurface, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold)
        }

        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant)
            equipment == null -> Text(error ?: "Could not load.", color = MV.Red)
            else -> {
                val t = equipment!!.training
                Section("Experience level")
                Segmented(
                    options = listOf("beginner", "intermediate", "advanced"),
                    selected = t.level,
                    onSelect = { update(t.copy(level = it)) },
                )

                Section("Days per week")
                Segmented(
                    options = listOf("2", "3", "4", "5", "6"),
                    selected = t.daysPerWeek.toString(),
                    onSelect = { update(t.copy(daysPerWeek = it.toInt())) },
                )

                Section("Split preference")
                Segmented(
                    options = listOf("auto", "full_body", "upper_lower", "ppl"),
                    selected = t.splitPreference,
                    labelMap = mapOf("full_body" to "full body", "upper_lower" to "upper-lower"),
                    onSelect = { update(t.copy(splitPreference = it)) },
                )

                Section("Target session length (min)")
                Segmented(
                    options = listOf("30", "40", "50", "60", "75"),
                    selected = t.workoutMinutes.toString(),
                    onSelect = { update(t.copy(workoutMinutes = it.toInt())) },
                )

                Spacer(Modifier.height(20.dp))
                Button(
                    onClick = ::save,
                    enabled = !saving,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (saving) "Saving…" else "Save preferences") }
                status?.let { Text(it, color = MV.Green, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 6.dp)) }
                error?.let { Text(it, color = MV.Red, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 6.dp)) }
            }
        }
    }
}

@Composable
private fun Section(title: String) {
    Text(
        title.uppercase(),
        color = MV.OnSurfaceVariant, fontSize = 11.sp,
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
) {
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
                    .background(if (on) MV.BrandRed else MV.SurfaceContainerLow)
                    .border(
                        1.dp,
                        if (on) MV.BrandRed else MV.OutlineVariant,
                        RoundedCornerShape(8.dp),
                    )
                    .clickable { onSelect(opt) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label,
                    color = if (on) MV.OnSurface else MV.OnSurfaceVariant,
                    fontSize = 12.sp,
                    fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
        }
    }
}
