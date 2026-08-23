package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.PrepComponentOut
import app.myvitals.sync.PrepComponentPatch
import app.myvitals.sync.PrepGenerateIn
import app.myvitals.sync.PrepMealOut
import app.myvitals.sync.PrepMealPatch
import app.myvitals.sync.PrepPlanOut
import app.myvitals.sync.PrepTargetsOut
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Weekend prep — the phone mirror of the web's Prep view (MEAL-9).
 *
 * Batch cooking has two completely different moments and mixing them
 * helps neither, so this is two sub-tabs.
 *
 * **Prep day** you are in the kitchen with a knife: a short checklist in
 * the order a real session runs — protein and grain on first because
 * they take longest, sauce made while they cook — that you can tick off
 * without losing your place.
 *
 * **The week** you are hungry and opening the fridge: what tonight is,
 * what goes in it, and a one-tap way to say you are eating out.
 *
 * The sub-tab defaults from the day of the week. Guessing gets it right
 * most of the time and costs nothing when wrong.
 *
 * Nothing here scores adherence. Skipping a meal or eating out release
 * their portions back into the spare count, which is the whole point: a
 * planner that turns red on Wednesday is a planner that gets deleted in
 * week two.
 *
 * Every number rendered is computed by the backend from the food
 * catalog. The AI that proposes the week never emits one.
 */
