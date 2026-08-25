package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FoodOut
import app.myvitals.sync.LogDayOut
import app.myvitals.sync.LogDayPatch
import app.myvitals.sync.LogEntryIn
import app.myvitals.sync.LogStatsOut
import app.myvitals.sync.RecentEntryOut
import app.myvitals.sync.RecipeOut
import app.myvitals.sync.RepeatDayIn
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

/**
 * The food log — the phone mirror of the web's Log view.
 *
 * Intermittent logging is the design assumption, not a failure mode.
 * There is deliberately no streak, no completion percentage and no
 * notification anywhere here: a tracker that turns red the moment you
 * stop is a tracker you stop opening. A day with no entries renders as
 * an ordinary empty day.
 *
 * Completeness is DECLARED, never inferred — the app cannot tell "I
 * stopped logging" from "I stopped eating" — and the stats endpoint
 * refuses rather than averaging partly-logged days.
 *
 * Fat is assessed per MEAL, because a meal is the unit that matters
 * after a cholecystectomy.
 */

internal val LOG_SLOTS = listOf("breakfast", "lunch", "dinner", "snack")
private val LOG_DAY_FMT = DateTimeFormatter.ofPattern("EEE d MMM")

@Composable
fun LogTab(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    var days by remember { mutableStateOf<List<LogDayOut>>(emptyList()) }
    var stats by remember { mutableStateOf<LogStatsOut?>(null) }
    var recipes by remember { mutableStateOf<List<RecipeOut>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var addingFor by remember { mutableStateOf<String?>(null) }
    // The foods this user actually eats, ranked server-side by how often
    // and how recently. Before this, every entry began at an empty search
    // box — and about half this diet is packaged or eaten out, so the
    // same items recurred constantly and each had to be re-found.
    var recents by remember { mutableStateOf<List<RecentEntryOut>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val start = LocalDate.now().minusDays(6).toString()
            val (d, st) = withContext(Dispatchers.IO) {
                api.mealsLog(start, 7) to api.mealsLogStats(30)
            }
            // Newest first — you log what you just ate.
            days = d.reversed()
            stats = st
            if (recipes.isEmpty()) {
                recipes = withContext(Dispatchers.IO) { api.mealsRecipes() }
            }
            // A cold log has none, and the row simply hides — never an error.
            recents = withContext(Dispatchers.IO) {
                runCatching { api.mealsLogRecent(12) }.getOrDefault(emptyList())
            }
            error = null
        } catch (e: Exception) {
            if (days.isEmpty()) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    /** One tap: the food AND the portion, straight in. No form, no search. */
    fun logRecent(day: String, r: RecentEntryOut) {
        if (busy) return
        busy = true
        scope.launch {
            runCatching {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                withContext(Dispatchers.IO) {
                    api.mealsAddLogEntry(
                        LogEntryIn(
                            day = day, slot = r.usualSlot,
                            foodId = r.foodId, recipeId = r.recipeId,
                            label = if (r.foodId == null && r.recipeId == null) r.label else null,
                            quantity = r.quantity, unit = r.unit, servings = r.servings,
                            manualKcal = r.manualKcal, manualFatG = r.manualFatG,
                        ),
                    )
                }
            }.onFailure { error = it.message ?: "could not log" }
            fetch()
            busy = false
        }
    }

    /** Copy the previous day onto this one. The server appends rather than
     *  replaces, so anything already logged today survives. */
    fun repeatPrevious(day: String) {
        if (busy) return
        busy = true
        scope.launch {
            runCatching {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                withContext(Dispatchers.IO) {
                    api.mealsRepeatDay(
                        RepeatDayIn(source = LocalDate.parse(day).minusDays(1).toString(),
                                    target = day),
                    )
                }
            }.onFailure {
                // A 404 is informative rather than a failure: it means the
                // day before was not logged either.
                error = "nothing logged the day before, so there was nothing to copy"
            }
            fetch()
            busy = false
        }
    }

    LaunchedEffect(Unit) { fetch() }

    addingFor?.let { day ->
        LogEntryDialog(
            settings = settings,
            day = day,
            recipes = recipes,
            onDismiss = { addingFor = null },
            onSave = { entry ->
                scope.launch {
                    try {
                        val api = BackendClient.create(
                            settings.backendUrl, settings.bearerToken,
                        )
                        withContext(Dispatchers.IO) { api.mealsAddLogEntry(entry) }
                        addingFor = null
                        fetch()
                    } catch (e: Exception) {
                        error = e.message ?: "could not log"
                    }
                }
            },
        )
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
            stats?.let { item { StatsCard(it) } }
            if (loading && days.isEmpty()) item { MutedText("Loading…") }

            items(days, key = { it.day }) { d ->
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(NeonMV.Card)
                        .padding(12.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            dayLabel(d.day), color = NeonMV.Ink, fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.weight(1f),
                        )
                        // "—" not "0" — an unlogged day is not a day of
                        // eating nothing.
                        Text(
                            (d.totals["kcal"]?.let { "${it.roundToInt()}" } ?: "—") +
                                " kcal · " +
                                (d.totals["fat_g"]?.let { String.format("%.1f", it) } ?: "—") +
                                " g",
                            color = NeonMV.Muted, fontSize = 11.sp,
                        )
                        IconButton(onClick = { addingFor = d.day }) {
                            Icon(Icons.Filled.Add, "Log something", tint = NeonMV.Muted)
                        }
                    }

                    Row(
                        Modifier.padding(top = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            if (d.complete) "complete" else "partial",
                            color = if (d.complete) NeonMV.Lime else NeonMV.Muted,
                            fontSize = 10.sp,
                            modifier = Modifier
                                .clip(RoundedCornerShape(999.dp))
                                .background(NeonMV.CardHigh)
                                .clickable {
                                    scope.launch {
                                        runCatching {
                                            val api = BackendClient.create(
                                                settings.backendUrl, settings.bearerToken,
                                            )
                                            withContext(Dispatchers.IO) {
                                                api.mealsMarkLogDay(
                                                    d.day, LogDayPatch(complete = !d.complete),
                                                )
                                            }
                                        }
                                        fetch()
                                    }
                                }
                                .padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                        if (d.unresolvedCount > 0) {
                            Text(
                                "  ${d.unresolvedCount} not costed — totals understate",
                                color = NeonMV.Amber, fontSize = 10.sp,
                            )
                        }
                        Spacer(Modifier.weight(1f))
                        Text(
                            "Same as yesterday",
                            color = if (busy) NeonMV.Muted else NeonMV.Cyan,
                            fontSize = 10.sp,
                            modifier = Modifier
                                .clip(RoundedCornerShape(999.dp))
                                .clickable(enabled = !busy) { repeatPrevious(d.day) }
                                .padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                    }

                    // One tap logs the food and the portion together.
                    if (recents.isNotEmpty()) {
                        Row(
                            Modifier
                                .padding(top = 6.dp)
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            recents.forEach { r ->
                                Row(
                                    Modifier
                                        .clip(RoundedCornerShape(999.dp))
                                        .background(NeonMV.CardHigh)
                                        .clickable(enabled = !busy) { logRecent(d.day, r) }
                                        .padding(horizontal = 10.dp, vertical = 5.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        r.label, color = NeonMV.Ink, fontSize = 11.sp,
                                        maxLines = 1,
                                    )
                                    if (r.quantity != null) {
                                        Text(
                                            "  " + trimNum(r.quantity) +
                                                (r.unit?.let { " $it" } ?: ""),
                                            color = NeonMV.Muted, fontSize = 10.sp,
                                            maxLines = 1,
                                        )
                                    }
                                }
                            }
                        }
                    }

                    if (d.entryCount == 0) {
                        Text(
                            "Nothing logged.", color = NeonMV.Muted, fontSize = 11.sp,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }

                    d.meals.forEach { m ->
                        Row(
                            Modifier.fillMaxWidth().padding(top = 8.dp),
                            verticalAlignment = Alignment.Bottom,
                        ) {
                            Text(
                                m.slot.uppercase(), color = NeonMV.Muted, fontSize = 9.sp,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                (m.totals["fat_g"]?.let { String.format("%.1f g fat", it) }
                                    ?: "— fat"),
                                color = NeonMV.Muted, fontSize = 10.sp,
                            )
                        }
                        m.fatAssessment?.takeIf { it.verdict != "unknown" }?.let {
                            Box(Modifier.padding(top = 4.dp)) {
                                FatAssessmentCard(it, compact = true)
                            }
                        }
                        m.entries.forEach { e ->
                            Row(
                                Modifier.fillMaxWidth().padding(top = 3.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    e.label + (
                                        e.quantity?.let {
                                            "  ${trimNum(it)}${e.unit?.let { u -> " $u" } ?: ""}"
                                        } ?: e.servings?.let { "  ×${trimNum(it)}" } ?: ""
                                        ),
                                    color = NeonMV.Ink, fontSize = 12.sp,
                                    modifier = Modifier.weight(1f),
                                )
                                if (e.source == "manual") {
                                    Text("typed", color = NeonMV.Muted, fontSize = 9.sp)
                                }
                                e.unresolvedReason?.let {
                                    Text("  $it", color = NeonMV.Amber, fontSize = 9.sp)
                                } ?: Text(
                                    "  " + (e.nutrition["kcal"]?.let { "${it.roundToInt()}" }
                                        ?: "—") + " kcal",
                                    color = NeonMV.Muted, fontSize = 10.sp,
                                )
                                IconButton(onClick = {
                                    scope.launch {
                                        runCatching {
                                            val api = BackendClient.create(
                                                settings.backendUrl, settings.bearerToken,
                                            )
                                            withContext(Dispatchers.IO) {
                                                api.mealsDeleteLogEntry(e.id)
                                            }
                                        }
                                        fetch()
                                    }
                                }) {
                                    Icon(
                                        Icons.Filled.Delete, "Remove", tint = NeonMV.Muted,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatsCard(s: LogStatsOut) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card)
            .padding(12.dp),
    ) {
        if (s.reason != null) {
            // A refusal, not an error. Averaging partly-logged days would
            // read as eating less than you did.
            Text(s.reason!!, color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 16.sp)
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(
                    (s.avgKcal?.let { "${it.roundToInt()}" } ?: "—") + " kcal/day",
                    color = NeonMV.Ink, fontSize = 13.sp,
                )
                Text(
                    (s.avgFatG?.let { String.format("%.1f", it) } ?: "—") + " g fat/day",
                    color = NeonMV.Ink, fontSize = 13.sp,
                )
            }
            Text(
                "from ${s.completeDays} complete days",
                color = NeonMV.Muted, fontSize = 10.sp,
            )
        }
        if (s.mealsCounted > 0) {
            Text(
                "Per meal, last 30 days: median " +
                    (s.medianMealFatG?.let { String.format("%.1f", it) } ?: "—") +
                    " g, highest " +
                    (s.maxMealFatG?.let { String.format("%.1f", it) } ?: "—") +
                    " g (${s.mealsCounted} meals).",
                color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 16.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        if (s.partialDays > 0) {
            Text(
                "${s.partialDays} partly-logged day" +
                    (if (s.partialDays == 1) "" else "s") +
                    " excluded from the averages.",
                color = NeonMV.Muted, fontSize = 10.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
internal fun LogEntryDialog(
    settings: SettingsRepository,
    day: String,
    recipes: List<RecipeOut>,
    onDismiss: () -> Unit,
    onSave: (LogEntryIn) -> Unit,
) {
    var slot by remember { mutableStateOf("dinner") }
    var food by remember { mutableStateOf<FoodOut?>(null) }
    var recipeId by remember { mutableStateOf<Long?>(null) }
    var qty by remember { mutableStateOf("") }
    var unit by remember { mutableStateOf("") }
    var servings by remember { mutableStateOf("1") }
    var label by remember { mutableStateOf("") }
    var kcal by remember { mutableStateOf("") }
    var fat by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Log for $day") },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        LOG_SLOTS.forEach { s ->
                            Text(
                                s,
                                color = if (s == slot) NeonMV.OnAccent else NeonMV.Muted,
                                fontSize = 11.sp,
                                modifier = Modifier
                                    .clip(RoundedCornerShape(999.dp))
                                    .background(
                                        if (s == slot) NeonMV.Lime else NeonMV.CardHigh,
                                    )
                                    .clickable { slot = s }
                                    .padding(horizontal = 9.dp, vertical = 5.dp),
                            )
                        }
                    }
                }
                if (food == null && recipeId == null) {
                    item {
                        FoodPicker(
                            settings = settings,
                            placeholder = "Search a food…",
                            onPick = { food = it },
                        )
                    }
                    item { SectionLabel("…or one of your recipes") }
                    items(recipes, key = { it.id }) { r ->
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable { recipeId = r.id }
                                .padding(vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(checked = false, onCheckedChange = null)
                            Text("  " + r.name, color = NeonMV.Ink, fontSize = 12.sp)
                        }
                    }
                    item { SectionLabel("…or just name it") }
                    item {
                        OutlinedTextField(
                            value = label, onValueChange = { label = it },
                            label = { Text("e.g. lunch out") }, singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = kcal, onValueChange = { kcal = it },
                                label = { Text("kcal") }, singleLine = true,
                                modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = fat, onValueChange = { fat = it },
                                label = { Text("fat g") }, singleLine = true,
                                modifier = Modifier.weight(1f),
                            )
                        }
                    }
                } else if (food != null) {
                    item {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                food!!.name, color = NeonMV.Ink, fontSize = 13.sp,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = { food = null }) { Text("change") }
                        }
                    }
                    item {
                        QuantityPicker(
                            food = food,
                            quantity = qty,
                            unit = unit,
                            onQuantityChange = { qty = it },
                            onUnitChange = { unit = it },
                            label = "How much?",
                        )
                    }
                } else {
                    item {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                recipes.firstOrNull { it.id == recipeId }?.name ?: "Recipe",
                                color = NeonMV.Ink, fontSize = 13.sp,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = { recipeId = null }) { Text("change") }
                        }
                    }
                    item {
                        OutlinedTextField(
                            value = servings, onValueChange = { servings = it },
                            label = { Text("servings") }, singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = food != null || recipeId != null || label.isNotBlank(),
                onClick = {
                    onSave(
                        LogEntryIn(
                            day = day,
                            slot = slot,
                            foodId = food?.id,
                            recipeId = recipeId,
                            label = if (food == null && recipeId == null)
                                label.trim() else null,
                            quantity = qty.toDoubleOrNull(),
                            unit = unit.ifBlank { null },
                            servings = if (recipeId != null)
                                servings.toDoubleOrNull() ?: 1.0 else null,
                            // Blank stays null. A meal whose calories you
                            // do not know is not a zero-calorie meal.
                            manualKcal = kcal.toDoubleOrNull(),
                            manualFatG = fat.toDoubleOrNull(),
                        ),
                    )
                },
            ) { Text("Log") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private fun dayLabel(s: String): String = runCatching {
    val d = LocalDate.parse(s)
    if (d == LocalDate.now()) "Today" else d.format(LOG_DAY_FMT)
}.getOrDefault(s)
