package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.background
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.CircumferenceIn
import app.myvitals.sync.CircumferencePoint
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import app.myvitals.ui.LocalAppTokens

private data class Site(val key: String, val label: String,
                        val get: (CircumferencePoint) -> Double?)

private val SITES = listOf(
    Site("waist_cm", "Waist") { it.waistCm },
    Site("chest_cm", "Chest") { it.chestCm },
    Site("arms_cm", "Arms") { it.armsCm },
    Site("hips_cm", "Hips") { it.hipsCm },
    Site("thighs_cm", "Thighs") { it.thighsCm },
    Site("neck_cm", "Neck") { it.neckCm },
    Site("calves_cm", "Calves") { it.calvesCm },
)

@Composable
fun MeasurementsScreen(settings: SettingsRepository, onBack: () -> Unit) {
    val tok = LocalAppTokens.current
    val scope = rememberCoroutineScope()
    val accent = Color(0xFF38BDF8)
    var points by remember { mutableStateOf<List<CircumferencePoint>>(emptyList()) }
    var latest by remember { mutableStateOf<Map<String, Double>>(emptyMap()) }
    var loading by remember { mutableStateOf(true) }
    var selectedSite by remember { mutableStateOf("waist_cm") }
    val form = remember { mutableStateMapOf<String, String>() }
    var saving by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf<String?>(null) }

    suspend fun fetch() {
        if (!settings.isConfigured()) { loading = false; return }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val r = withContext(Dispatchers.IO) { api.circumference() }
            points = r.points
            latest = r.latestPerSite
        } catch (e: Exception) {
            Timber.w(e, "circumference load failed")
        } finally { loading = false }
    }
    LaunchedEffect(Unit) { fetch() }

    Column(Modifier.fillMaxSize().background(tok.bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = tok.onSurface)
            }
            Text("Measurements", color = tok.onSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold)
        }
        LazyColumn(
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // Latest-per-site tiles
            if (latest.isNotEmpty()) {
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
                        Column(Modifier.padding(14.dp)) {
                            Text("LATEST", color = tok.onSurfaceVariant, fontSize = 11.sp,
                                fontWeight = FontWeight.Bold)
                            Spacer(Modifier.height(6.dp))
                            SITES.filter { latest[it.key] != null }.chunked(3).forEach { rowSites ->
                                Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
                                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                    rowSites.forEach { s ->
                                        Column(Modifier.weight(1f)) {
                                            Text(s.label, color = tok.onSurfaceVariant, fontSize = 10.sp)
                                            Text("${latest[s.key]} cm", color = tok.onSurface,
                                                fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                                        }
                                    }
                                    repeat(3 - rowSites.size) { Spacer(Modifier.weight(1f)) }
                                }
                            }
                        }
                    }
                }
                // Trend
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
                        Column(Modifier.padding(14.dp)) {
                            Text("TREND", color = tok.onSurfaceVariant, fontSize = 11.sp,
                                fontWeight = FontWeight.Bold)
                            Spacer(Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                                modifier = Modifier.fillMaxWidth()
                                    .horizontalScroll(rememberScrollState())) {
                                SITES.forEach { s ->
                                    FilterChip(
                                        selected = selectedSite == s.key,
                                        onClick = { selectedSite = s.key },
                                        label = { Text(s.label, fontSize = 12.sp) },
                                        colors = FilterChipDefaults.filterChipColors(
                                            selectedContainerColor = accent.copy(alpha = 0.20f),
                                            selectedLabelColor = tok.onSurface,
                                        ),
                                    )
                                }
                            }
                            Spacer(Modifier.height(10.dp))
                            val site = SITES.first { it.key == selectedSite }
                            val vals = points.mapNotNull { site.get(it) }
                            if (vals.size < 2) {
                                Text("Log 2+ ${site.label.lowercase()} entries to see a trend.",
                                    color = tok.onSurfaceVariant, fontSize = 12.sp)
                            } else {
                                LineChart(vals, accent)
                            }
                        }
                    }
                }
            }
            // Entry form
            item {
                Card(colors = CardDefaults.cardColors(containerColor = tok.surfaceContainer)) {
                    Column(Modifier.padding(14.dp)) {
                        Text("LOG MEASUREMENTS", color = tok.onSurfaceVariant, fontSize = 11.sp,
                            fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(8.dp))
                        SITES.chunked(2).forEach { pair ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                pair.forEach { s ->
                                    OutlinedTextField(
                                        value = form[s.key] ?: "",
                                        onValueChange = { form[s.key] = it },
                                        label = { Text("${s.label} (cm)", fontSize = 12.sp) },
                                        singleLine = true,
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                        modifier = Modifier.weight(1f),
                                    )
                                }
                                if (pair.size == 1) Spacer(Modifier.weight(1f))
                            }
                        }
                        Spacer(Modifier.height(10.dp))
                        Button(
                            onClick = {
                                scope.launch {
                                    saving = true; msg = null
                                    // Only positive values (matches web; a stray
                                    // 0/negative must not persist).
                                    fun v(k: String) = form[k]?.toDoubleOrNull()?.takeIf { it > 0 }
                                    val body = CircumferenceIn(
                                        waistCm = v("waist_cm"), chestCm = v("chest_cm"),
                                        armsCm = v("arms_cm"), hipsCm = v("hips_cm"),
                                        thighsCm = v("thighs_cm"), neckCm = v("neck_cm"),
                                        calvesCm = v("calves_cm"),
                                    )
                                    val any = listOf(body.waistCm, body.chestCm, body.armsCm,
                                        body.hipsCm, body.thighsCm, body.neckCm, body.calvesCm)
                                        .any { it != null && it > 0 }
                                    if (!any) { msg = "Enter at least one measurement."; saving = false; return@launch }
                                    try {
                                        val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                                        withContext(Dispatchers.IO) { api.logCircumference(body) }
                                        SITES.forEach { form[it.key] = "" }
                                        fetch()
                                        msg = "Saved."
                                    } catch (e: Exception) {
                                        msg = e.message?.take(120) ?: "Save failed"
                                    } finally { saving = false }
                                }
                            },
                            enabled = !saving,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(if (saving) "Saving…" else "Save measurements") }
                        msg?.let {
                            Spacer(Modifier.height(6.dp))
                            Text(it, color = tok.onSurfaceVariant, fontSize = 12.sp)
                        }
                        Text("Leave a field blank to skip it. All entered sites share one timestamp.",
                            color = tok.onSurfaceVariant, fontSize = 11.sp,
                            modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun LineChart(values: List<Double>, color: Color) {
    Canvas(Modifier.fillMaxWidth().height(160.dp)) {
        if (values.size < 2) return@Canvas
        val minV = values.min()
        val maxV = values.max()
        val span = (maxV - minV).takeIf { it > 0.0001 } ?: 1.0
        val stepX = size.width / (values.size - 1)
        val pad = 8f
        val h = size.height - pad * 2
        val pts = values.mapIndexed { i, v ->
            Offset(i * stepX, pad + (h - ((v - minV) / span * h).toFloat()))
        }
        for (i in 0 until pts.size - 1) {
            drawLine(color, pts[i], pts[i + 1], strokeWidth = 3f)
        }
        pts.forEach { drawCircle(color, radius = 4f, center = it, style = Stroke(width = 2f)) }
    }
}