@Composable
fun PrepTab(settings: SettingsRepository) {
    var plan by remember { mutableStateOf<PrepPlanOut?>(null) }
    var targets by remember { mutableStateOf<PrepTargetsOut?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var generating by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf<Long?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }
    var showTargets by remember { mutableStateOf(false) }

    val weekend = LocalDate.now().dayOfWeek.let {
        it == DayOfWeek.SATURDAY || it == DayOfWeek.SUNDAY
    }
    var sub by remember { mutableStateOf(if (weekend) "prep" else "week") }
    var draftDays by remember { mutableStateOf(5) }
    var draftSlots by remember { mutableStateOf(listOf("lunch", "dinner")) }

    val scope = rememberCoroutineScope()

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                val resp = api.prepCurrent()
                plan = if (resp.isSuccessful) resp.body() else null
                targets = api.prepTargets()
            }
            error = null
        } catch (e: Exception) {
            if (plan == null && targets == null) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { fetch() }

    fun generate() {
        scope.launch {
            generating = true
            error = null
            notice = null
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                plan = withContext(Dispatchers.IO) {
                    api.prepGenerate(
                        PrepGenerateIn(
                            start = nextMondayIso(),
                            days = draftDays,
                            slots = draftSlots,
                        ),
                    )
                }
                sub = "prep"
            } catch (e: Exception) {
                error = e.message ?: "Could not plan the week"
            } finally {
                generating = false
            }
        }
    }

    fun tickComponent(c: PrepComponentOut) {
        scope.launch {
            busy = c.id
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                plan = withContext(Dispatchers.IO) {
                    api.prepPatchComponent(c.id, PrepComponentPatch(done = !c.done))
                }
            } catch (e: Exception) {
                error = e.message ?: "Could not save"
            } finally {
                busy = null
            }
        }
    }

    fun setStatus(m: PrepMealOut, status: String) {
        scope.launch {
            busy = m.id
            notice = null
            try {
                // Tapping the active status again clears it back to
                // suggested, so a mis-tap is one tap to undo rather than
                // a decision the user is stuck with all week.
                val next = if (m.status == status) "suggested" else status
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                plan = withContext(Dispatchers.IO) {
                    api.prepPatchMeal(m.id, PrepMealPatch(status = next))
                }
            } catch (e: Exception) {
                error = e.message ?: "Could not save"
            } finally {
                busy = null
            }
        }
    }

    fun logMeal(m: PrepMealOut) {
        scope.launch {
            busy = m.id
            error = null
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val res = withContext(Dispatchers.IO) { api.prepLogMeal(m.id) }
                notice = "Logged ${res.logged} item" +
                    (if (res.logged == 1) "" else "s") + " to ${res.slot}."
                plan?.id?.let { id ->
                    plan = withContext(Dispatchers.IO) { api.prepPlan(id) }
                }
            } catch (e: Exception) {
                error = e.message ?: "Could not log it"
            } finally {
                busy = null
            }
        }
    }

    fun buildList() {
        val id = plan?.id ?: return
        scope.launch {
            generating = true
            error = null
            try {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                val list = withContext(Dispatchers.IO) { api.prepShoppingList(id) }
                notice = "Shopping list ready — ${list.items.size} item" +
                    (if (list.items.size == 1) "" else "s") + " to buy" +
                    (
                        if (list.coveredByPantry > 0) {
                            ", ${list.coveredByPantry} already in the pantry."
                        } else {
                            "."
                        }
                        )
                plan = withContext(Dispatchers.IO) { api.prepPlan(id) }
            } catch (e: Exception) {
                error = e.message ?: "Could not build the list"
            } finally {
                generating = false
            }
        }
    }

    PullableMetricBox(
        refreshing = refreshing,
        onRefresh = { refreshing = true; try { fetch() } finally { refreshing = false } },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            error?.let { item { ErrorText(it) } }
            notice?.let {
                item { Text(it, color = NeonMV.Lime, fontSize = 12.sp) }
            }
            if (loading && plan == null) item { MutedText("Loading…") }

            targets?.let { item { TargetsCard(it, showTargets) { showTargets = !showTargets } } }

            val p = plan
            if (p == null) {
                if (!loading) {
                    item {
                        NoPlanCard(
                            days = draftDays,
                            slots = draftSlots,
                            generating = generating,
                            onDays = { draftDays = it },
                            onToggleSlot = { s ->
                                draftSlots = if (s in draftSlots) {
                                    draftSlots - s
                                } else {
                                    draftSlots + s
                                }
                            },
                            onGenerate = ::generate,
                        )
                    }
                }
                return@LazyColumn
            }

            item {
                PlanHeaderCard(
                    plan = p,
                    sub = sub,
                    generating = generating,
                    onSub = { sub = it },
                    onShoppingList = ::buildList,
                )
            }

            if (sub == "prep") {
                items(p.components, key = { it.id }) { c ->
                    ComponentRow(c, busy == c.id) { tickComponent(c) }
                }
                val uncostable = p.components.count { it.unresolved }
                if (uncostable > 0) {
                    item {
                        MutedText(
                            "$uncostable component" + (if (uncostable == 1) "" else "s") +
                                " could not be matched to a food, so the calorie and " +
                                "protein totals are partial rather than wrong.",
                        )
                    }
                }
            } else {
                val spares = p.components.filter { (it.spare ?: 0.0) >= 1.0 }
                val shorts = p.components.filter { it.short }
                if (spares.isNotEmpty() || shorts.isNotEmpty()) {
                    item { LedgerCard(spares, shorts) }
                }
                items(p.schedule, key = { it.day }) { d ->
                    DayCard(
                        day = d,
                        busy = busy,
                        onStatus = ::setStatus,
                        onLog = ::logMeal,
                    )
                }
            }

            item {
                Text(
                    if (generating) "Planning…" else "Plan a different week",
                    color = NeonMV.Cyan,
                    fontSize = 12.sp,
                    modifier = Modifier.padding(vertical = 8.dp)
                        .clickable(enabled = !generating) { generate() },
                )
            }
        }
    }
}

// ── pieces ───────────────────────────────────────────────────────────

