package app.myvitals.ui.meals

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.HelpOutline
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Refresh
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.PlanDayOut
import app.myvitals.sync.PlanEntryIn
import app.myvitals.sync.RecipeOut
import app.myvitals.sync.ShoppingListIn
import app.myvitals.sync.ShoppingListOut
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

/**
 * The weekly plan and the shopping list — the phone mirror of the web's
 * Plan and Shopping views.
 *
 * Every quantity here is rendered, never computed. The plan's day totals
 * and the shopping list's pantry subtraction both happen server-side, so
 * the two clients cannot disagree about what to buy.
 *
 * There is no household or portion model — single person — so `servings`
 * is a plain multiplier meaning "how many containers of this to make".
 */

private val SLOTS = listOf("breakfast", "lunch", "dinner", "snack", "prep")
private val DAY_FMT = DateTimeFormatter.ofPattern("EEE d")

// ───────────────────────────────────────────────────────────── the plan

@Composable
fun PlanTab(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    var weekStart by remember { mutableStateOf(mondayOfThisWeek()) }
    var days by remember { mutableStateOf<List<PlanDayOut>>(emptyList()) }
    var recipes by remember { mutableStateOf<List<RecipeOut>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var addingFor by remember { mutableStateOf<String?>(null) }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val (d, r) = withContext(Dispatchers.IO) {
                api.mealsPlan(weekStart, 7) to api.mealsRecipes()
            }
            days = d
            recipes = r
            error = null
        } catch (e: Exception) {
            if (days.isEmpty()) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(weekStart) { fetch() }

    addingFor?.let { day ->
        PlanEntryDialog(
            day = day,
            recipes = recipes,
            onDismiss = { addingFor = null },
            onSave = { entry ->
                scope.launch {
                    try {
                        val api = BackendClient.create(
                            settings.backendUrl, settings.bearerToken,
                        )
                        withContext(Dispatchers.IO) { api.mealsAddPlanEntry(entry) }
                        addingFor = null
                        fetch()
                    } catch (e: Exception) {
                        error = e.message ?: "could not add"
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
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = { weekStart = shiftWeek(weekStart, -1) }) {
                        Icon(Icons.Filled.ChevronLeft, "Previous week", tint = NeonMV.Muted)
                    }
                    Text(
                        weekLabel(days),
                        color = NeonMV.Ink, fontSize = 13.sp,
                        modifier = Modifier.weight(1f)
                            .clickable { weekStart = mondayOfThisWeek() },
                    )
                    IconButton(onClick = { weekStart = shiftWeek(weekStart, 1) }) {
                        Icon(Icons.Filled.ChevronRight, "Next week", tint = NeonMV.Muted)
                    }
                }
            }
            error?.let { item { ErrorText(it) } }
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
                            runCatching { LocalDate.parse(d.day).format(DAY_FMT) }
                                .getOrDefault(d.day),
                            color = NeonMV.Ink, fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            modifier = Modifier.weight(1f),
                        )
                        // "—" not "0": a day with nothing costable planned
                        // has an unknown total, not an empty one.
                        Text(
                            (d.kcal?.let { "${it.roundToInt()}" } ?: "—") + " kcal · " +
                                (d.fatG?.let { String.format("%.1f", it) } ?: "—") + " g fat",
                            color = NeonMV.Muted, fontSize = 11.sp,
                        )
                        IconButton(onClick = { addingFor = d.day }) {
                            Icon(Icons.Filled.Add, "Add", tint = NeonMV.Muted)
                        }
                    }

                    if (d.entries.isEmpty()) {
                        Text("Nothing planned.", color = NeonMV.Muted, fontSize = 11.sp)
                    }
                    d.entries.forEach { e ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 3.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                e.slot.uppercase(), color = NeonMV.Muted, fontSize = 9.sp,
                                modifier = Modifier.padding(end = 6.dp),
                            )
                            Text(
                                (e.recipeName ?: e.note ?: "—") +
                                    if (e.servings > 1) "  ×${e.servings}" else "",
                                color = NeonMV.Ink, fontSize = 12.sp,
                                modifier = Modifier.weight(1f),
                            )
                            e.kcalPerServing?.let {
                                Text(
                                    "${(it * e.servings).roundToInt()} kcal",
                                    color = NeonMV.Muted, fontSize = 11.sp,
                                )
                            }
                            verdictDot(e.fatVerdict)?.let { c ->
                                Box(
                                    Modifier.padding(start = 6.dp).size(7.dp)
                                        .clip(CircleShape).background(c),
                                )
                            }
                            IconButton(onClick = {
                                scope.launch {
                                    runCatching {
                                        val api = BackendClient.create(
                                            settings.backendUrl, settings.bearerToken,
                                        )
                                        withContext(Dispatchers.IO) {
                                            api.mealsDeletePlanEntry(e.id)
                                        }
                                    }
                                    fetch()
                                }
                            }) {
                                Icon(Icons.Filled.Delete, "Remove", tint = NeonMV.Muted)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Null for "unknown" — an absent judgment gets no dot at all rather
 *  than a neutral one that could be mistaken for a verdict. */
private fun verdictDot(verdict: String): Color? = when (verdict) {
    "ok" -> NeonMV.Lime
    "approaching" -> NeonMV.Amber
    "high" -> NeonMV.Amber
    "very_high" -> NeonMV.Bad
    else -> null
}

@Composable
private fun PlanEntryDialog(
    day: String,
    recipes: List<RecipeOut>,
    onDismiss: () -> Unit,
    onSave: (PlanEntryIn) -> Unit,
) {
    var slot by remember { mutableStateOf("dinner") }
    var recipeId by remember { mutableStateOf<Long?>(null) }
    var note by remember { mutableStateOf("") }
    var servings by remember { mutableStateOf("1") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Plan for $day") },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        SLOTS.forEach { s ->
                            TabChipSmall(s, s == slot) { slot = s }
                        }
                    }
                }
                item { SectionLabel("Recipe") }
                items(recipes, key = { it.id }) { r ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { recipeId = if (recipeId == r.id) null else r.id }
                            .padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(checked = recipeId == r.id, onCheckedChange = null)
                        Text(
                            "  " + r.name, color = NeonMV.Ink, fontSize = 13.sp,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                item {
                    if (recipeId == null) {
                        OutlinedTextField(
                            value = note, onValueChange = { note = it },
                            label = { Text("…or a note (eating out, leftovers)") },
                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                        )
                    } else {
                        OutlinedTextField(
                            value = servings, onValueChange = { servings = it },
                            label = { Text("Containers to make") },
                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = recipeId != null || note.isNotBlank(),
                onClick = {
                    onSave(
                        PlanEntryIn(
                            day = day, slot = slot, recipeId = recipeId,
                            note = if (recipeId == null) note.trim() else null,
                            servings = servings.toIntOrNull() ?: 1,
                        ),
                    )
                },
            ) { Text("Add") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun TabChipSmall(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label,
        color = if (selected) NeonMV.OnAccent else NeonMV.Muted,
        fontSize = 11.sp,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (selected) NeonMV.Lime else NeonMV.CardHigh)
            .clickable(onClick = onClick)
            .padding(horizontal = 9.dp, vertical = 5.dp),
    )
}

// ──────────────────────────────────────────────────────── shopping list

@Composable
fun ShoppingTab(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var lists by remember { mutableStateOf<List<ShoppingListOut>>(emptyList()) }
    var active by remember { mutableStateOf<ShoppingListOut?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var generating by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val rows = withContext(Dispatchers.IO) { api.mealsShoppingLists() }
            lists = rows
            active = rows.firstOrNull()
            error = null
        } catch (e: Exception) {
            if (lists.isEmpty()) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { fetch() }

    PullableMetricBox(
        refreshing = refreshing,
        onRefresh = { refreshing = true; try { fetch() } finally { refreshing = false } },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            item {
                Button(
                    enabled = !generating,
                    onClick = {
                        scope.launch {
                            generating = true
                            try {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                val created = withContext(Dispatchers.IO) {
                                    api.mealsGenerateShoppingList(ShoppingListIn(days = 7))
                                }
                                fetch()
                                active = created
                            } catch (e: Exception) {
                                error = e.message ?: "could not generate"
                            } finally {
                                generating = false
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Filled.Refresh, contentDescription = null)
                    Text(if (generating) "  Building…" else "  Generate from plan")
                }
            }
            error?.let { item { ErrorText(it) } }
            if (loading && lists.isEmpty()) item { MutedText("Loading…") }

            val current = active
            if (current == null && !loading) {
                item {
                    MutedText(
                        "No lists yet. Plan some meals, then generate one — it " +
                            "subtracts what the pantry already holds.",
                    )
                }
            }

            current?.let { l ->
                item {
                    Column(Modifier.padding(top = 4.dp, bottom = 4.dp)) {
                        Text(
                            l.name ?: "Shopping list",
                            color = NeonMV.Ink, fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                        )
                        Text(
                            buildString {
                                append("${l.plannedMeals} planned meal")
                                if (l.plannedMeals != 1) append("s")
                                if (l.coveredByPantry > 0) {
                                    append(" · ${l.coveredByPantry} already covered")
                                }
                            },
                            color = NeonMV.Muted, fontSize = 11.sp,
                        )
                    }
                }
                if (l.items.isEmpty()) {
                    item {
                        MutedText(
                            if (l.plannedMeals == 0)
                                "Nothing was planned for this window, so there is nothing to buy."
                            else
                                "Everything the plan needs is already in the pantry.",
                        )
                    }
                }
                items(l.items, key = { it.id }) { item ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .background(NeonMV.Card)
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(
                            checked = item.checked,
                            onCheckedChange = { on ->
                                scope.launch {
                                    runCatching {
                                        val api = BackendClient.create(
                                            settings.backendUrl, settings.bearerToken,
                                        )
                                        withContext(Dispatchers.IO) {
                                            api.mealsCheckShoppingItem(l.id, item.id, on)
                                        }
                                    }
                                    fetch()
                                }
                            },
                        )
                        Column(Modifier.weight(1f)) {
                            Text(
                                item.label, color = NeonMV.Ink, fontSize = 12.sp,
                                textDecoration =
                                    if (item.checked) TextDecoration.LineThrough else null,
                            )
                            val amount = listOfNotNull(item.amount, item.amountText)
                                .joinToString(" + ")
                            if (amount.isNotBlank()) {
                                Text(amount, color = NeonMV.Muted, fontSize = 10.sp)
                            }
                        }
                        if (item.pantryUncertain) {
                            Icon(
                                Icons.Filled.HelpOutline,
                                contentDescription =
                                    "Pantry has some but the amount is unknown",
                                tint = NeonMV.Amber,
                                modifier = Modifier.size(16.dp),
                            )
                        }
                        item.walmartUrl?.let { url ->
                            IconButton(onClick = {
                                // Opened in the user's OWN browser. A cart
                                // belongs to a logged-in browser session, so
                                // nothing server-side could act on it anyway.
                                runCatching {
                                    context.startActivity(
                                        Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                                    )
                                }
                            }) {
                                Icon(
                                    Icons.Filled.OpenInNew, "Search Walmart",
                                    tint = NeonMV.Muted,
                                    modifier = Modifier.size(15.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ───────────────────────────────────────────────────────────── helpers

/** Monday of the current week, on the DEVICE's local date. The server
 *  resolves its own default in the configured timezone; passing an
 *  explicit day keeps the two in step when the user scrolls weeks. */
private fun mondayOfThisWeek(): String {
    val today = LocalDate.now()
    return today.minusDays((today.dayOfWeek.value - 1).toLong()).toString()
}

private fun shiftWeek(start: String, weeks: Int): String =
    runCatching { LocalDate.parse(start).plusWeeks(weeks.toLong()).toString() }
        .getOrDefault(start)

private fun weekLabel(days: List<PlanDayOut>): String {
    if (days.isEmpty()) return "…"
    val fmt = DateTimeFormatter.ofPattern("MMM d")
    return runCatching {
        val a = LocalDate.parse(days.first().day).format(fmt)
        val b = LocalDate.parse(days.last().day).format(fmt)
        "$a – $b"
    }.getOrDefault("…")
}
