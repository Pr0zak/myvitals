package app.myvitals.ui.meals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.LogDayOut
import app.myvitals.sync.LogEntryIn
import app.myvitals.sync.LogMealOut
import app.myvitals.sync.PrepTargetsOut
import app.myvitals.sync.RecentEntryOut
import app.myvitals.sync.RecipeOut
import app.myvitals.sync.RepeatDayIn
import app.myvitals.ui.LoadFailedCard
import app.myvitals.ui.StaleNote
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonRing
import app.myvitals.ui.neon.NeonRingCaption
import app.myvitals.ui.neon.NeonScreen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

/**
 * Direction A — Meals IS today. Fetching wrapper around [MealsTodayContent].
 *
 * Everything shown is fetched, never derived on the phone: the totals,
 * the per-slot grouping and the per-meal fat verdict all come from
 * `/meals/log`, and the energy target from `/meals/prep/targets`.
 *
 * UI-6: the hero is an energy ring beside a per-MEAL fat column. Day-level
 * fat left the hero — fat is judged per meal (without a gall bladder the
 * constraint is how much lands at once), so a day total in the most
 * prominent spot pointed at the wrong number.
 */
@Composable
fun TodayTab(settings: SettingsRepository, onOpenMore: () -> Unit, onBack: (() -> Unit)? = null) {
    val scope = rememberCoroutineScope()
    var day by remember { mutableStateOf<LogDayOut?>(null) }
    var targets by remember { mutableStateOf<PrepTargetsOut?>(null) }
    var recents by remember { mutableStateOf<List<RecentEntryOut>>(emptyList()) }
    var recipes by remember { mutableStateOf<List<RecipeOut>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var actionError by remember { mutableStateOf<String?>(null) }
    // null = closed; otherwise the slot the dialog opens on.
    var addingSlot by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }

    val today = LocalDate.now().toString()

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            // Resolved per fetch, not captured from the first composition
            // (UX-D5): a tab resumed after midnight showed yesterday's log.
            val day0 = LocalDate.now().toString()
            withContext(Dispatchers.IO) {
                day = api.mealsLog(day0, 1).firstOrNull() ?: LogDayOut(day = day0)
                // Optional context, never a reason to fail the screen: a
                // missing target means the ring says so.
                targets = runCatching { api.prepTargets() }.getOrNull()
                recents = runCatching { api.mealsLogRecent(12) }.getOrDefault(emptyList())
                if (recipes.isEmpty()) {
                    recipes = runCatching { api.mealsRecipes() }.getOrDefault(emptyList())
                }
            }
            error = null
        } catch (e: Exception) {
            error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    fun act(block: suspend (api: app.myvitals.sync.BackendApi) -> Unit) {
        if (busy) return
        busy = true
        actionError = null
        scope.launch {
            runCatching {
                block(BackendClient.create(settings.backendUrl, settings.bearerToken))
            }.onFailure { actionError = "Couldn't log that: ${it.message ?: "error"}" }
            fetch()
            busy = false
        }
    }

    LaunchedEffect(Unit) { fetch() }

    addingSlot?.let { slot ->
        LogEntryDialog(
            settings = settings, day = today, recipes = recipes,
            initialSlot = slot,
            onDismiss = { addingSlot = null },
            onSave = { body ->
                addingSlot = null
                act { api -> withContext(Dispatchers.IO) { api.mealsAddLogEntry(body) } }
            },
        )
    }

    MealsTodayContent(
        day = day,
        targets = targets,
        recents = recents,
        loading = loading,
        error = error,
        actionError = actionError,
        busy = busy,
        refreshing = refreshing,
        dateLabel = LocalDate.now().format(DateTimeFormatter.ofPattern("EEE d MMM")),
        contentPadding = PaddingValues(0.dp),
        onBack = onBack,
        onRefresh = {
            scope.launch { refreshing = true; try { fetch() } finally { refreshing = false } }
        },
        onAdd = { slot -> addingSlot = slot },
        onOpenMore = onOpenMore,
        onRepeatYesterday = {
            act { api ->
                withContext(Dispatchers.IO) {
                    api.mealsRepeatDay(RepeatDayIn(
                        source = LocalDate.now().minusDays(1).toString(), target = today,
                    ))
                }
            }
        },
        onRecent = { r ->
            act { api ->
                withContext(Dispatchers.IO) {
                    api.mealsAddLogEntry(LogEntryIn(
                        day = today, slot = r.usualSlot,
                        foodId = r.foodId, recipeId = r.recipeId,
                        label = if (r.foodId == null && r.recipeId == null) r.label else null,
                        quantity = r.quantity, unit = r.unit, servings = r.servings,
                        manualKcal = r.manualKcal, manualFatG = r.manualFatG,
                    ))
                }
            }
        },
    )
}

/**
 * The per-meal fat verdict as a colour. `unknown` (and anything the client
 * does not recognise) is GREY — a verdict the app cannot reach must not
 * borrow the reassurance of one it can. High is amber, never rose: rose is
 * for crisis surfaces, and a rich dinner is not one.
 */
