package app.myvitals.ui.meals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import app.myvitals.ui.common.userMessage
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
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
import app.myvitals.ui.LoadFailedCard
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonRingCaption
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
 * Fetching wrapper around the stateless [PrepContent].
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
    // A plan of null is only "no plan yet" once the server SAID so; a
    // failed request used to fall through to the no-plan card.
    var planKnown by remember { mutableStateOf(false) }
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
                if (!resp.isSuccessful) throw IllegalStateException("prep/current HTTP ${resp.code()}")
                plan = resp.body()
                planKnown = true
                targets = runCatching { api.prepTargets() }.getOrNull()
            }
            error = null
        } catch (e: Exception) {
            error = e.message ?: "load failed"
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
                    api.prepGenerate(PrepGenerateIn(start = nextMondayIso(), days = draftDays, slots = draftSlots))
                }
                planKnown = true
                sub = "prep"
            } catch (e: Exception) {
                error = e.userMessage("Could not plan the week")
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
                plan = withContext(Dispatchers.IO) { api.prepPatchComponent(c.id, PrepComponentPatch(done = !c.done)) }
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
                // suggested, so a mis-tap is one tap to undo.
                val next = if (m.status == status) "suggested" else status
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                plan = withContext(Dispatchers.IO) { api.prepPatchMeal(m.id, PrepMealPatch(status = next)) }
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
                notice = "Logged ${res.logged} item" + (if (res.logged == 1) "" else "s") + " to ${res.slot}."
                plan?.id?.let { id -> plan = withContext(Dispatchers.IO) { api.prepPlan(id) } }
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
                    (if (list.coveredByPantry > 0) ", ${list.coveredByPantry} already in the pantry." else ".")
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
        PrepContent(
            plan = plan, planKnown = planKnown, targets = targets, loading = loading,
            error = error, notice = notice, sub = sub, busy = busy, generating = generating,
            showTargets = showTargets, draftDays = draftDays, draftSlots = draftSlots,
            today = LocalDate.now().toString(),
            onRetry = { scope.launch { fetch() } },
            onSub = { sub = it },
            onToggleTargets = { showTargets = !showTargets },
            onDays = { draftDays = it },
            onToggleSlot = { s -> draftSlots = if (s in draftSlots) draftSlots - s else draftSlots + s },
            onGenerate = ::generate,
            onShoppingList = ::buildList,
            onTick = ::tickComponent,
            onStatus = ::setStatus,
            onLog = ::logMeal,
        )
    }
}

/** Component kind → colour. Protein is MAGENTA: it used to be the rose
 *  `NeonMV.Bad`, which on this app means crisis — a chicken breast is not
 *  an error. */
internal fun prepKindColor(kind: String): Color = when (kind) {
    "protein" -> NeonMV.Magenta
    "grain" -> NeonMV.Amber
    "veg" -> NeonMV.Lime
    "sauce" -> NeonMV.Periwinkle
    else -> NeonMV.Muted
}