@Composable
private fun TargetsCard(t: PrepTargetsOut, expanded: Boolean, onToggle: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        if (!t.ok) {
            // A refusal is a real answer. Showing a default number here
            // would be a calorie target the app invented, and it would
            // be acted on.
            MutedText(t.reason ?: "Not enough profile detail for a target.")
            return@Column
        }
        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            BigStat("${t.overrideKcal ?: t.targetKcal}", "kcal a day")
            BigStat("${t.proteinG}", "g protein")
            t.expectedLossKgPerWeek?.takeIf { it > 0 }?.let {
                BigStat("$it", "kg a week")
            }
        }
        if (t.weightStale) {
            Text(
                "Built on your weight from ${t.weightMeasuredOn} — " +
                    "${t.weightAgeDays} days ago. Everything above inherits " +
                    "that drift, and will look consistent while being wrong.",
                color = NeonMV.Amber, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        Text(
            if (expanded) "hide" else "how this was worked out",
            color = NeonMV.Cyan, fontSize = 11.sp,
            modifier = Modifier.padding(top = 6.dp).clickable { onToggle() },
        )
        if (expanded) {
            t.overrideKcal?.let {
                Text(
                    "You set $it kcal by hand, so plans use that. The " +
                        "estimate below is for comparison.",
                    color = NeonMV.Amber, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            DetailLine("Resting burn (${t.method})", "${t.bmrKcal} kcal")
            DetailLine(
                "× ${t.activityFactor} for ${t.activityLevel} activity",
                "${t.tdeeKcal} kcal",
            )
            t.deficitKcal?.takeIf { it > 0 }?.let {
                DetailLine("− deficit to lose weight", "$it kcal")
            }
            if (t.proteinRangeG.size == 2) {
                DetailLine(
                    if (t.goalWeightKg != null) {
                        "Protein, scaled to your goal weight"
                    } else {
                        "Protein, scaled to bodyweight"
                    },
                    "${t.proteinRangeG[0]}–${t.proteinRangeG[1]} g",
                )
            }
            if (t.hitFloor) {
                Text(
                    "The full deficit would have gone below a safe floor, so " +
                        "it was trimmed. The figure above is what was applied.",
                    color = NeonMV.Amber, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            t.caveat?.let {
                Text(
                    it, color = NeonMV.Muted, fontSize = 10.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        }
    }
}

@Composable
private fun BigStat(value: String, label: String) {
    Column {
        Text(value, color = NeonMV.Ink, fontSize = 24.sp, fontWeight = FontWeight.SemiBold)
        Text(label, color = NeonMV.Muted, fontSize = 10.sp)
    }
}

@Composable
private fun DetailLine(label: String, value: String) {
    Row(
        Modifier.fillMaxWidth().padding(top = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = NeonMV.Muted, fontSize = 11.sp)
        Text(value, color = NeonMV.Ink, fontSize = 11.sp)
    }
}

@Composable
private fun NoPlanCard(
    days: Int,
    slots: List<String>,
    generating: Boolean,
    onDays: (Int) -> Unit,
    onToggleSlot: (String) -> Unit,
    onGenerate: () -> Unit,
) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text("No prep plan yet", color = NeonMV.Ink, fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold)
        Text(
            "Pick a few things to batch cook at the weekend and the week " +
                "assembles itself from them. Nothing is fixed — skip a meal " +
                "or eat out and the plan tells you what that leaves spare.",
            color = NeonMV.Muted, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp),
        )
        Row(
            Modifier.padding(top = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Chip("Mon–Fri", days == 5) { onDays(5) }
            Chip("Mon–Sun", days == 7) { onDays(7) }
        }
        Text("Meals to plan", color = NeonMV.Muted, fontSize = 10.sp,
            modifier = Modifier.padding(top = 10.dp))
        Row(
            Modifier.padding(top = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf("breakfast", "lunch", "dinner", "snack").forEach { s ->
                Chip(s.replaceFirstChar { it.uppercase() }, s in slots) { onToggleSlot(s) }
            }
        }
        Text(
            "Whatever you leave out stays yours to sort out — the plan says " +
                "so rather than showing the week as short of target.",
            color = NeonMV.Muted, fontSize = 10.sp,
            modifier = Modifier.padding(top = 8.dp),
        )
        Text(
            if (generating) "Planning…" else "Plan next week",
            color = if (slots.isEmpty()) NeonMV.Muted else NeonMV.OnAccent,
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier
                .padding(top = 12.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(if (slots.isEmpty()) NeonMV.Track else NeonMV.Cyan)
                .clickable(enabled = !generating && slots.isNotEmpty()) { onGenerate() }
                .padding(horizontal = 14.dp, vertical = 8.dp),
        )
    }
}

@Composable
private fun PlanHeaderCard(
    plan: PrepPlanOut,
    sub: String,
    generating: Boolean,
    onSub: (String) -> Unit,
    onShoppingList: () -> Unit,
) {
    val done = plan.components.count { it.done }
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text(
            plan.headline ?: "This week",
            color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Week of ${plan.startDay} · ${plan.components.size} things to cook · " +
                "$done/${plan.components.size} done",
            color = NeonMV.Muted, fontSize = 11.sp,
            modifier = Modifier.padding(top = 4.dp),
        )
        plan.budgets.uncoveredKcal?.takeIf { it > 0 }?.let {
            Text(
                "These meals cover about " +
                    "${(plan.budgets.coveredShare * 100).roundToInt()}% of your day. " +
                    "The remaining ~$it kcal is whatever you eat outside them — " +
                    "it is not a shortfall.",
                color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        plan.warnings.forEach { w ->
            Text(
                w, color = NeonMV.Amber, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        plan.notes?.takeIf { it.isNotBlank() }?.let {
            Text(
                it, color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        Row(
            Modifier.padding(top = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Chip("Prep day", sub == "prep") { onSub("prep") }
            Chip("The week", sub == "week") { onSub("week") }
        }
        Text(
            if (generating) "Working…" else "Shopping list",
            color = NeonMV.Cyan, fontSize = 12.sp,
            modifier = Modifier.padding(top = 10.dp)
                .clickable(enabled = !generating) { onShoppingList() },
        )
    }
}

@Composable
private fun ComponentRow(c: PrepComponentOut, busy: Boolean, onTick: () -> Unit) {
    val accent = when (c.kind) {
        "protein" -> NeonMV.Bad
        "grain" -> NeonMV.Amber
        "veg" -> NeonMV.Lime
        "sauce" -> NeonMV.Periwinkle
        else -> NeonMV.Track
    }
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Checkbox(
            checked = c.done,
            onCheckedChange = { if (!busy) onTick() },
            colors = CheckboxDefaults.colors(
                checkedColor = NeonMV.Lime,
                uncheckedColor = NeonMV.Track,
                checkmarkColor = NeonMV.OnAccent,
            ),
            modifier = Modifier.size(28.dp),
        )
        Column(Modifier.padding(start = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(6.dp).clip(RoundedCornerShape(3.dp)).background(accent),
                )
                Text(
                    "  ${c.kind.uppercase()}",
                    color = NeonMV.Muted, fontSize = 9.sp,
                )
            }
            Text(
                c.name,
                color = if (c.done) NeonMV.Muted else NeonMV.Ink,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(top = 2.dp),
            )
            Text(
                buildString {
                    append(
                        if (c.quantity == null) {
                            "—"
                        } else {
                            val q = c.quantity
                            val txt = if (q == q.roundToInt().toDouble()) {
                                "${q.roundToInt()}"
                            } else {
                                "$q"
                            }
                            txt + (c.unit?.let { " $it" } ?: "")
                        },
                    )
                    append(" · ${c.portions} portion")
                    if (c.portions != 1) append("s")
                    c.gramsPerPortion?.let { append(" · ${it.roundToInt()} g each") }
                },
                color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 2.dp),
            )
            c.prepNote?.let {
                Text(
                    it, color = NeonMV.Ink, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            if (c.unresolved) {
                Text(
                    "No nutrition for this one — ${c.unresolvedReason}.",
                    color = NeonMV.Amber, fontSize = 10.sp,
                    modifier = Modifier.padding(top = 3.dp),
                )
            }
        }
    }
}

@Composable
private fun LedgerCard(spares: List<PrepComponentOut>, shorts: List<PrepComponentOut>) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text("WHAT IS SPARE", color = NeonMV.Muted, fontSize = 10.sp,
            fontWeight = FontWeight.SemiBold)
        spares.forEach { c ->
            Row(Modifier.padding(top = 4.dp)) {
                Text(c.name, color = NeonMV.Ink, fontSize = 12.sp)
                Text(
                    "  ${fmtPortions(c.spare)} unclaimed",
                    color = NeonMV.Muted, fontSize = 11.sp,
                )
            }
        }
        shorts.forEach { c ->
            Row(Modifier.padding(top = 4.dp)) {
                Text(c.name, color = NeonMV.Ink, fontSize = 12.sp)
                Text(
                    "  short ${fmtPortions(abs(c.spare ?: 0.0))} — a meal later in " +
                        "the week has nothing behind it",
                    color = NeonMV.Amber, fontSize = 11.sp,
                )
            }
        }
        Text(
            "Spare portions are not a mistake. Move a meal to a later day, or " +
                "freeze them.",
            color = NeonMV.Muted, fontSize = 10.sp,
            modifier = Modifier.padding(top = 6.dp),
        )
    }
}

@Composable
private fun DayCard(
    day: app.myvitals.sync.PrepDayOut,
    busy: Long?,
    onStatus: (PrepMealOut, String) -> Unit,
    onLog: (PrepMealOut) -> Unit,
) {
    val isToday = day.day == LocalDate.now().toString()
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card)
            .then(
                if (isToday) {
                    Modifier.border(1.dp, NeonMV.Cyan, RoundedCornerShape(12.dp))
                } else {
                    Modifier
                },
            )
            .padding(12.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom,
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(day.weekday, color = NeonMV.Ink, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold)
                Text("  ${day.day}", color = NeonMV.Muted, fontSize = 10.sp)
            }
            Text(
                (day.plannedKcal?.let { "${it.roundToInt()} kcal" } ?: "—") +
                    (day.budgetKcal?.let { " of ~${it.roundToInt()}" } ?: ""),
                color = NeonMV.Muted, fontSize = 11.sp,
            )
        }
        if (day.meals.isEmpty()) {
            Text("Nothing planned.", color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp))
        }
        day.meals.forEach { m -> MealRow(m, busy == m.id, onStatus, onLog) }
    }
}

@Composable
private fun MealRow(
    m: PrepMealOut,
    busy: Boolean,
    onStatus: (PrepMealOut, String) -> Unit,
    onLog: (PrepMealOut) -> Unit,
) {
    val off = m.status == "skipped" || m.status == "eating_out"
    Column(Modifier.fillMaxWidth().padding(top = 10.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(m.slot.uppercase(), color = NeonMV.Muted, fontSize = 9.sp)
            Text(
                "  ${m.name}",
                color = if (off) NeonMV.Muted else NeonMV.Ink,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        Text(
            m.estKcal?.let { "${it.roundToInt()} kcal" } ?: "—",
            color = NeonMV.Muted, fontSize = 11.sp,
        )
        m.assemblyNote?.let {
            Text(it, color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 3.dp))
        }
        Row(
            Modifier.padding(top = 3.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            m.estProteinG?.let {
                Text("${it.roundToInt()} g protein", color = NeonMV.Muted, fontSize = 10.sp)
            }
            m.estFatG?.let {
                Text("${it.roundToInt()} g fat", color = NeonMV.Muted, fontSize = 10.sp)
            }
            if (m.fatAssessment?.verdict in listOf("high", "very_high")) {
                Text("over your per-meal fat target", color = NeonMV.Amber, fontSize = 10.sp)
            }
            if (m.unresolvedCount > 0) {
                Text(
                    "partial — ${m.unresolvedCount} not costed",
                    color = NeonMV.Amber, fontSize = 10.sp,
                )
            }
        }
        Row(
            Modifier.padding(top = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Chip("Making this", m.status == "accepted", !busy) { onStatus(m, "accepted") }
            Chip("Eating out", m.status == "eating_out", !busy) { onStatus(m, "eating_out") }
            Chip("Skip", m.status == "skipped", !busy) { onStatus(m, "skipped") }
        }
        Text(
            "Log it",
            color = if (busy || m.uses.isEmpty()) NeonMV.Muted else NeonMV.Cyan,
            fontSize = 11.sp,
            modifier = Modifier.padding(top = 6.dp)
                .clickable(enabled = !busy && m.uses.isNotEmpty()) { onLog(m) },
        )
    }
}

@Composable
private fun Chip(
    label: String,
    selected: Boolean,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    Text(
        label,
        color = if (selected) NeonMV.Lime else NeonMV.Muted,
        fontSize = 11.sp,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .border(
                1.dp,
                if (selected) NeonMV.Lime else NeonMV.Track,
                RoundedCornerShape(999.dp),
            )
            .clickable(enabled = enabled) { onClick() }
            .padding(horizontal = 10.dp, vertical = 5.dp),
    )
}

// ── helpers ──────────────────────────────────────────────────────────

/** A plan made at the weekend is for the week ahead. */
private fun nextMondayIso(): String =
    LocalDate.now().with(TemporalAdjusters.next(DayOfWeek.MONDAY)).toString()

private fun fmtPortions(v: Double?): String {
    val d = v ?: 0.0
    val n = if (d == d.roundToInt().toDouble()) "${d.roundToInt()}" else "$d"
    return "$n portion" + (if (d == 1.0) "" else "s")
}