internal fun fatVerdictColor(verdict: String?): Color = when (verdict) {
    "ok" -> NeonMV.Lime
    "approaching" -> NeonMV.Amber.copy(alpha = 0.7f)
    "high", "very_high" -> NeonMV.Amber
    else -> NeonMV.Muted
}

/** Meal fat in grams: the assessment's figure, else the meal total. Null
 *  stays null — an uncostable meal has UNKNOWN fat, not zero. */
private fun mealFatG(meal: LogMealOut?): Double? =
    meal?.fatAssessment?.fatG ?: meal?.totals?.get("fat_g")

@Composable
fun MealsTodayContent(
    day: LogDayOut?,
    targets: PrepTargetsOut?,
    recents: List<RecentEntryOut>,
    loading: Boolean,
    error: String?,
    actionError: String?,
    busy: Boolean,
    refreshing: Boolean,
    dateLabel: String,
    contentPadding: PaddingValues,
    onBack: (() -> Unit)?,
    onRefresh: () -> Unit,
    onAdd: (String) -> Unit,
    onOpenMore: () -> Unit,
    onRepeatYesterday: () -> Unit,
    onRecent: (RecentEntryOut) -> Unit,
) {
    Box(Modifier.fillMaxSize()) {
        NeonScreen(
            title = "Meals",
            contentPadding = contentPadding,
            onBack = onBack,
            refreshing = refreshing,
            onRefresh = onRefresh,
            headerTrailing = { Text(dateLabel, color = NeonMV.Muted, fontSize = 12.sp) },
        ) {
            if (error != null && day != null) StaleNote("Showing what we last loaded — refresh failed.")
            when {
                // A failed load is not "nothing logged".
                day == null && error != null -> LoadFailedCard("Couldn't load today's log", error, onRefresh)
                day == null -> NeonHeroCard(accent = NeonMV.Lime) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        NeonRing(0f, NeonMV.Lime, 112.dp) { NeonRingCaption("loading") }
                        Spacer(Modifier.width(16.dp))
                        Text("Loading today's meals…", color = NeonMV.Muted, fontSize = 13.sp)
                    }
                }
                else -> TodayHero(day, targets)
            }
            actionError?.let { Text(it, color = NeonMV.Amber, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp)) }

            if (day != null) {
                if (recents.isNotEmpty()) {
                    NeonEyebrow("Log again")
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        // First, not last: as the trailing item it sat past
                        // the right edge — the hidden-affordance problem.
                        RecentTile("Same as yesterday", null, NeonMV.Cyan, enabled = !busy, onClick = onRepeatYesterday)
                        recents.forEach { r ->
                            RecentTile(
                                r.label,
                                r.quantity?.let { trimNum(it) + (r.unit?.let { u -> " $u" } ?: "") },
                                NeonMV.Ink, enabled = !busy,
                            ) { onRecent(r) }
                        }
                    }
                }

                NeonEyebrow("Meals")
                // Always all four slots. An empty one is shown as an empty
                // card, not hidden: "I have not eaten lunch" and "lunch is not
                // a thing I log" look identical once the row disappears.
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    for (slot in LOG_SLOTS) {
                        val meal = day.meals.firstOrNull { it.slot == slot }
                        if (meal == null || meal.entries.isEmpty()) EmptySlotCard(slot) { onAdd(slot) }
                        else SlotCard(meal)
                    }
                }

                Spacer(Modifier.height(14.dp))
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 56.dp).clip(NeonCardShape).background(NeonMV.Card)
                        .clickable(onClick = onOpenMore).padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("Plan & kitchen", color = NeonMV.Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                        Text("Week, prep, shopping, pantry, recipes", color = NeonMV.Muted,
                            fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp))
                    }
                    Icon(Icons.Filled.ChevronRight, null, tint = NeonMV.Muted)
                }
            } else if (loading) {
                Spacer(Modifier.height(4.dp))
            }
            Spacer(Modifier.height(96.dp))
        }

        // The one action this screen exists for, always in reach.
        Row(
            Modifier
                .align(Alignment.BottomCenter)
                .padding(16.dp)
                .fillMaxWidth()
                .height(52.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(NeonMV.Lime)
                .clickable { onAdd("dinner") },
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Add, null, tint = NeonMV.OnAccent, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("Log something", color = NeonMV.OnAccent, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        }
    }
}

/**
 * Energy ring against the target, with a per-meal fat column beside it.
 * No target → the ring sits at 0 and SAYS so; a made-up denominator would
 * make a real number look like progress toward something nobody set.
 */
