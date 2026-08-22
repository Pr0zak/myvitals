package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.runtime.toMutableStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendApi
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FoodOut
import app.myvitals.sync.PantryItemIn
import app.myvitals.sync.PantryItemOut
import app.myvitals.sync.RecipeIn
import app.myvitals.sync.RecipeIngredientIn
import app.myvitals.sync.RecipeOut
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonMV
import com.squareup.moshi.Types
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/**
 * Recipes, pantry and food lookup — the phone half of MEAL-1, mirroring
 * the web's Recipes, Pantry and Foods views so the two surfaces never
 * disagree.
 *
 * Everything numeric here is rendered, not computed. Recipe totals,
 * per-serving figures, the unresolved-line count and `daysToExpiry` all
 * come from the backend; deriving any of them locally is what CLAUDE.md's
 * source-of-truth rule exists to prevent, and `daysToExpiry` in
 * particular would roll over at the wrong hour if computed from the
 * phone's clock.
 *
 * Follows the established SWR recipe: read the cache, render it, fetch in
 * parallel, swap in the fresh response. The spinner only appears on a
 * cold cache.
 */

private const val CACHE_RECIPES = "meals_recipes"
private const val CACHE_PANTRY = "meals_pantry"

private enum class MealsTab(val label: String) {
    RECIPES("Recipes"),
    PANTRY("Pantry"),
    FOODS("Foods"),
}

@Composable
fun MealsScreen(settings: SettingsRepository) {
    var tab by remember { mutableStateOf(MealsTab.RECIPES) }

    Column(Modifier.fillMaxSize().background(NeonMV.Bg)) {
        Text(
            "Meals",
            color = NeonMV.Ink,
            fontSize = 22.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 10.dp),
        )
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            MealsTab.entries.forEach { t ->
                TabChip(t.label, t == tab) { tab = t }
            }
        }
        Box(Modifier.fillMaxSize().padding(top = 10.dp)) {
            when (tab) {
                MealsTab.RECIPES -> RecipesTab(settings)
                MealsTab.PANTRY -> PantryTab(settings)
                MealsTab.FOODS -> FoodsTab(settings)
            }
        }
    }
}

@Composable
private fun TabChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label,
        color = if (selected) NeonMV.OnAccent else NeonMV.Muted,
        fontSize = 13.sp,
        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (selected) NeonMV.Lime else NeonMV.Card)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 7.dp),
    )
}

// ────────────────────────────────────────────────────────────── recipes

