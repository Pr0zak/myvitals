package app.myvitals.ui

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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.DirectionsBike
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.Refresh
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.CoachCard
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * Coach — phone mirror of /coach. Two lazy-loaded AI cards (workout
 * synthesis + cardio zones). Cards expand on tap; preload tries the
 * /latest endpoints so the user sees something immediately without
 * burning a Claude call.
 */
@Composable
fun CoachScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()

    var workoutOpen by remember { mutableStateOf(false) }
    var workout by remember { mutableStateOf<CoachCard?>(null) }
    var workoutLoading by remember { mutableStateOf(false) }
    var workoutErr by remember { mutableStateOf<String?>(null) }

    var cardioOpen by remember { mutableStateOf(false) }
    var cardio by remember { mutableStateOf<CoachCard?>(null) }
    var cardioLoading by remember { mutableStateOf(false) }
    var cardioErr by remember { mutableStateOf<String?>(null) }

    suspend fun fetchWorkout(refresh: Boolean) {
        workoutLoading = true; workoutErr = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            workout = if (refresh || workout == null) {
                withContext(Dispatchers.IO) { api.coachWorkout() }
            } else workout
        } catch (e: Exception) {
            Timber.w(e, "workout coach failed"); workoutErr = e.message?.take(160)
        } finally { workoutLoading = false }
    }

    suspend fun fetchCardio(refresh: Boolean) {
        cardioLoading = true; cardioErr = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            cardio = if (refresh || cardio == null) {
                withContext(Dispatchers.IO) { api.coachCardio() }
            } else cardio
        } catch (e: Exception) {
            Timber.w(e, "cardio coach failed"); cardioErr = e.message?.take(160)
        } finally { cardioLoading = false }
    }

    // Preload the latest cached cards on mount so the user sees content
    // immediately without burning a Claude call.
    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) return@LaunchedEffect
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val w = withContext(Dispatchers.IO) { api.coachWorkoutLatest() }
            if (w.isSuccessful) workout = w.body()
            val c = withContext(Dispatchers.IO) { api.coachCardioLatest() }
            if (c.isSuccessful) cardio = c.body()
        } catch (_: Exception) { /* preload best-effort */ }
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
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = MV.OnSurface)
            }
            Text("Coach", color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        }

        Text(
            "AI cards that synthesize your data into specific guidance. Cards lazy-load on tap.",
            color = MV.OnSurfaceVariant, fontSize = 12.sp,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        CoachCardBlock(
            icon = Icons.Outlined.FitnessCenter,
            title = "Workout coach",
            subtitle = "strength + cardio + recovery",
            open = workoutOpen,
            loading = workoutLoading,
            error = workoutErr,
            card = workout,
            onToggle = {
                workoutOpen = !workoutOpen
                if (workoutOpen && workout == null) {
                    scope.launch { fetchWorkout(false) }
                }
            },
            onRefresh = { scope.launch { fetchWorkout(true) } },
            renderBody = { c ->
                val a = c.analysis
                Headline(a["headline"]?.toString() ?: "")
                Pair("What's working", a["what_is_working"]?.toString() ?: "")
                Pair("What to change", a["what_to_change"]?.toString() ?: "")
                EvidenceList(a["evidence"])
                LabeledPlan("This week's plan", a["weekly_plan_hint"]?.toString() ?: "")
            },
        )

        CoachCardBlock(
            icon = Icons.Outlined.DirectionsBike,
            title = "Cardio coach",
            subtitle = "HR zones, dose, polarization",
            open = cardioOpen,
            loading = cardioLoading,
            error = cardioErr,
            card = cardio,
            onToggle = {
                cardioOpen = !cardioOpen
                if (cardioOpen && cardio == null) {
                    scope.launch { fetchCardio(false) }
                }
            },
            onRefresh = { scope.launch { fetchCardio(true) } },
            renderBody = { c ->
                val a = c.analysis
                Headline(a["headline"]?.toString() ?: "")
                Pair("Polarization", a["polarized_assessment"]?.toString() ?: "")
                Pair("Volume", a["volume_assessment"]?.toString() ?: "")
                EvidenceList(a["evidence"])
                LabeledPlan("Recommendation", a["recommendation"]?.toString() ?: "")
            },
        )

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun CoachCardBlock(
    icon: ImageVector,
    title: String,
    subtitle: String,
    open: Boolean,
    loading: Boolean,
    error: String?,
    card: CoachCard?,
    onToggle: () -> Unit,
    onRefresh: () -> Unit,
    renderBody: @Composable (CoachCard) -> Unit,
) {
    val toneColor = when ((card?.analysis?.get("tone") as? String)) {
        "good" -> Color(0xFF22C55E)
        "warn" -> Color(0xFFF59E0B)
        "bad" -> Color(0xFFEF4444)
        else -> MV.OutlineVariant
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(MV.SurfaceContainerLow)
            .border(1.dp, MV.OutlineVariant, RoundedCornerShape(12.dp)),
    ) {
        // Tone-tinted left border via overlay
        Box(modifier = Modifier.fillMaxWidth()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onToggle() }
                    .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(modifier = Modifier.size(4.dp, 24.dp).background(toneColor))
                Spacer(Modifier.width(8.dp))
                Icon(icon, contentDescription = title, tint = MV.OnSurface,
                    modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(title, color = MV.OnSurface, fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold)
                    Text(subtitle, color = MV.OnSurfaceDim, fontSize = 10.sp)
                }
                Text(if (open) "▾" else "▸", color = MV.OnSurfaceVariant, fontSize = 14.sp)
            }
        }

        if (open) {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                when {
                    loading -> Text("Thinking…", color = MV.OnSurfaceVariant, fontSize = 12.sp)
                    error != null -> Text(error, color = MV.Red, fontSize = 12.sp)
                    card != null -> {
                        renderBody(card)
                        Spacer(Modifier.height(10.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "${card.generatedAt.take(16).replace("T", " ")} · ${card.model}" +
                                    if (card.cached) " (cached)" else "",
                                color = MV.OnSurfaceDim, fontSize = 10.sp,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = onRefresh, modifier = Modifier.size(28.dp)) {
                                Icon(Icons.Outlined.Refresh, "Refresh",
                                    tint = MV.OnSurfaceVariant,
                                    modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                    else -> Text("Tap to generate.", color = MV.OnSurfaceDim, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun Headline(text: String) {
    Text(text, color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(bottom = 6.dp))
}

@Composable
private fun Pair(label: String, value: String) {
    if (value.isBlank()) return
    Text(label.uppercase(), color = MV.OnSurfaceVariant, fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 6.dp, bottom = 2.dp))
    Text(value, color = MV.OnSurface, fontSize = 12.sp)
}

@Composable
private fun EvidenceList(raw: Any?) {
    val items: List<String> = when (raw) {
        is List<*> -> raw.mapNotNull { it?.toString() }
        is String -> {
            // Claude tool-use sometimes returns array fields as a
            // single string with <parameter name="item">…</parameter>
            // blocks instead of a JSON array. Extract those when
            // present; otherwise fall back to newline-split.
            val tagRe = Regex("""<parameter[^>]*>([\s\S]*?)</parameter>""")
            val tagItems = tagRe.findAll(raw).map { it.groupValues[1].trim() }
                .filter { it.isNotEmpty() }.toList()
            if (tagItems.isNotEmpty()) tagItems
            else raw.lines().map { it.trim() }.filter { it.isNotEmpty() }
        }
        else -> emptyList()
    }
    if (items.isEmpty()) return
    Text("EVIDENCE", color = MV.OnSurfaceVariant, fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 6.dp, bottom = 2.dp))
    items.forEach { line ->
        Text("• $line", color = MV.OnSurface, fontSize = 12.sp,
            modifier = Modifier.padding(bottom = 2.dp))
    }
}

@Composable
private fun LabeledPlan(label: String, value: String) {
    if (value.isBlank()) return
    Spacer(Modifier.height(6.dp))
    Text(label.uppercase(), color = MV.OnSurfaceVariant, fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 4.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(MV.SurfaceContainer)
            .padding(8.dp),
    ) {
        Text(value, color = MV.OnSurface, fontSize = 12.sp)
    }
}