@Composable
fun PrepContent(
    plan: PrepPlanOut?,
    planKnown: Boolean,
    targets: PrepTargetsOut?,
    loading: Boolean,
    error: String?,
    notice: String?,
    sub: String,
    busy: Long?,
    generating: Boolean,
    showTargets: Boolean,
    draftDays: Int,
    draftSlots: List<String>,
    today: String,
    onRetry: () -> Unit,
    onSub: (String) -> Unit,
    onToggleTargets: () -> Unit,
    onDays: (Int) -> Unit,
    onToggleSlot: (String) -> Unit,
    onGenerate: () -> Unit,
    onShoppingList: () -> Unit,
    onTick: (PrepComponentOut) -> Unit,
    onStatus: (PrepMealOut, String) -> Unit,
    onLog: (PrepMealOut) -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        // Room above the hero so its glow is not clipped by the list edge.
        contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (!planKnown && error != null) {
            item { LoadFailedCard("Couldn't load your prep plan", error, onRetry) }
            return@LazyColumn
        }
        error?.let { item { ErrorText(it) } }
        notice?.let { item { Text(it, color = NeonMV.Lime, fontSize = 12.sp) } }
        if (!planKnown) {
            item { MutedText(if (loading) "Loading your prep plan…" else "") }
            return@LazyColumn
        }

        val p = plan
        if (p == null) {
            targets?.let { item { TargetsCard(it, showTargets, onToggleTargets) } }
            item {
                NoPlanCard(
                    days = draftDays, slots = draftSlots, generating = generating,
                    onDays = onDays, onToggleSlot = onToggleSlot, onGenerate = onGenerate,
                )
            }
            return@LazyColumn
        }

        item { PrepHero(p, today, generating, onShoppingList) }
        item {
            Segmented(
                listOf("prep" to "Prep day", "week" to "The week"), sub, enabled = true,
            ) { onSub(it) }
        }

        if (sub == "prep") {
            items(p.components, key = { it.id }) { c -> ComponentCard(c, busy == c.id) { onTick(c) } }
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
            if (spares.isNotEmpty() || shorts.isNotEmpty()) item { LedgerCard(spares, shorts) }
            items(p.schedule, key = { it.day }) { d ->
                DayCard(day = d, isToday = d.day == today, busy = busy, onStatus = onStatus, onLog = onLog)
            }
        }

        targets?.let { item { TargetsCard(it, showTargets, onToggleTargets) } }
        item {
            Text(
                if (generating) "Planning…" else "Plan a different week",
                color = NeonMV.Cyan, fontSize = 13.sp,
                modifier = Modifier.heightIn(min = 44.dp).padding(vertical = 12.dp)
                    .clickable(enabled = !generating) { onGenerate() },
            )
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

/**
 * Prep-day hero: a segmented ring, one segment per component, filled in its
 * kind colour once ticked; beside it the week as seven mini bars of planned
 * against budget energy (both server values), today in cyan.
 */
@Composable
private fun PrepHero(plan: PrepPlanOut, today: String, generating: Boolean, onShoppingList: () -> Unit) {
    val comps = plan.components
    val done = comps.count { it.done }
    var showWhy by remember { mutableStateOf(false) }
    NeonHeroCard(accent = NeonMV.Lime) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(120.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.size(120.dp)) {
                    val sw = 10.dp.toPx()
                    val inset = sw / 2 + 4.dp.toPx()
                    val arc = Size(size.width - inset * 2, size.height - inset * 2)
                    val tl = Offset(inset, inset)
                    val n = comps.size.coerceAtLeast(1)
                    val gap = if (n > 1) 10f else 0f
                    val sweep = 360f / n - gap
                    comps.forEachIndexed { i, c ->
                        val start = -90f + i * (360f / n) + gap / 2
                        val col = if (c.done) prepKindColor(c.kind) else NeonMV.Track
                        if (c.done) drawArc(col.copy(alpha = 0.22f), start, sweep, false, tl, arc,
                            style = Stroke(sw * 2f, cap = StrokeCap.Butt))
                        drawArc(col, start, sweep, false, tl, arc, style = Stroke(sw, cap = StrokeCap.Butt))
                    }
                    if (comps.isEmpty()) drawArc(NeonMV.Track, 0f, 360f, false, tl, arc, style = Stroke(sw))
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    NeonNumber("$done / ${comps.size}", size = 22)
                    NeonRingCaption("cooked")
                }
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(plan.headline ?: "This week", color = NeonMV.Ink, fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold, maxLines = 2)
                Text("Week of ${prettyDay(plan.startDay)}", color = NeonMV.Muted, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 2.dp))
                Spacer(Modifier.height(8.dp))
                WeekStrip(plan, today)
            }
        }
        // Warnings stay out in the open — time-sensitive and actionable.
        plan.warnings.forEach { w ->
            Text(w, color = NeonMV.Amber, fontSize = 11.sp, lineHeight = 15.sp, modifier = Modifier.padding(top = 8.dp))
        }
        val hasNotes = !plan.notes.isNullOrBlank() || (plan.budgets.uncoveredKcal ?: 0) > 0
        Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ActionButton(if (generating) "Working…" else "Shopping list", NeonMV.Cyan, enabled = !generating,
                modifier = Modifier.weight(1f), onClick = onShoppingList)
            if (hasNotes) {
                ActionButton(if (showWhy) "Hide reasoning" else "Why this plan", NeonMV.Muted,
                    modifier = Modifier.weight(1f)) { showWhy = !showWhy }
            }
        }
        if (showWhy) {
            plan.budgets.uncoveredKcal?.takeIf { it > 0 }?.let {
                Text(
                    "These meals cover about ${(plan.budgets.coveredShare * 100).roundToInt()}% of your day. " +
                        "The remaining ~$it kcal is whatever you eat outside them — it is not a shortfall.",
                    color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 15.sp, modifier = Modifier.padding(top = 8.dp),
                )
            }
            plan.notes?.takeIf { it.isNotBlank() }?.let {
                Text(it, color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 15.sp, modifier = Modifier.padding(top = 6.dp))
            }
        }
    }
}

/** Seven mini bars: planned ÷ budget energy per day (server values). A day
 *  with no budget or nothing planned shows an empty track, not a zero. */
