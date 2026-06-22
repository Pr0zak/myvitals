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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.EquipmentPayload
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
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

    val neon = settings.neonShellEnabled
    // Hoisted palette: every neon value is `if (neon) … else <current>` so the
    // classic shell stays byte-identical. Chip/segment accent = Cyan (selected),
    // micro-loader (wrist weights) accent = Lime — passed explicitly below.
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val dim = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val good = if (neon) NeonMV.Lime else MV.Green
    val bad = if (neon) NeonMV.Bad else MV.Red
    // dark ink reads better on a bright neon fill; classic keeps the light text
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
            .background(bg)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "Back", tint = ink)
            }
            Text("Equipment", color = ink, fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold)
        }

        when {
            loading -> Text("Loading…", color = muted)
            equipment == null -> Text(error ?: "Could not load.", color = bad)
            else -> {
                val eq = equipment!!

                EqSection("Dumbbells", muted)
                EqSegmented(
                    options = listOf("none", "fixed_pairs", "adjustable"),
                    selected = eq.dumbbells.type,
                    labelMap = mapOf("fixed_pairs" to "fixed pairs"),
                    onSelect = { type ->
                        mutate {
                            it.copy(dumbbells = it.dumbbells.copy(type = type))
                        }
                    },
                    neon = neon,
                )

                if (eq.dumbbells.type == "fixed_pairs") {
                    Spacer(Modifier.height(8.dp))
                    Text("Owned pairs (lb)", color = muted, fontSize = 11.sp)
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
                        neon = neon,
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

                EqSection("Wrist weights (lb)", muted)
                Text(
                    "Sub-5 lb micro-loaders you strap on to bridge the gap " +
                        "between pairs (e.g. 1.25 lb). The planner uses exactly " +
                        "what you select here — nothing else.",
                    color = muted, fontSize = 11.sp,
                    modifier = Modifier.padding(bottom = 4.dp),
                )
                val wristAccent = if (neon) NeonMV.Lime else MV.BrandRed
                val wristPresets = listOf(
                    0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0,
                )
                // Render presets PLUS any custom values already selected (e.g.
                // added via the web equipment screen) so they're visible and
                // removable here too — not silently hidden on the phone.
                val wristItems = (wristPresets + eq.wristWeightsLb).distinct().sorted()
                ChipGrid(
                    items = wristItems,
                    selected = eq.wristWeightsLb.toSet(),
                    label = { fmtLb(it) },
                    neon = neon,
                    accentColor = wristAccent,
                    onToggle = { lb ->
                        mutate {
                            val cur = it.wristWeightsLb.toMutableList()
                            if (lb in cur) cur.remove(lb) else cur.add(lb)
                            cur.sort()
                            it.copy(wristWeightsLb = cur)
                        }
                    },
                )
                // Custom micro-loader entry (parity with web) — any value not in
                // the presets, snapped to 0.25 lb resolution.
                var wristInput by remember { mutableStateOf("") }
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = wristInput,
                        onValueChange = { wristInput = it },
                        label = { Text("custom lb") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = {
                            val v = wristInput.toDoubleOrNull()
                            if (v != null) {
                                val rounded = Math.round(v * 4.0) / 4.0  // 0.25 lb
                                if (rounded > 0.0) {
                                    mutate {
                                        val cur = it.wristWeightsLb.toMutableList()
                                        if (rounded !in cur) { cur.add(rounded); cur.sort() }
                                        it.copy(wristWeightsLb = cur)
                                    }
                                }
                            }
                            wristInput = ""
                        },
                        enabled = wristInput.isNotBlank(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = wristAccent, contentColor = onAccent,
                        ),
                    ) { Text("Add") }
                }

                EqSection("Bench", muted)
                SwitchRow("Flat", eq.bench.flat, neon) { on ->
                    mutate { it.copy(bench = it.bench.copy(flat = on)) }
                }
                SwitchRow("Incline", eq.bench.incline, neon) { on ->
                    mutate { it.copy(bench = it.bench.copy(incline = on)) }
                }
                SwitchRow("Decline", eq.bench.decline, neon) { on ->
                    mutate { it.copy(bench = it.bench.copy(decline = on)) }
                }

                EqSection("Bars", muted)
                SwitchRow("Pull-up bar", eq.pullUpBar, neon) { on ->
                    mutate { it.copy(pullUpBar = on) }
                }

                EqSection("Cardio gear", muted)
                SwitchRow("Rower (Concept2)", eq.cardioRower, neon) { on ->
                    mutate { it.copy(cardioRower = on) }
                }
                SwitchRow("Mountain bike (outdoor)", eq.cardioMtbOutdoor, neon) { on ->
                    mutate { it.copy(cardioMtbOutdoor = on) }
                }
                SwitchRow("Road bike (outdoor)", eq.cardioRoadBike, neon) { on ->
                    mutate { it.copy(cardioRoadBike = on) }
                }
                SwitchRow("Indoor bike", eq.cardioBikeIndoor, neon) { on ->
                    mutate { it.copy(cardioBikeIndoor = on) }
                }
                SwitchRow("Treadmill", eq.cardioTreadmill, neon) { on ->
                    mutate { it.copy(cardioTreadmill = on) }
                }

                Spacer(Modifier.height(20.dp))
                Button(
                    onClick = ::save,
                    enabled = !saving,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = accent, contentColor = onAccent,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (saving) "Saving…" else "Save equipment") }
                status?.let { Text(it, color = good, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 6.dp)) }
                error?.let { Text(it, color = bad, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 6.dp)) }
                Spacer(Modifier.height(24.dp))

                Text(
                    "Other gear (barbell, rack, cables, kettlebells, bands) " +
                        "still edits from the web dashboard for now.",
                    color = dim, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp, bottom = 16.dp),
                )
            }
        }
    }
}

