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
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.DirectionsBike
import androidx.compose.material.icons.outlined.Favorite
import androidx.compose.material.icons.outlined.FitnessCenter
import androidx.compose.material.icons.outlined.HourglassEmpty
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.GpsFixed
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
import app.myvitals.ui.neon.NeonMV
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
    val context = androidx.compose.ui.platform.LocalContext.current
    val neon = settings.neonShellEnabled

    // Hoisted palette — classic byte-identical when neon is off.
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant

    var workoutOpen by remember { mutableStateOf(false) }
    var workout by remember { mutableStateOf<CoachCard?>(null) }
    var workoutLoading by remember { mutableStateOf(false) }
    var workoutErr by remember { mutableStateOf<String?>(null) }

    var cardioOpen by remember { mutableStateOf(false) }
    var cardio by remember { mutableStateOf<CoachCard?>(null) }
    var cardioLoading by remember { mutableStateOf(false) }
    var cardioErr by remember { mutableStateOf<String?>(null) }

    var sleepOpen by remember { mutableStateOf(false) }
    var sleep by remember { mutableStateOf<CoachCard?>(null) }
    var sleepLoading by remember { mutableStateOf(false) }
    var sleepErr by remember { mutableStateOf<String?>(null) }

    var recoveryOpen by remember { mutableStateOf(false) }
    var recovery by remember { mutableStateOf<CoachCard?>(null) }
    var recoveryLoading by remember { mutableStateOf(false) }
    var recoveryErr by remember { mutableStateOf<String?>(null) }

    var fastingOpen by remember { mutableStateOf(false) }
    var fasting by remember { mutableStateOf<CoachCard?>(null) }
    var fastingLoading by remember { mutableStateOf(false) }
    var fastingErr by remember { mutableStateOf<String?>(null) }

    var goals by remember { mutableStateOf<List<app.myvitals.sync.AiGoal>>(emptyList()) }

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

    suspend fun fetchSleep(refresh: Boolean) {
        sleepLoading = true; sleepErr = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            sleep = if (refresh || sleep == null) {
                withContext(Dispatchers.IO) { api.coachSleep() }
            } else sleep
        } catch (e: Exception) {
            Timber.w(e, "sleep coach failed"); sleepErr = e.message?.take(160)
        } finally { sleepLoading = false }
    }

    suspend fun fetchRecovery(refresh: Boolean) {
        recoveryLoading = true; recoveryErr = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            recovery = if (refresh || recovery == null) {
                withContext(Dispatchers.IO) { api.coachRecovery() }
            } else recovery
        } catch (e: Exception) {
            Timber.w(e, "recovery coach failed"); recoveryErr = e.message?.take(160)
        } finally { recoveryLoading = false }
    }

    suspend fun fetchFasting(refresh: Boolean) {
        fastingLoading = true; fastingErr = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            fasting = if (refresh || fasting == null) {
                withContext(Dispatchers.IO) { api.coachFasting() }
            } else fasting
        } catch (e: Exception) {
            Timber.w(e, "fasting coach failed"); fastingErr = e.message?.take(160)
        } finally { fastingLoading = false }
    }

    // Preload the latest cached cards on mount so the user sees content
    // immediately without burning a Claude call. Goals load alongside —
    // they're cheap (no AI) and feed the read-only progress strip.
    //
    // SWR: every card + goals also persists to JsonCache so a cold-start
    // offline open renders the last-known cards instead of empty rows.
    val goalsType = remember {
        app.myvitals.data.JsonCache.listType(app.myvitals.sync.AiGoal::class.java)
    }
    LaunchedEffect(Unit) {
        // Hydrate from local cache first (offline-safe). Per-card.
        app.myvitals.data.JsonCache.read<CoachCard>(
            context, "coach_workout_latest", CoachCard::class.java,
        )?.let { workout = it.value }
        app.myvitals.data.JsonCache.read<CoachCard>(
            context, "coach_cardio_latest", CoachCard::class.java,
        )?.let { cardio = it.value }
        app.myvitals.data.JsonCache.read<CoachCard>(
            context, "coach_sleep_latest", CoachCard::class.java,
        )?.let { sleep = it.value }
        app.myvitals.data.JsonCache.read<CoachCard>(
            context, "coach_recovery_latest", CoachCard::class.java,
        )?.let { recovery = it.value }
        app.myvitals.data.JsonCache.read<CoachCard>(
            context, "coach_fasting_latest", CoachCard::class.java,
        )?.let { fasting = it.value }
        app.myvitals.data.JsonCache.read<List<app.myvitals.sync.AiGoal>>(
            context, "coach_goals", goalsType,
        )?.let { goals = it.value }

        if (!settings.isConfigured()) return@LaunchedEffect
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val w = withContext(Dispatchers.IO) { api.coachWorkoutLatest() }
            if (w.isSuccessful) w.body()?.let {
                workout = it
                app.myvitals.data.JsonCache.write(
                    context, "coach_workout_latest", CoachCard::class.java, it,
                )
            }
            val c = withContext(Dispatchers.IO) { api.coachCardioLatest() }
            if (c.isSuccessful) c.body()?.let {
                cardio = it
                app.myvitals.data.JsonCache.write(
                    context, "coach_cardio_latest", CoachCard::class.java, it,
                )
            }
            val s = withContext(Dispatchers.IO) { api.coachSleepLatest() }
            if (s.isSuccessful) s.body()?.let {
                sleep = it
                app.myvitals.data.JsonCache.write(
                    context, "coach_sleep_latest", CoachCard::class.java, it,
                )
            }
            val r = withContext(Dispatchers.IO) { api.coachRecoveryLatest() }
            if (r.isSuccessful) r.body()?.let {
                recovery = it
                app.myvitals.data.JsonCache.write(
                    context, "coach_recovery_latest", CoachCard::class.java, it,
                )
            }
            val f = withContext(Dispatchers.IO) { api.coachFastingLatest() }
            if (f.isSuccessful) f.body()?.let {
                fasting = it
                app.myvitals.data.JsonCache.write(
                    context, "coach_fasting_latest", CoachCard::class.java, it,
                )
            }
            val freshGoals = withContext(Dispatchers.IO) {
                runCatching { api.aiGoals() }.getOrDefault(emptyList())
            }
            if (freshGoals.isNotEmpty()) {
                goals = freshGoals
                app.myvitals.data.JsonCache.write(
                    context, "coach_goals", goalsType, freshGoals,
                )
            }
        } catch (_: Exception) { /* preload best-effort */ }
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
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = ink)
            }
            Text("Coach", color = ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        }

        Text(
            "AI cards that synthesize your data into specific guidance. Cards lazy-load on tap.",
            color = muted, fontSize = 12.sp,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        CoachCardBlock(
            neon = neon,
            accent = NeonMV.Cyan,
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
                Headline(a["headline"]?.toString() ?: "", neon, NeonMV.Cyan)
                Pair("What's working", a["what_is_working"]?.toString() ?: "", neon)
                Pair("What to change", a["what_to_change"]?.toString() ?: "", neon)
                EvidenceList(a["evidence"], neon)
                LabeledPlan("This week's plan", a["weekly_plan_hint"]?.toString() ?: "", neon)
            },
        )

        if (goals.isNotEmpty()) {
            GoalsCard(goals, neon)
        }

        CoachCardBlock(
            neon = neon,
            accent = NeonMV.Magenta,
            icon = Icons.Outlined.Bedtime,
            title = "Sleep coach",
            subtitle = "duration · consistency · stages · recovery link",
            open = sleepOpen,
            loading = sleepLoading,
            error = sleepErr,
            card = sleep,
            onToggle = {
                sleepOpen = !sleepOpen
                if (sleepOpen && sleep == null) {
                    scope.launch { fetchSleep(false) }
                }
            },
            onRefresh = { scope.launch { fetchSleep(true) } },
            renderBody = { c ->
                val a = c.analysis
                Headline(a["headline"]?.toString() ?: "", neon, NeonMV.Magenta)
                LabeledPlan(
                    "Supporting recovery",
                    (a["supporting_recovery"]?.toString() ?: "marginal"),
                    neon,
                )
                Pair("Duration", a["duration_assessment"]?.toString() ?: "", neon)
                Pair("Consistency", a["consistency_assessment"]?.toString() ?: "", neon)
                Pair("Stages", a["stage_assessment"]?.toString() ?: "", neon)
                Pair("Recovery link", a["recovery_link"]?.toString() ?: "", neon)
                EvidenceList(a["evidence"], neon)
                LabeledPlan("Recommendation", a["recommendation"]?.toString() ?: "", neon)
            },
        )

        CoachCardBlock(
            neon = neon,
            accent = NeonMV.Cyan,
            icon = Icons.Outlined.HourglassEmpty,
            title = "Fasting coach",
            subtitle = "should I fast · protocol · goal fit",
            open = fastingOpen,
            loading = fastingLoading,
            error = fastingErr,
            card = fasting,
            onToggle = {
                fastingOpen = !fastingOpen
                if (fastingOpen && fasting == null) {
                    scope.launch { fetchFasting(false) }
                }
            },
            onRefresh = { scope.launch { fetchFasting(true) } },
            renderBody = { c ->
                val a = c.analysis
                LabeledPlan(
                    "Recommendation",
                    (a["recommendation"]?.toString() ?: "eat normally")
                        .replace('_', ' ')
                        + (a["protocol_suggestion"]?.toString()?.takeIf { it.isNotBlank() }
                              ?.let { " · $it" } ?: ""),
                    neon,
                )
                val window = a["best_window"]?.toString()
                if (!window.isNullOrBlank()) {
                    Pair("Best window", window, neon)
                }
                Pair("Goal fit", a["goal_alignment"]?.toString() ?: "", neon)
                EvidenceList(a["evidence"], neon)
                val caveats = a["caveats"]
                if (caveats != null) {
                    @Suppress("UNCHECKED_CAST")
                    val list = (caveats as? List<*>)?.map { it.toString() } ?: emptyList()
                    if (list.isNotEmpty()) {
                        LabeledPlan("Caveats", list.joinToString("\n• ", prefix = "• "), neon)
                    }
                }
            },
        )

        CoachCardBlock(
            neon = neon,
            accent = NeonMV.Cyan,
            icon = Icons.Outlined.Favorite,
            title = "Recovery coach",
            subtitle = "HRV · RHR · skin temp · readiness — multi-week trend",
            open = recoveryOpen,
            loading = recoveryLoading,
            error = recoveryErr,
            card = recovery,
            onToggle = {
                recoveryOpen = !recoveryOpen
                if (recoveryOpen && recovery == null) {
                    scope.launch { fetchRecovery(false) }
                }
            },
            onRefresh = { scope.launch { fetchRecovery(true) } },
            renderBody = { c ->
                val a = c.analysis
                Headline(a["headline"]?.toString() ?: "", neon, NeonMV.Cyan)
                LabeledPlan(
                    "Trend",
                    (a["trend_direction"]?.toString() ?: "flat"),
                    neon,
                )
                Pair("HRV", a["hrv_assessment"]?.toString() ?: "", neon)
                Pair("Resting HR", a["rhr_assessment"]?.toString() ?: "", neon)
                Pair("Skin temperature Δ", a["skin_temp_assessment"]?.toString() ?: "", neon)
                Pair("Readiness", a["readiness_assessment"]?.toString() ?: "", neon)
                EvidenceList(a["evidence"], neon)
                LabeledPlan("Recommendation", a["recommendation"]?.toString() ?: "", neon)
            },
        )

        CoachCardBlock(
            neon = neon,
            accent = NeonMV.Cyan,
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
                Headline(a["headline"]?.toString() ?: "", neon, NeonMV.Cyan)
                Pair("Polarization", a["polarized_assessment"]?.toString() ?: "", neon)
                Pair("Volume", a["volume_assessment"]?.toString() ?: "", neon)
                EvidenceList(a["evidence"], neon)
                LabeledPlan("Recommendation", a["recommendation"]?.toString() ?: "", neon)
            },
        )

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun CoachCardBlock(
    neon: Boolean,
    accent: Color,
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
    val card1 = if (neon) NeonMV.Card else MV.SurfaceContainerLow
    val line = if (neon) NeonMV.Line else MV.OutlineVariant
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val dim = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    val errColor = if (neon) NeonMV.Bad else MV.Red
    // The card icon carries the per-kind neon accent; classic keeps ink.
    val iconTint = if (neon) accent else MV.OnSurface
    val toneColor = when ((card?.analysis?.get("tone") as? String)) {
        // Severity semantics: good=Lime, warn=Amber, bad=Bad under neon.
        "good" -> if (neon) NeonMV.Lime else Color(0xFF22C55E)
        "warn" -> if (neon) NeonMV.Amber else Color(0xFFF59E0B)
        "bad" -> if (neon) NeonMV.Bad else Color(0xFFEF4444)
        // Neutral tone falls back to the per-kind accent under neon.
        else -> if (neon) accent else MV.OutlineVariant
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(card1)
            .border(1.dp, line, RoundedCornerShape(12.dp)),
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
                Icon(icon, contentDescription = title, tint = iconTint,
                    modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(title, color = ink, fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold)
                    Text(subtitle, color = dim, fontSize = 10.sp)
                }
                Text(if (open) "▾" else "▸", color = muted, fontSize = 14.sp)
            }
        }

        if (open) {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                when {
                    loading -> Text("Thinking…", color = muted, fontSize = 12.sp)
                    error != null -> Text(error, color = errColor, fontSize = 12.sp)
                    card != null -> {
                        renderBody(card)
                        Spacer(Modifier.height(10.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "${card.generatedAt.take(16).replace("T", " ")} · ${card.model}" +
                                    if (card.cached) " (cached)" else "",
                                color = dim, fontSize = 10.sp,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = onRefresh, modifier = Modifier.size(28.dp)) {
                                Icon(Icons.Outlined.Refresh, "Refresh",
                                    tint = muted,
                                    modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                    else -> Text("Tap to generate.", color = dim, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun Headline(text: String, neon: Boolean, accent: Color) {
    // Under neon the headline carries the per-kind accent; classic keeps ink.
    Text(text, color = if (neon) accent else MV.OnSurface,
        fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(bottom = 6.dp))
}

@Composable
private fun Pair(label: String, value: String, neon: Boolean) {
    if (value.isBlank()) return
    Text(label.uppercase(), color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
        fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 6.dp, bottom = 2.dp))
    Text(value, color = if (neon) NeonMV.Ink else MV.OnSurface, fontSize = 12.sp)
}

@Composable
private fun EvidenceList(raw: Any?, neon: Boolean) {
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
    Text("EVIDENCE", color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
        fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 6.dp, bottom = 2.dp))
    items.forEach { line ->
        Text("• $line", color = if (neon) NeonMV.Ink else MV.OnSurface, fontSize = 12.sp,
            modifier = Modifier.padding(bottom = 2.dp))
    }
}

@Composable
private fun LabeledPlan(label: String, value: String, neon: Boolean) {
    if (value.isBlank()) return
    Spacer(Modifier.height(6.dp))
    Text(label.uppercase(), color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
        fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 4.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(if (neon) NeonMV.CardHigh else MV.SurfaceContainer)
            .padding(8.dp),
    ) {
        Text(value, color = if (neon) NeonMV.Ink else MV.OnSurface, fontSize = 12.sp)
    }
}

@Composable
private fun GoalsCard(goals: List<app.myvitals.sync.AiGoal>, neon: Boolean) {
    // Phone mirror of the web Coach.vue Goals card (GOALS-4 / GOALS-5).
    // Read-only — no AI call. Just renders the progress payload
    // already enriched on /ai/goals (GOALS-3).
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val line = if (neon) NeonMV.Line else MV.OutlineVariant
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 10.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(card)
            .border(
                androidx.compose.foundation.BorderStroke(1.dp, line),
                RoundedCornerShape(10.dp),
            )
            .padding(12.dp),
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Outlined.GpsFixed, contentDescription = null,
                    tint = ink, modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text("Goals", color = ink, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text("${goals.size} active",
                    color = muted, fontSize = 11.sp)
            }
            Spacer(Modifier.height(8.dp))
            goals.forEach { g ->
                GoalRow(g, neon)
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

@Composable
private fun GoalRow(g: app.myvitals.sync.AiGoal, neon: Boolean) {
    val pct = (g.progressPct ?: 0.0).coerceIn(0.0, 100.0)
    // Completed=Lime, in-progress=Cyan under neon; sky-blue classic.
    val barColor = if (pct >= 100.0) {
        if (neon) NeonMV.Lime else Color(0xFF22C55E)
    } else {
        if (neon) NeonMV.Cyan else Color(0xFF38BDF8)
    }
    val pillFg = if (neon) NeonMV.Cyan else Color(0xFF38BDF8)
    val pillBg = if (neon) NeonMV.Cyan.copy(alpha = 0.10f) else Color(0x1A38BDF8)
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val dim = if (neon) NeonMV.Muted else MV.OnSurfaceDim
    val track = if (neon) NeonMV.Track else Color(0x14FFFFFF)
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                g.kind.replace('_', ' ').uppercase(), color = pillFg,
                fontSize = 9.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier
                    .background(pillBg, RoundedCornerShape(4.dp))
                    .padding(horizontal = 5.dp, vertical = 1.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(g.title, color = ink, fontSize = 13.sp,
                modifier = Modifier.weight(1f))
            if (g.progressPct != null) {
                Text("${pct.toInt()}%", color = ink,
                    fontSize = 12.sp, fontWeight = FontWeight.Medium)
            }
        }
        Spacer(Modifier.height(4.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(track),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(fraction = (pct / 100.0).toFloat())
                    .fillMaxSize()
                    .background(barColor),
            )
        }
        if (g.currentValue != null && g.targetValue != null) {
            Spacer(Modifier.height(2.dp))
            Text(
                "%.1f / %s %s".format(
                    g.currentValue, g.targetValue.toString(), g.targetUnit ?: "",
                ),
                color = dim, fontSize = 10.sp,
            )
        }
    }
}