@Composable
private fun WeekStrip(plan: PrepPlanOut, today: String) {
    Row(Modifier.fillMaxWidth().height(44.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        for (d in plan.schedule.take(7)) {
            val f = run {
                val pk = d.plannedKcal; val bk = d.budgetKcal
                if (pk != null && bk != null && bk > 0) (pk / bk).toFloat().coerceIn(0f, 1f) else 0f
            }
            val isToday = d.day == today
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(Modifier.width(12.dp).weight(1f).clip(RoundedCornerShape(3.dp)).background(NeonMV.Track),
                    contentAlignment = Alignment.BottomCenter) {
                    if (f > 0f) Box(Modifier.fillMaxWidth().fillMaxHeight(f)
                        .background(if (isToday) NeonMV.Cyan else NeonMV.Lime.copy(alpha = 0.7f)))
                }
                Text(d.weekday.take(1), color = if (isToday) NeonMV.Cyan else NeonMV.Muted, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun ActionButton(
    label: String, color: Color, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit,
) {
    Box(
        modifier.heightIn(min = 44.dp).clip(RoundedCornerShape(12.dp))
            .border(1.dp, if (enabled) color.copy(alpha = 0.45f) else NeonMV.Line, RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 10.dp),
        contentAlignment = Alignment.Center,
    ) { Text(label, color = if (enabled) color else NeonMV.Muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold) }
}

/** A ≥44dp segmented control. */
@Composable
private fun Segmented(
    options: List<Pair<String, String>>, selected: String, enabled: Boolean, onPick: (String) -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    Row(Modifier.fillMaxWidth().height(44.dp).clip(shape).border(1.dp, NeonMV.Line, shape).background(NeonMV.Card)) {
        options.forEachIndexed { i, (key, label) ->
            val on = key == selected
            if (i > 0) Box(Modifier.width(1.dp).fillMaxHeight().background(NeonMV.Line))
            SegCell(label, on, enabled) { onPick(key) }
        }
    }
}

@Composable
private fun RowScope.SegCell(label: String, on: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.weight(1f).fillMaxHeight()
            .background(if (on) NeonMV.Lime.copy(alpha = 0.14f) else Color.Transparent)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (on) NeonMV.Lime else if (enabled) NeonMV.Ink else NeonMV.Muted,
            fontSize = 12.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/** A component to cook: ≥64dp, a full-height stripe in its kind colour. */
@Composable
private fun ComponentCard(c: PrepComponentOut, busy: Boolean, onTick: () -> Unit) {
    val accent = prepKindColor(c.kind)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).height(IntrinsicSize.Min)
            .clip(NeonCardShape).background(NeonMV.Card).clickable(enabled = !busy) { onTick() },
    ) {
        Box(Modifier.width(5.dp).fillMaxHeight().background(if (c.done) accent else accent.copy(alpha = 0.55f)))
        Row(Modifier.weight(1f).padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Text(c.kind.uppercase(), color = accent, fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                Text(c.name, color = if (c.done) NeonMV.Muted else NeonMV.Ink, fontSize = 14.sp,
                    fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 2.dp))
                Text(
                    buildString {
                        append(c.quantity?.let { q ->
                            (if (q == q.roundToInt().toDouble()) "${q.roundToInt()}" else "$q") + (c.unit?.let { " $it" } ?: "")
                        } ?: "—")
                        append(" · ${c.portions} portion")
                        if (c.portions != 1) append("s")
                        c.gramsPerPortion?.let { append(" · ${it.roundToInt()} g each") }
                    },
                    color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp),
                )
                c.prepNote?.let { Text(it, color = NeonMV.Ink, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp)) }
                if (c.unresolved) {
                    Text("No nutrition for this one — ${c.unresolvedReason}.", color = NeonMV.Amber,
                        fontSize = 10.sp, modifier = Modifier.padding(top = 3.dp))
                }
            }
            Checkbox(
                checked = c.done,
                onCheckedChange = { if (!busy) onTick() },
                colors = CheckboxDefaults.colors(
                    checkedColor = accent, uncheckedColor = NeonMV.Track, checkmarkColor = NeonMV.OnAccent,
                ),
            )
        }
    }
}

@Composable
private fun DayCard(
    day: app.myvitals.sync.PrepDayOut,
    isToday: Boolean,
    busy: Long?,
    onStatus: (PrepMealOut, String) -> Unit,
    onLog: (PrepMealOut) -> Unit,
) {
    Column(
        Modifier.fillMaxWidth().clip(NeonCardShape).background(NeonMV.Card)
            .then(if (isToday) Modifier.border(1.dp, NeonMV.Cyan, NeonCardShape) else Modifier)
            .padding(14.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Bottom) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(day.weekday, color = if (isToday) NeonMV.Cyan else NeonMV.Ink, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold)
                // "24 Aug", not "2026-08-24".
                Text("  " + runCatching {
                    LocalDate.parse(day.day).format(java.time.format.DateTimeFormatter.ofPattern("d MMM"))
                }.getOrDefault(day.day), color = NeonMV.Muted, fontSize = 10.sp)
            }
            Text(
                (day.plannedKcal?.let { "${it.roundToInt()} kcal" } ?: "—") +
                    (day.budgetKcal?.let { " of ~${it.roundToInt()}" } ?: ""),
                color = NeonMV.Muted, fontSize = 11.sp,
            )
        }
        if (day.meals.isEmpty()) {
            Text("Nothing planned.", color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
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
    val fa = m.fatAssessment
    val fatC = fatVerdictColor(fa?.verdict)
    Column(Modifier.fillMaxWidth().padding(top = 12.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(m.slot.uppercase(), color = NeonMV.Muted, fontSize = 9.sp)
            Text("  ${m.name}", color = if (off) NeonMV.Muted else NeonMV.Ink, fontSize = 13.sp, fontWeight = FontWeight.Medium)
        }
        m.assemblyNote?.let { Text(it, color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 3.dp)) }
        Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(m.estKcal?.let { "${it.roundToInt()} kcal" } ?: "— kcal", color = NeonMV.Muted, fontSize = 11.sp)
            m.estProteinG?.let { Text("${it.roundToInt()} g protein", color = NeonMV.Muted, fontSize = 11.sp) }
        }
        // The fat verdict on EVERY meal. Grey when it cannot be judged —
        // "unknown" must not borrow the reassurance of "fine".
        Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(fatC))
            Text(
                (m.estFatG?.let { "${it.roundToInt()} g fat" } ?: "fat unknown") + " · " + when (fa?.verdict) {
                    "ok" -> "within your per-meal target"
                    "approaching" -> "close to your per-meal target"
                    "high" -> "over your per-meal target"
                    "very_high" -> "well over your per-meal target"
                    else -> "can't judge fat yet"
                },
                color = if (fa == null || fa.verdict == "unknown") NeonMV.Muted else fatC,
                fontSize = 11.sp, modifier = Modifier.padding(start = 6.dp),
            )
        }
        if (m.unresolvedCount > 0) {
            Text("partial — ${m.unresolvedCount} not costed", color = NeonMV.Amber, fontSize = 10.sp,
                modifier = Modifier.padding(top = 2.dp))
        }
        Spacer(Modifier.height(8.dp))
        Segmented(
            listOf("accepted" to "Making this", "eating_out" to "Eating out", "skipped" to "Skip"),
            m.status, enabled = !busy,
        ) { onStatus(m, it) }
        Spacer(Modifier.height(6.dp))
        ActionButton("Log it", NeonMV.Cyan, Modifier.fillMaxWidth(), enabled = !busy && m.uses.isNotEmpty()) { onLog(m) }
    }
}