@Composable
private fun RecipesTab(settings: SettingsRepository) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val type = remember {
        Types.newParameterizedType(List::class.java, RecipeOut::class.java)
    }

    var recipes by remember { mutableStateOf<List<RecipeOut>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var expanded by remember { mutableStateOf<Long?>(null) }
    var editorFor by remember { mutableStateOf<RecipeOut?>(null) }
    var creating by remember { mutableStateOf(false) }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val rows = withContext(Dispatchers.IO) { api.mealsRecipes() }
            recipes = rows
            error = null
            JsonCache.write(context, CACHE_RECIPES, type, rows)
        } catch (e: Exception) {
            // Keep whatever is already on screen. An error card that
            // replaces good cached data is worse than a stale list.
            if (recipes.isEmpty()) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        JsonCache.read<List<RecipeOut>>(context, CACHE_RECIPES, type)?.let {
            recipes = it.value
            loading = false
        }
        fetch()
    }

    if (creating || editorFor != null) {
        RecipeEditor(
            settings = settings,
            existing = editorFor,
            onDismiss = { creating = false; editorFor = null },
            onSaved = {
                creating = false
                editorFor = null
                scope.launch { fetch() }
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
                Button(onClick = { creating = true }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Add, contentDescription = null)
                    Text("  New recipe")
                }
            }
            error?.let { item { ErrorText(it) } }
            if (loading && recipes.isEmpty()) {
                item { MutedText("Loading…") }
            } else if (recipes.isEmpty()) {
                item {
                    MutedText(
                        "No recipes yet. Add one and its nutrition is worked " +
                            "out from the ingredients.",
                    )
                }
            }
            items(recipes, key = { it.id }) { r ->
                RecipeCard(
                    r = r,
                    expanded = expanded == r.id,
                    onToggle = { expanded = if (expanded == r.id) null else r.id },
                    onEdit = { editorFor = r },
                    onDelete = {
                        scope.launch {
                            runCatching {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                withContext(Dispatchers.IO) { api.mealsDeleteRecipe(r.id) }
                            }
                            fetch()
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun RecipeCard(
    r: RecipeOut,
    expanded: Boolean,
    onToggle: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card)
            .padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f).clickable(onClick = onToggle)) {
                Text(r.name, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                val mins = (r.prepMin ?: 0) + (r.cookMin ?: 0)
                val kcal = r.perServing["kcal"]?.let { "${it.roundToInt()}" } ?: "—"
                Text(
                    buildString {
                        append("${r.servings} serving${if (r.servings == 1) "" else "s"}")
                        if (mins > 0) append(" · $mins min")
                        append(" · $kcal kcal/serving")
                    },
                    color = NeonMV.Muted,
                    fontSize = 11.sp,
                )
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Filled.Edit, "Edit", tint = NeonMV.Muted)
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Filled.Delete, "Delete", tint = NeonMV.Muted)
            }
            IconButton(onClick = onToggle) {
                Icon(
                    if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = if (expanded) "Collapse" else "Expand",
                    tint = NeonMV.Muted,
                )
            }
        }

        if (!expanded) return@Column

        if (r.unresolvedCount > 0) {
            Row(
                Modifier.padding(top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Filled.Warning, null, tint = NeonMV.Amber)
                Text(
                    "  ${r.unresolvedCount} ingredient" +
                        "${if (r.unresolvedCount == 1) "" else "s"} could not be " +
                        "costed, so these totals are an underestimate.",
                    color = NeonMV.Amber,
                    fontSize = 11.sp,
                )
            }
        }

        Column(Modifier.padding(top = 10.dp)) {
            NutriRow("Calories", r.perServing["kcal"], r.totals["kcal"], 0, "")
            NutriRow("Fat", r.perServing["fat_g"], r.totals["fat_g"], 1, " g", emphasise = true)
            NutriRow("Saturated", r.perServing["saturated_fat_g"], r.totals["saturated_fat_g"], 1, " g")
            NutriRow("Protein", r.perServing["protein_g"], r.totals["protein_g"], 1, " g")
            NutriRow("Carbs", r.perServing["carbs_g"], r.totals["carbs_g"], 1, " g")
            NutriRow("Fibre", r.perServing["fiber_g"], r.totals["fiber_g"], 1, " g")
            NutriRow("Sodium", r.perServing["sodium_mg"], r.totals["sodium_mg"], 0, " mg")
        }

        SectionLabel("Ingredients")
        r.ingredients.forEach { i ->
            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                val qty = i.quantity?.let { q ->
                    "${trimNum(q)}${i.unit?.let { " $it" } ?: ""} "
                } ?: ""
                Text(
                    "$qty${i.foodName ?: i.rawText ?: "—"}",
                    color = if (i.unresolvedReason != null) NeonMV.Muted else NeonMV.Ink,
                    fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                if (i.unresolvedReason != null) {
                    Text(i.unresolvedReason!!, color = NeonMV.Amber, fontSize = 10.sp)
                } else if (i.grams != null) {
                    Text("${i.grams!!.roundToInt()} g", color = NeonMV.Muted, fontSize = 11.sp)
                }
            }
        }

        r.method?.takeIf { it.isNotBlank() }?.let {
            SectionLabel("Method")
            Text(it, color = NeonMV.Ink, fontSize = 12.sp, lineHeight = 18.sp)
        }
    }
}

/** One nutrition row. A null renders "—", never 0 — the distinction is
 *  the whole reason these come back nullable from the server. */
@Composable
private fun NutriRow(
    label: String,
    perServing: Double?,
    total: Double?,
    digits: Int,
    suffix: String,
    emphasise: Boolean = false,
) {
    fun fmt(v: Double?) =
        if (v == null) "—" else String.format("%.${digits}f%s", v, suffix)
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(
            label,
            color = if (emphasise) NeonMV.Ink else NeonMV.Muted,
            fontSize = 12.sp,
            fontWeight = if (emphasise) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.weight(1f),
        )
        Text(
            fmt(perServing),
            color = if (emphasise) NeonMV.Ink else NeonMV.Muted,
            fontSize = 12.sp,
            fontWeight = if (emphasise) FontWeight.SemiBold else FontWeight.Normal,
        )
        Text(
            "   ${fmt(total)}",
            color = NeonMV.Muted,
            fontSize = 12.sp,
        )
    }
}