private fun fmtLb(lb: Double): String =
    if (lb == lb.toLong().toDouble()) "${lb.toLong()}" else lb.toString()

@Composable
private fun EqSection(title: String, labelColor: androidx.compose.ui.graphics.Color) {
    Text(
        title.uppercase(),
        color = labelColor, fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
        modifier = Modifier.padding(top = 16.dp, bottom = 4.dp),
    )
}

@Composable
private fun EqSegmented(
    options: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    neon: Boolean,
    labelMap: Map<String, String> = emptyMap(),
) {
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val unselectedBg = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val outline = if (neon) NeonMV.Line else MV.OutlineVariant
    val selectedInk = if (neon) NeonMV.OnAccent else MV.OnSurface
    val unselectedInk = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
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
                    .background(if (on) accent else unselectedBg)
                    .border(
                        1.dp,
                        if (on) accent else outline,
                        RoundedCornerShape(8.dp),
                    )
                    .clickable { onSelect(opt) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label,
                    color = if (on) selectedInk else unselectedInk,
                    fontSize = 12.sp,
                    fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
        }
    }
}

@Composable
private fun SwitchRow(
    label: String,
    checked: Boolean,
    neon: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val accent = if (neon) NeonMV.Cyan else MV.BrandRed
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val track = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val outline = if (neon) NeonMV.Line else MV.OutlineVariant
    // thumb on the checked (accent) track stays light in classic; under neon
    // a dark thumb reads on the bright Cyan fill
    val checkedThumb = if (neon) NeonMV.OnAccent else MV.OnSurface
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onCheckedChange(!checked) }
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = ink, fontSize = 14.sp,
            modifier = Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = checkedThumb,
                checkedTrackColor = accent,
                uncheckedThumbColor = muted,
                uncheckedTrackColor = track,
                uncheckedBorderColor = outline,
            ),
        )
    }
}

@Composable
private fun <T> ChipGrid(
    items: List<T>,
    selected: Set<T>,
    label: (T) -> String,
    neon: Boolean,
    onToggle: (T) -> Unit,
    // selected-chip accent; defaults to Cyan under neon, Brand red classic.
    // The micro-loader (wrist weights) grid passes Lime here.
    accentColor: androidx.compose.ui.graphics.Color =
        if (neon) NeonMV.Cyan else MV.BrandRed,
) {
    val unselectedBg = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val outline = if (neon) NeonMV.Line else MV.OutlineVariant
    val selectedInk = if (neon) NeonMV.OnAccent else MV.OnSurface
    val unselectedInk = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
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
                            .background(if (on) accentColor else unselectedBg)
                            .border(
                                1.dp,
                                if (on) accentColor else outline,
                                RoundedCornerShape(8.dp),
                            )
                            .clickable { onToggle(item) },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(label(item),
                            color = if (on) selectedInk else unselectedInk,
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