@Composable
private fun Chip(
    label: String,
    selected: Boolean,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    Box(
        Modifier
            .heightIn(min = 44.dp)
            .clip(RoundedCornerShape(999.dp))
            .border(1.dp, if (selected) NeonMV.Lime else NeonMV.Track, RoundedCornerShape(999.dp))
            .clickable(enabled = enabled) { onClick() }
            .padding(horizontal = 12.dp),
        contentAlignment = Alignment.Center,
    ) { Text(label, color = if (selected) NeonMV.Lime else NeonMV.Muted, fontSize = 12.sp) }
}

// ── pieces kept from before UI-6 ────────────────────────────────────

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

// ── helpers ──────────────────────────────────────────────────────────

/** A plan made at the weekend is for the week ahead. */
private fun nextMondayIso(): String =
    LocalDate.now().with(TemporalAdjusters.next(DayOfWeek.MONDAY)).toString()

private fun fmtPortions(v: Double?): String {
    val d = v ?: 0.0
    val n = if (d == d.roundToInt().toDouble()) "${d.roundToInt()}" else "$d"
    return "$n portion" + (if (d == 1.0) "" else "s")
}


/** "Mon 24 Aug", not "2026-08-24". An ISO date is a storage format; it
 *  is not what a week is called when someone is deciding what to cook. */
private fun prettyDay(iso: String): String = runCatching {
    java.time.LocalDate.parse(iso)
        .format(java.time.format.DateTimeFormatter.ofPattern("EEE d MMM"))
}.getOrDefault(iso)