@Composable
private fun TodayHero(day: LogDayOut, targets: PrepTargetsOut?) {
    val kcal = day.totals["kcal"]
    val target = targets?.takeIf { it.ok }?.targetKcal?.takeIf { it > 0 }
    val frac = if (kcal != null && target != null) (kcal / target).toFloat() else 0f
    NeonHeroCard(accent = NeonMV.Lime) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            NeonRing(frac, NeonMV.Lime, 112.dp) {
                NeonNumber(kcal?.let { "%,d".format(it.roundToInt()) } ?: "—", size = 22)
                NeonRingCaption(target?.let { "of %,d kcal".format(it) } ?: "no target set")
            }
            Spacer(Modifier.width(16.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                Text("FAT PER MEAL", color = NeonMV.Muted, fontSize = 10.sp,
                    fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
                for (slot in LOG_SLOTS) {
                    val meal = day.meals.firstOrNull { it.slot == slot }?.takeIf { it.entries.isNotEmpty() }
                    val c = if (meal == null) NeonMV.Track else fatVerdictColor(meal.fatAssessment?.verdict)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(10.dp).clip(CircleShape).background(c))
                        Text(slot.replaceFirstChar { it.uppercase() }, color = NeonMV.Ink, fontSize = 12.sp,
                            modifier = Modifier.padding(start = 8.dp).weight(1f))
                        if (meal == null) {
                            Text("not logged", color = NeonMV.Muted, fontSize = 11.sp)
                        } else {
                            NeonNumber(mealFatG(meal)?.let { "%.0f g".format(it) } ?: "— g",
                                color = if (meal.fatAssessment?.verdict == "unknown" || meal.fatAssessment == null)
                                    NeonMV.Muted else c, size = 13)
                        }
                    }
                }
            }
        }
        if (target == null && targets != null) {
            Text(
                targets.reason ?: "No energy target set — add your profile in Settings.",
                color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.padding(top = 10.dp),
            )
        }
        if (day.unresolvedCount > 0) {
            Text("${day.unresolvedCount} not costed — this understates the total",
                color = NeonMV.Amber, fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

@Composable
private fun RecentTile(label: String, sub: String?, color: Color, enabled: Boolean, onClick: () -> Unit) {
    Column(
        Modifier
            .heightIn(min = 44.dp)
            .widthIn(max = 180.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(NeonMV.CardHigh)
            .border(1.dp, NeonMV.Line, RoundedCornerShape(14.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(label, color = if (enabled) color else NeonMV.Muted, fontSize = 12.sp,
            fontWeight = FontWeight.Medium, maxLines = 1)
        sub?.let { Text(it, color = NeonMV.Muted, fontSize = 10.sp, maxLines = 1) }
    }
}

/** One meal: a stripe in the verdict colour, the meal's fat as the number. */
@Composable
private fun SlotCard(meal: LogMealOut) {
    val fa = meal.fatAssessment
    val c = fatVerdictColor(fa?.verdict)
    Row(
        Modifier.fillMaxWidth().height(IntrinsicSize.Min).clip(NeonCardShape).background(NeonMV.Card),
    ) {
        Box(Modifier.width(4.dp).fillMaxHeight().background(c))
        Column(Modifier.weight(1f).padding(horizontal = 14.dp, vertical = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(meal.slot.replaceFirstChar { it.uppercase() }, color = NeonMV.Ink, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                NeonNumber(mealFatG(meal)?.let { "%.0f".format(it) } ?: "—",
                    color = if (fa == null || fa.verdict == "unknown") NeonMV.Muted else c, size = 18)
                Text(" g fat", color = NeonMV.Muted, fontSize = 11.sp)
            }
            Text(meal.entries.joinToString(" · ") { it.label }, color = NeonMV.Muted, fontSize = 12.sp,
                maxLines = 2, modifier = Modifier.padding(top = 4.dp))
            Row(Modifier.padding(top = 4.dp)) {
                Text(meal.totals["kcal"]?.let { "${it.roundToInt()} kcal" } ?: "kcal unknown",
                    color = NeonMV.Muted, fontSize = 11.sp, modifier = Modifier.weight(1f))
            }
            fa?.let {
                Text(it.reason ?: fatVerdictLabel(it.verdict), color = if (it.verdict == "unknown") NeonMV.Muted else c,
                    fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}

/** An empty slot: a dashed card that opens the log dialog on that slot. */
@Composable
private fun EmptySlotCard(slot: String, onClick: () -> Unit) {
    Box(
        Modifier.fillMaxWidth().height(48.dp).clip(NeonCardShape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            drawRoundRect(
                NeonMV.Track, cornerRadius = CornerRadius(18.dp.toPx()),
                style = Stroke(1.5.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))),
            )
        }
        Text("+ Log ${slot}", color = NeonMV.Muted, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
}

/** The verdict in words, for when the server sent no reason line. */
private fun fatVerdictLabel(v: String): String = when (v) {
    "very_high" -> "well over your per-meal fat target"
    "high" -> "over your per-meal fat target"
    "approaching" -> "close to your per-meal fat target"
    "ok" -> "within your per-meal fat target"
    else -> "no per-meal fat target set"
}
