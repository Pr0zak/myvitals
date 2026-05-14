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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import app.myvitals.ui.MV
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Phone-side parity for the web's StrengthEquipment.vue. Edits the same
 * fields the catalog filter cares about — dumbbells / wrist weights /
 * bench / pull-up bar / cardio gear — and PUTs through the same
 * `/workout/strength/equipment` endpoint the web uses. Backend's
 * `put_equipment` already auto-regenerates today's plan when the change
 * could affect the prescription, so no extra refresh trigger needed here.
 */
@Composable
fun StrengthEquipmentScreen(
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

    fun mutate(transform: (EquipmentPayload) -> EquipmentPayload) {
        equipment = equipment?.let(transform)
        status = null
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

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MV.Bg)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Back", tint = MV.OnSurface)
            }
            Text("Equipment", color = MV.OnSurface, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold)
        }

        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant)
            equipment == null -> Text(error ?: "Could not load.", color = MV.Red)
            else -> {
                val eq = equipment!!

                EqSection("Dumbbells")
                EqSegmented(
                    options = listOf("none", "fixed_pairs", "adjustable"),
                    selected = eq.dumbbells.type,
                    labelMap = mapOf("fixed_pairs" to "fixed pairs"),
                    onSelect = { type ->
                        mutate {
                            it.copy(dumbbells = it.dumbbells.copy(type = type))
                        }
                    },
                )

                if (eq.dumbbells.type == "fixed_pairs") {
                    Spacer(Modifier.height(8.dp))
                    Text("Owned pairs (lb)", color = MV.OnSurfaceVariant, fontSize = 11.sp)
                    Spacer(Modifier.height(4.dp))
                    val presets = listOf(
                        2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0,
                        22.5, 25.0, 27.5, 30.0, 32.5, 35.0, 37.5, 40.0,
                        45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0,
                        85.0, 90.0, 95.0, 100.0,
                    )
                    ChipGrid(
                        items = presets,
                        selected = eq.dumbbells.pairsLb.toSet(),
                        label = { fmtLb(it) },
                        onToggle = { lb ->
                            mutate {
                                val cur = it.dumbbells.pairsLb.toMutableList()
                                if (lb in cur) cur.remove(lb) else cur.add(lb)
                                cur.sort()
                                it.copy(dumbbells = it.dumbbells.copy(pairsLb = cur))
                            }
                        },
                    )
                }
                // Adjustable + min/max/step inputs intentionally omitted from v1.
                // The user can pick adjustable here; web still owns the numeric
                // limits until we add Compose number-pickers in a follow-up.

                EqSection("Wrist weights (lb)")
                val wristPresets = listOf(1.0, 1.5, 2.0, 2.5, 3.0, 5.0)
                ChipGrid(
                    items = wristPresets,
                    selected = eq.wristWeightsLb.toSet(),
                    label = { fmtLb(it) },
                    onToggle = { lb ->
                        mutate {
                            val cur = it.wristWeightsLb.toMutableList()
                            if (lb in cur) cur.remove(lb) else cur.add(lb)
                            cur.sort()
                            it.copy(wristWeightsLb = cur)
                        }
                    },
                )

                EqSection("Bench")
                SwitchRow("Flat", eq.bench.flat) { on ->
                    mutate { it.copy(bench = it.bench.copy(flat = on)) }
                }
                SwitchRow("Incline", eq.bench.incline) { on ->
                    mutate { it.copy(bench = it.bench.copy(incline = on)) }
                }
                SwitchRow("Decline", eq.bench.decline) { on ->
                    mutate { it.copy(bench = it.bench.copy(decline = on)) }
                }

                EqSection("Bars")
                SwitchRow("Pull-up bar", eq.pullUpBar) { on ->
                    mutate { it.copy(pullUpBar = on) }
                }

                EqSection("Cardio gear")
                SwitchRow("Rower (Concept2)", eq.cardioRower) { on ->
                    mutate { it.copy(cardioRower = on) }
                }
                SwitchRow("Mountain bike (outdoor)", eq.cardioMtbOutdoor) { on ->
                    mutate { it.copy(cardioMtbOutdoor = on) }
                }
                SwitchRow("Road bike (outdoor)", eq.cardioRoadBike) { on ->
                    mutate { it.copy(cardioRoadBike = on) }
                }
                SwitchRow("Indoor bike", eq.cardioBikeIndoor) { on ->
                    mutate { it.copy(cardioBikeIndoor = on) }
                }
                SwitchRow("Treadmill", eq.cardioTreadmill) { on ->
                    mutate { it.copy(cardioTreadmill = on) }
                }

                Spacer(Modifier.height(20.dp))
                Button(
                    onClick = ::save,
                    enabled = !saving,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MV.BrandRed, contentColor = MV.OnSurface,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (saving) "Saving…" else "Save equipment") }
                status?.let { Text(it, color = MV.Green, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 6.dp)) }
                error?.let { Text(it, color = MV.Red, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 6.dp)) }
                Spacer(Modifier.height(24.dp))

                Text(
                    "Other gear (barbell, rack, cables, kettlebells, bands) " +
                        "still edits from the web dashboard for now.",
                    color = MV.OnSurfaceDim, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp, bottom = 16.dp),
                )
            }
        }
    }
}

private fun fmtLb(lb: Double): String =
    if (lb == lb.toLong().toDouble()) "${lb.toLong()}" else lb.toString()

@Composable
private fun EqSection(title: String) {
    Text(
        title.uppercase(),
        color = MV.OnSurfaceVariant, fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
        modifier = Modifier.padding(top = 16.dp, bottom = 4.dp),
    )
}

@Composable
private fun EqSegmented(
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

@Composable
private fun SwitchRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onCheckedChange(!checked) }
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = MV.OnSurface, fontSize = 14.sp,
            modifier = Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = MV.OnSurface,
                checkedTrackColor = MV.BrandRed,
                uncheckedThumbColor = MV.OnSurfaceVariant,
                uncheckedTrackColor = MV.SurfaceContainerLow,
                uncheckedBorderColor = MV.OutlineVariant,
            ),
        )
    }
}

@Composable
private fun <T> ChipGrid(
    items: List<T>,
    selected: Set<T>,
    label: (T) -> String,
    onToggle: (T) -> Unit,
) {
    // Simple flowing row of chips. Use FlowRow when material3 ships it
    // stable; for now wrap manually 4 per row to stay readable on narrow
    // phones without pulling extra deps.
    val perRow = 4
    val rows = items.chunked(perRow)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (row in rows) {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (item in row) {
                    val on = item in selected
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .height(36.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (on) MV.BrandRed else MV.SurfaceContainerLow)
                            .border(
                                1.dp,
                                if (on) MV.BrandRed else MV.OutlineVariant,
                                RoundedCornerShape(8.dp),
                            )
                            .clickable { onToggle(item) },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(label(item),
                            color = if (on) MV.OnSurface else MV.OnSurfaceVariant,
                            fontSize = 12.sp,
                            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                        )
                    }
                }
                // pad short last row so chips don't fill width
                val pad = perRow - row.size
                repeat(pad) {
                    Box(modifier = Modifier.weight(1f))
                }
            }
        }
    }
}