// ─────────────────────────────────────────────────────── recipe editor

@Composable
private fun RecipeEditor(
    settings: SettingsRepository,
    existing: RecipeOut?,
    onDismiss: () -> Unit,
    onSaved: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf(existing?.name ?: "") }
    var servings by remember { mutableStateOf((existing?.servings ?: 1).toString()) }
    var prep by remember { mutableStateOf(existing?.prepMin?.toString() ?: "") }
    var cook by remember { mutableStateOf(existing?.cookMin?.toString() ?: "") }
    var method by remember { mutableStateOf(existing?.method ?: "") }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    val lines: SnapshotStateList<DraftLine> = remember {
        (existing?.ingredients?.map {
            DraftLine(it.foodId, it.foodName, it.rawText, it.quantity?.let(::trimNum) ?: "", it.unit ?: "")
        } ?: emptyList()).toMutableStateList()
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (existing == null) "New recipe" else "Edit recipe") },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    OutlinedTextField(
                        value = name, onValueChange = { name = it },
                        label = { Text("Name") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = servings, onValueChange = { servings = it },
                            label = { Text("Servings") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = prep, onValueChange = { prep = it },
                            label = { Text("Prep") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = cook, onValueChange = { cook = it },
                            label = { Text("Cook") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                item { SectionLabel("Ingredients") }
                items(lines.size) { idx ->
                    val line = lines[idx]
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        OutlinedTextField(
                            value = line.quantity,
                            onValueChange = { lines[idx] = line.copy(quantity = it) },
                            label = { Text("qty") }, singleLine = true,
                            modifier = Modifier.weight(0.9f),
                        )
                        OutlinedTextField(
                            value = line.unit,
                            onValueChange = { lines[idx] = line.copy(unit = it) },
                            label = { Text("unit") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            line.foodName ?: line.rawText ?: "—",
                            color = NeonMV.Ink, fontSize = 12.sp,
                            modifier = Modifier.weight(1.6f),
                        )
                        IconButton(onClick = { lines.removeAt(idx) }) {
                            Icon(Icons.Filled.Delete, "Remove", tint = NeonMV.Muted)
                        }
                    }
                }
                item {
                    FoodPicker(
                        settings = settings,
                        ingredientsOnly = true,
                        placeholder = "Add an ingredient…",
                        onPick = { f -> lines.add(DraftLine(f.id, f.name, null, "", "")) },
                    )
                }
                item {
                    OutlinedTextField(
                        value = method, onValueChange = { method = it },
                        label = { Text("Method") },
                        minLines = 3,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                error?.let { item { ErrorText(it) } }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !saving && name.isNotBlank(),
                onClick = {
                    scope.launch {
                        saving = true
                        error = null
                        try {
                            val api = BackendClient.create(
                                settings.backendUrl, settings.bearerToken,
                            )
                            val body = RecipeIn(
                                name = name.trim(),
                                servings = servings.toIntOrNull() ?: 1,
                                prepMin = prep.toIntOrNull(),
                                cookMin = cook.toIntOrNull(),
                                method = method.ifBlank { null },
                                ingredients = lines.map {
                                    RecipeIngredientIn(
                                        foodId = it.foodId,
                                        rawText = it.rawText,
                                        quantity = it.quantity.toDoubleOrNull(),
                                        unit = it.unit.ifBlank { null },
                                    )
                                },
                            )
                            withContext(Dispatchers.IO) {
                                if (existing == null) api.mealsCreateRecipe(body)
                                else api.mealsUpdateRecipe(existing.id, body)
                            }
                            onSaved()
                        } catch (e: Exception) {
                            error = e.message ?: "save failed"
                        } finally {
                            saving = false
                        }
                    }
                },
            ) { Text(if (saving) "Saving…" else "Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private data class DraftLine(
    val foodId: Long?,
    val foodName: String?,
    val rawText: String?,
    val quantity: String,
    val unit: String,
)

// ─────────────────────────────────────────────────────────────── pantry

@Composable
private fun PantryTab(settings: SettingsRepository) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val type = remember {
        Types.newParameterizedType(List::class.java, PantryItemOut::class.java)
    }

    var items by remember { mutableStateOf<List<PantryItemOut>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var adding by remember { mutableStateOf(false) }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val rows = withContext(Dispatchers.IO) { api.mealsPantry() }
            items = rows
            error = null
            JsonCache.write(context, CACHE_PANTRY, type, rows)
        } catch (e: Exception) {
            if (items.isEmpty()) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        JsonCache.read<List<PantryItemOut>>(context, CACHE_PANTRY, type)?.let {
            items = it.value
            loading = false
        }
        fetch()
    }

    if (adding) {
        PantryAdder(
            settings = settings,
            onDismiss = { adding = false },
            onSaved = { adding = false; scope.launch { fetch() } },
        )
    }

    PullableMetricBox(
        refreshing = refreshing,
        onRefresh = { refreshing = true; try { fetch() } finally { refreshing = false } },
    ) {
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            item {
                Button(onClick = { adding = true }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.Add, contentDescription = null)
                    Text("  Add item")
                }
            }
            error?.let { item { ErrorText(it) } }
            if (loading && items.isEmpty()) {
                item { MutedText("Loading…") }
            } else if (items.isEmpty()) {
                item {
                    MutedText(
                        "Nothing in the pantry yet. Add what you have and " +
                            "recipes can be matched against it.",
                    )
                }
            }
            items(items, key = { it.id }) { p ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .background(NeonMV.Card)
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            p.foodName ?: p.label ?: "Untitled",
                            color = NeonMV.Ink, fontSize = 13.sp,
                        )
                        val amount = p.quantity?.let {
                            "${trimNum(it)}${p.unit?.let { u -> " $u" } ?: ""}"
                        } ?: p.unit
                        amount?.let {
                            Text(it, color = NeonMV.Muted, fontSize = 11.sp)
                        }
                    }
                    expiryLabel(p.daysToExpiry)?.let { (text, colour) ->
                        Text(text, color = colour, fontSize = 11.sp)
                    }
                    IconButton(onClick = {
                        scope.launch {
                            runCatching {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                withContext(Dispatchers.IO) { api.mealsDeletePantry(p.id) }
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

/** Expiry phrased the way a person would say it. `null` days means the
 *  item has no date — which is NOT the same as expiring today, so it
 *  renders nothing at all. */
private fun expiryLabel(days: Int?): Pair<String, androidx.compose.ui.graphics.Color>? {
    if (days == null) return null
    return when {
        days < 0 -> "expired ${-days}d ago" to NeonMV.Bad
        days == 0 -> "expires today" to NeonMV.Amber
        days == 1 -> "expires tomorrow" to NeonMV.Amber
        days <= 3 -> "${days}d left" to NeonMV.Amber
        else -> "${days}d left" to NeonMV.Muted
    }
}

@Composable
private fun PantryAdder(
    settings: SettingsRepository,
    onDismiss: () -> Unit,
    onSaved: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var picked by remember { mutableStateOf<FoodOut?>(null) }
    var label by remember { mutableStateOf("") }
    var qty by remember { mutableStateOf("") }
    var unit by remember { mutableStateOf("") }
    var expires by remember { mutableStateOf("") }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add to pantry") },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    if (picked == null) {
                        FoodPicker(
                            settings = settings,
                            placeholder = "Search the food catalog…",
                            onPick = { picked = it; label = "" },
                        )
                    } else {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                picked!!.name, color = NeonMV.Ink, fontSize = 13.sp,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = { picked = null }) { Text("change") }
                        }
                    }
                }
                if (picked == null) {
                    item {
                        OutlinedTextField(
                            value = label, onValueChange = { label = it },
                            label = { Text("…or just name it") }, singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = qty, onValueChange = { qty = it },
                            label = { Text("Qty") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = unit, onValueChange = { unit = it },
                            label = { Text("Unit") }, singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                item {
                    OutlinedTextField(
                        value = expires, onValueChange = { expires = it },
                        label = { Text("Use by (YYYY-MM-DD)") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                error?.let { item { ErrorText(it) } }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !saving && (picked != null || label.isNotBlank()),
                onClick = {
                    scope.launch {
                        saving = true
                        error = null
                        try {
                            val api = BackendClient.create(
                                settings.backendUrl, settings.bearerToken,
                            )
                            withContext(Dispatchers.IO) {
                                api.mealsAddPantry(
                                    PantryItemIn(
                                        foodId = picked?.id,
                                        label = if (picked == null) label.trim() else null,
                                        quantity = qty.toDoubleOrNull(),
                                        unit = unit.ifBlank { null },
                                        expiresOn = expires.ifBlank { null },
                                    ),
                                )
                            }
                            onSaved()
                        } catch (e: Exception) {
                            error = e.message ?: "could not add"
                        } finally {
                            saving = false
                        }
                    }
                },
            ) { Text(if (saving) "Adding…" else "Add") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

// ──────────────────────────────────────────────────────────────── foods

@Composable
private fun FoodsTab(settings: SettingsRepository) {
    var selected by remember { mutableStateOf<FoodOut?>(null) }
    var ingredientsOnly by remember { mutableStateOf(false) }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (ingredientsOnly) "Ingredients only" else "All foods",
                    color = NeonMV.Muted, fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = { ingredientsOnly = !ingredientsOnly }) {
                    Text(if (ingredientsOnly) "show all" else "ingredients only")
                }
            }
        }
        item {
            FoodPicker(
                settings = settings,
                ingredientsOnly = ingredientsOnly,
                placeholder = "Search 11,000+ foods…",
                onPick = { selected = it },
            )
        }
        selected?.let { f ->
            item {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(NeonMV.Card)
                        .padding(12.dp),
                ) {
                    Text(f.name, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    f.category?.let {
                        Text(it, color = NeonMV.Muted, fontSize = 11.sp)
                    }
                    SectionLabel("Per 100 g")
                    FoodStat("Calories", f.kcal, 0, "")
                    FoodStat("Fat", f.fatG, 1, " g", emphasise = true)
                    FoodStat("Saturated fat", f.saturatedFatG, 1, " g")
                    FoodStat("Protein", f.proteinG, 1, " g")
                    FoodStat("Carbs", f.carbsG, 1, " g")
                    FoodStat("Fibre", f.fiberG, 1, " g")
                    FoodStat("Sugar", f.sugarG, 1, " g")
                    FoodStat("Sodium", f.sodiumMg, 0, " mg")

                    f.unitGrams?.takeIf { it.isNotEmpty() }?.let { units ->
                        SectionLabel("Measures")
                        units.forEach { (u, g) ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                                Text("1 $u", color = NeonMV.Muted, fontSize = 12.sp,
                                    modifier = Modifier.weight(1f))
                                Text("${trimNum(g)} g", color = NeonMV.Ink, fontSize = 12.sp)
                            }
                        }
                    }
                }
            }
        }
        if (selected == null) {
            item { MutedText("Search for a food to see its nutrition.") }
        }
    }
}

@Composable
private fun FoodStat(
    label: String, v: Double?, digits: Int, suffix: String, emphasise: Boolean = false,
) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(
            label,
            color = if (emphasise) NeonMV.Ink else NeonMV.Muted,
            fontSize = 12.sp,
            fontWeight = if (emphasise) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.weight(1f),
        )
        Text(
            if (v == null) "—" else String.format("%.${digits}f%s", v, suffix),
            color = if (emphasise) NeonMV.Ink else NeonMV.Muted,
            fontSize = 12.sp,
            fontWeight = if (emphasise) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}

// ─────────────────────────────────────────────────────────────── shared

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        color = NeonMV.Muted,
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 10.dp, bottom = 4.dp),
    )
}

@Composable
private fun MutedText(text: String) {
    Text(text, color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 18.sp,
        modifier = Modifier.padding(vertical = 12.dp))
}

@Composable
private fun ErrorText(text: String) {
    Text(text, color = NeonMV.Bad, fontSize = 12.sp,
        modifier = Modifier.padding(vertical = 8.dp))
}

/** "2.0" reads wrong on an ingredient line; "2" is what a recipe says. */
private fun trimNum(v: Double): String =
    if (v == v.toLong().toDouble()) v.toLong().toString() else v.toString()
