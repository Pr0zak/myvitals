package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.rememberScrollState
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
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
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
import app.myvitals.sync.CommonItemOut
import app.myvitals.sync.QuickAddIn
import app.myvitals.sync.DietProfile
import app.myvitals.sync.DietProfileIn
import app.myvitals.sync.FatAssessment
import app.myvitals.sync.FoodOut
import app.myvitals.sync.ImageIn
import app.myvitals.sync.LabelIn
import app.myvitals.sync.LabelScan
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
    PLAN("Plan"),
    CAN_MAKE("Can make"),
    LOG("Log"),
    IDEAS("Ideas"),
    RECIPES("Recipes"),
    SHOPPING("Shopping"),
    PANTRY("Pantry"),
    FOODS("Foods"),
    NUTRITION("Nutrition"),
}

@Composable
fun MealsScreen(settings: SettingsRepository) {
    var tab by remember { mutableStateOf(MealsTab.PLAN) }

    Column(Modifier.fillMaxSize().background(NeonMV.Bg)) {
        Text(
            "Meals",
            color = NeonMV.Ink,
            fontSize = 22.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 10.dp),
        )
        // Six chips do not fit across a phone. Scrolling the row keeps
        // every tab reachable rather than silently clipping the last two.
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            MealsTab.entries.forEach { t ->
                TabChip(t.label, t == tab) { tab = t }
            }
        }
        Box(Modifier.fillMaxSize().padding(top = 10.dp)) {
            when (tab) {
                MealsTab.PLAN -> PlanTab(settings)
                MealsTab.CAN_MAKE -> CanMakeTab(settings)
                MealsTab.LOG -> LogTab(settings)
                MealsTab.IDEAS -> SuggestTab(settings)
                MealsTab.SHOPPING -> ShoppingTab(settings)
                MealsTab.RECIPES -> RecipesTab(settings)
                MealsTab.PANTRY -> PantryTab(settings)
                MealsTab.FOODS -> FoodsTab(settings)
                MealsTab.NUTRITION -> NutritionTab(settings)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun StapleChip(c: CommonItemOut, onClick: () -> Unit) {
    Text(
        c.label + if (c.inPantry) "  \u2713" else "",
        color = if (c.inPantry) NeonMV.Lime else NeonMV.Ink,
        fontSize = 12.sp,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(NeonMV.CardHigh)
            .then(
                if (c.inPantry) Modifier
                else Modifier.clickable(onClick = onClick),
            )
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
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
            r.fatAssessment?.takeIf { it.verdict != "unknown" }?.let { fa ->
                Text(
                    fa.fatG?.let { String.format("%.1fg fat", it) } ?: "— fat",
                    color = when (fa.verdict) {
                        "very_high" -> NeonMV.Bad
                        "high", "approaching" -> NeonMV.Amber
                        else -> NeonMV.Lime
                    },
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
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

        r.fatAssessment?.let {
            Box(Modifier.padding(top = 10.dp)) { FatAssessmentCard(it) }
        }

        r.energySplit?.takeIf { it.kcalFromMacros != null }?.let { es ->
            Row(
                Modifier.padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("Energy from", color = NeonMV.Muted, fontSize = 11.sp)
                Text(
                    "protein " + (es.percent.protein?.let { "$it%" } ?: "—"),
                    color = NeonMV.Cyan, fontSize = 11.sp,
                )
                Text(
                    "carbs " + (es.percent.carbs?.let { "$it%" } ?: "—"),
                    color = NeonMV.Periwinkle, fontSize = 11.sp,
                )
                Text(
                    "fat " + (es.percent.fat?.let { "$it%" } ?: "—"),
                    color = NeonMV.Amber, fontSize = 11.sp,
                )
            }
            if (es.incomplete) {
                Text(
                    "Partial — a macro is unknown for at least one ingredient.",
                    color = NeonMV.Amber, fontSize = 10.sp,
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

        r.fatSoluble?.takeIf { !it.noData }?.let { fs ->
            SectionLabel("Fat-soluble vitamins (per serving)")
            fs.present.forEach { (k, v) ->
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(
                        VIT_LABELS[k] ?: k, color = NeonMV.Muted, fontSize = 12.sp,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        String.format("%.1f %s", v, VIT_UNITS[k] ?: ""),
                        color = NeonMV.Ink, fontSize = 12.sp,
                    )
                }
            }
            if (fs.missing.isNotEmpty()) {
                Text(
                    "${fs.missing.size} not known for these ingredients — " +
                        "absent, not zero.",
                    color = NeonMV.Muted, fontSize = 10.sp,
                )
            }
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
                    Column(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                line.foodName ?: line.rawText ?: "—",
                                color = NeonMV.Ink, fontSize = 12.sp,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = { lines.removeAt(idx) }) {
                                Icon(Icons.Filled.Delete, "Remove", tint = NeonMV.Muted)
                            }
                        }
                        if (line.foodId != null) {
                            QuantityPicker(
                                food = null,
                                quantity = line.quantity,
                                unit = line.unit,
                                onQuantityChange = {
                                    lines[idx] = line.copy(quantity = it)
                                },
                                onUnitChange = { lines[idx] = line.copy(unit = it) },
                                label = "How much?",
                                ownUnits = line.unitGrams,
                            )
                        } else {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                OutlinedTextField(
                                    value = line.quantity,
                                    onValueChange = {
                                        lines[idx] = line.copy(quantity = it)
                                    },
                                    label = { Text("qty") }, singleLine = true,
                                    modifier = Modifier.weight(1f),
                                )
                                OutlinedTextField(
                                    value = line.unit,
                                    onValueChange = { lines[idx] = line.copy(unit = it) },
                                    label = { Text("unit") }, singleLine = true,
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
                item {
                    FoodPicker(
                        settings = settings,
                        ingredientsOnly = true,
                        placeholder = "Add an ingredient…",
                        onPick = { f ->
                            lines.add(
                                DraftLine(f.id, f.name, null, "", "", f.unitGrams),
                            )
                        },
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
    /** The food's own measures, so the unit picker can offer them. Null
     *  for a hand-typed line, which falls back to free text. */
    val unitGrams: Map<String, Double>? = null,
)

// ─────────────────────────────────────────────────────────────── pantry

@OptIn(ExperimentalLayoutApi::class)
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
    // One-tap staples. Typing plain names only appears to work — nine of
    // twenty everyday staples match a concept and the rest fail silently.
    var common by remember { mutableStateOf<List<CommonItemOut>>(emptyList()) }
    var showCommon by remember { mutableStateOf(true) }

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
            runCatching {
                common = withContext(Dispatchers.IO) { api.mealsCommonIngredients() }
            }
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
                Text(
                    "What's actually in the house. This is what the shopping " +
                        "list subtracts from, and what the Can-make tab matches " +
                        "your recipes against.",
                    color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 16.sp,
                )
            }

            item { PhotoPantry(settings = settings, onAdded = { scope.launch { fetch() } }) }
            item {
                PackageScan(
                    settings = settings,
                    // Scanning a pack in the PANTRY means "I just bought
                    // this": define it AND stock it. In the Foods tab the
                    // same photos mean only "define this product".
                    stock = true,
                    onSaved = { scope.launch { fetch() } },
                )
            }

            if (common.isNotEmpty()) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "Common staples", color = NeonMV.Ink, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            if (showCommon) "hide" else "show",
                            color = NeonMV.Cyan, fontSize = 11.sp,
                            modifier = Modifier.clickable { showCommon = !showCommon },
                        )
                    }
                }
                if (showCommon) {
                    item {
                        Text(
                            "Tap to add. No amounts needed — the pantry only has " +
                                "to know whether you have something.",
                            color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
                        )
                    }
                    common.groupBy { it.category }.forEach { (cat, entries) ->
                        item {
                            Column(Modifier.padding(top = 6.dp)) {
                                Text(
                                    cat.uppercase(), color = NeonMV.Muted,
                                    fontSize = 9.sp,
                                    modifier = Modifier.padding(bottom = 3.dp),
                                )
                                FlowRow(
                                    horizontalArrangement = Arrangement.spacedBy(5.dp),
                                    verticalArrangement = Arrangement.spacedBy(5.dp),
                                ) {
                                    entries.forEach { c ->
                                        StapleChip(c) {
                                            scope.launch {
                                                c.foodId?.let { fid ->
                                                    runCatching {
                                                        val api = BackendClient.create(
                                                            settings.backendUrl,
                                                            settings.bearerToken,
                                                        )
                                                        withContext(Dispatchers.IO) {
                                                            api.mealsQuickAddPantry(
                                                                QuickAddIn(listOf(fid)),
                                                            )
                                                        }
                                                    }
                                                    fetch()
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
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
    // A pantry is a list of things you cook with, so the picker defaults
    // to whole ingredients. Packaged and prepared food is still stockable
    // — hence the toggle — but leading with it buries plain chicken
    // breast under deli slices and restaurant sandwiches.
    var ingredientsOnly by remember { mutableStateOf(true) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add to pantry") },
        text = {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    if (picked == null) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "Ingredients only",
                                color = NeonMV.Muted, fontSize = 11.sp,
                                modifier = Modifier.weight(1f),
                            )
                            Switch(
                                checked = ingredientsOnly,
                                onCheckedChange = { ingredientsOnly = it },
                            )
                        }
                        FoodPicker(
                            settings = settings,
                            ingredientsOnly = ingredientsOnly,
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
                    // Optional on purpose: "we have olive oil" is a useful
                    // fact without a number, and demanding one is the
                    // friction that stops a pantry being kept up to date.
                    QuantityPicker(
                        food = picked,
                        quantity = qty,
                        unit = unit,
                        onQuantityChange = { qty = it },
                        onUnitChange = { unit = it },
                        label = "How much? (optional)",
                    )
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
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var selected by remember { mutableStateOf<FoodOut?>(null) }
    var ingredientsOnly by remember { mutableStateOf(false) }
    // MEAL-8: scan the panel rather than typing thirteen numbers off it.
    var scanBusy by remember { mutableStateOf(false) }
    var scan by remember { mutableStateOf<LabelScan?>(null) }
    var scanError by remember { mutableStateOf<String?>(null) }

    // Multiple photos: the panel has the numbers and no product name, the
    // front has the name and no numbers, and a third of the ingredients
    // list is transcribed verbatim.
    val labelPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents(),
    ) { uris ->
        if (uris.isNullOrEmpty()) return@rememberLauncherForActivityResult
        if (uris.size > 4) {
            scanError = "Pick at most 4 photos — the front, the panel and " +
                "the ingredients is all it can use."
            return@rememberLauncherForActivityResult
        }
        scope.launch {
            scanBusy = true
            scanError = null
            scan = null
            try {
                val encoded = withContext(Dispatchers.IO) {
                    uris.mapNotNull { downscaleUriToBase64(context, it) }
                }
                if (encoded.isEmpty()) {
                    scanError = "Could not read those images."
                    return@launch
                }
                val api = BackendClient.create(
                    settings.backendUrl, settings.bearerToken,
                )
                scan = withContext(Dispatchers.IO) {
                    api.mealsReadLabel(
                        LabelIn(encoded.map { ImageIn(imageBase64 = it) }),
                    )
                }
            } catch (e: Exception) {
                scanError = e.message ?: "could not read that label"
            } finally {
                scanBusy = false
            }
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text(
                "A reference catalog — look up what a food contains, or add " +
                    "one the catalog doesn't have. Adding a food here does NOT " +
                    "mean you have it; that's the Pantry tab.",
                color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 16.sp,
            )
        }
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
        item {
            Button(
                enabled = !scanBusy,
                onClick = { labelPicker.launch("image/*") },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    if (scanBusy) "Reading…"
                    else "Scan a package (front + label + ingredients)",
                )
            }
        }
        scanError?.let { item { ErrorText(it) } }
        scan?.let { sc -> item { LabelScanCard(sc) } }
        selected?.let { f ->
            item {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(NeonMV.Card)
                        .padding(12.dp),
                ) {
                    Text(
                        f.concept?.replaceFirstChar { c -> c.uppercase() } ?: f.name,
                        color = NeonMV.Ink, fontSize = 15.sp,
                        fontWeight = FontWeight.Medium,
                    )
                    if (f.concept != null) {
                        Text(f.name, color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp)
                    }
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

/** What the label said, for checking against the packet in hand.
 *
 *  Deliberately read-only. Nothing is saved from here: a transcription
 *  error written straight into the catalog is a wrong number nobody
 *  knows to look for. */
@Composable
private fun LabelScanCard(sc: LabelScan) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text(
            sc.name.ifBlank { "Nutrition label" },
            color = NeonMV.Ink, fontSize = 14.sp, fontWeight = FontWeight.Medium,
        )
        sc.servingText?.let {
            Text("Serving: $it", color = NeonMV.Muted, fontSize = 11.sp)
        }
        if (!sc.convertible) {
            Text(
                sc.reason ?: "Could not scale these figures to per 100 g.",
                color = NeonMV.Amber, fontSize = 11.sp, lineHeight = 15.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        } else {
            SectionLabel("Per 100 g")
            FoodStat("Calories", sc.per100g["kcal"], 0, "")
            FoodStat("Fat", sc.per100g["fat_g"], 1, " g", emphasise = true)
            FoodStat("Saturated", sc.per100g["saturated_fat_g"], 1, " g")
            FoodStat("Protein", sc.per100g["protein_g"], 1, " g")
            FoodStat("Carbs", sc.per100g["carbs_g"], 1, " g")
            FoodStat("Fibre", sc.per100g["fiber_g"], 1, " g")
            FoodStat("Sugar", sc.per100g["sugar_g"], 1, " g")
            FoodStat("Sodium", sc.per100g["sodium_mg"], 0, " mg")
        }
        if (sc.unreadable.isNotEmpty()) {
            Text(
                "Couldn't read: " + sc.unreadable.joinToString(", ") +
                    " — left blank rather than guessed.",
                color = NeonMV.Amber, fontSize = 10.sp, lineHeight = 14.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        sc.ingredients?.takeIf { it.isNotBlank() }?.let {
            SectionLabel("Ingredients")
            Text(it, color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp)
        }
        sc.notes.forEach {
            Text(
                it, color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
internal fun FoodStat(
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
internal fun SectionLabel(text: String) {
    Text(
        text,
        color = NeonMV.Muted,
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 10.dp, bottom = 4.dp),
    )
}

@Composable
internal fun MutedText(text: String) {
    Text(text, color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 18.sp,
        modifier = Modifier.padding(vertical = 12.dp))
}

@Composable
internal fun ErrorText(text: String) {
    Text(text, color = NeonMV.Bad, fontSize = 12.sp,
        modifier = Modifier.padding(vertical = 8.dp))
}

private val VIT_LABELS = mapOf(
    "vitamin_a_ug" to "Vitamin A",
    "vitamin_d_ug" to "Vitamin D",
    "vitamin_e_mg" to "Vitamin E",
    "vitamin_k_ug" to "Vitamin K",
)
private val VIT_UNITS = mapOf(
    "vitamin_a_ug" to "\u00b5g",
    "vitamin_d_ug" to "\u00b5g",
    "vitamin_e_mg" to "mg",
    "vitamin_k_ug" to "\u00b5g",
)

/** "2.0" reads wrong on an ingredient line; "2" is what a recipe says. */
internal fun trimNum(v: Double): String =
    if (v == v.toLong().toDouble()) v.toLong().toString() else v.toString()

// ─────────────────────────────────────────────────────────── nutrition

/**
 * Diet settings and the standalone fat check — the phone mirror of the
 * web's `views/meals/Nutrition.vue`.
 *
 * Both halves work with zero logging, which is the design floor for this
 * feature: setting a target needs nothing, and checking a number read off
 * a package needs nothing.
 *
 * The app never supplies a default fat target. This screen asks for the
 * number AND where it came from, and the second answer is rendered next
 * to the first wherever the target is used — a figure a clinician gave
 * and a figure the user guessed deserve different confidence.
 */
@Composable
private fun NutritionTab(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    var profile by remember { mutableStateOf<DietProfile?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var savedNote by remember { mutableStateOf(false) }

    var targetG by remember { mutableStateOf("") }
    var targetSource by remember { mutableStateOf("") }
    var trackVitamins by remember { mutableStateOf(true) }
    var kcalTarget by remember { mutableStateOf("") }

    var checkFat by remember { mutableStateOf("") }
    var checkResult by remember { mutableStateOf<FatAssessment?>(null) }
    var checking by remember { mutableStateOf(false) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val p = withContext(Dispatchers.IO) { api.mealsDietProfile() }
            profile = p
            targetG = p.fatPerMealTargetG?.let { trimNum(it) } ?: ""
            targetSource = p.fatTargetSource ?: ""
            trackVitamins = p.trackFatSoluble
            kcalTarget = p.dailyKcalTarget?.toString() ?: ""
            error = null
        } catch (e: Exception) {
            error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        error?.let { item { ErrorText(it) } }
        if (loading) {
            item { MutedText("Loading…") }
            return@LazyColumn
        }

        item {
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(NeonMV.Card)
                    .padding(12.dp),
            ) {
                Text(
                    "Fat per meal", color = NeonMV.Ink, fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Without a gall bladder, bile drips continuously instead of " +
                        "arriving as a bolus, so what matters is how much fat turns " +
                        "up in ONE sitting — not the daily total.",
                    color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 17.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Text(
                    "This app will not guess a limit for you. Tolerance varies a lot " +
                        "between people and usually improves over months, so any " +
                        "number here should be one you were actually given.",
                    color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 17.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )

                OutlinedTextField(
                    value = targetG, onValueChange = { targetG = it },
                    label = { Text("Target grams per meal") },
                    placeholder = { Text("blank if you don't have one") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                )
                OutlinedTextField(
                    value = targetSource, onValueChange = { targetSource = it },
                    label = { Text("Where did this number come from?") },
                    placeholder = { Text("e.g. dietitian, Mar 2026") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                OutlinedTextField(
                    value = kcalTarget, onValueChange = { kcalTarget = it },
                    label = { Text("Daily calorie target (optional)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )

                Row(
                    Modifier.fillMaxWidth().padding(top = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Show fat-soluble vitamins (A, D, E, K) on meals — " +
                            "absorbing these depends on absorbing fat",
                        color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 15.sp,
                        modifier = Modifier.weight(1f),
                    )
                    Switch(checked = trackVitamins, onCheckedChange = { trackVitamins = it })
                }

                Row(
                    Modifier.padding(top = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Button(
                        enabled = !saving,
                        onClick = {
                            scope.launch {
                                saving = true
                                savedNote = false
                                error = null
                                try {
                                    val api = BackendClient.create(
                                        settings.backendUrl, settings.bearerToken,
                                    )
                                    // An empty field CLEARS the value rather than
                                    // leaving it — that is how the user removes a
                                    // target they no longer want judged against.
                                    val p = withContext(Dispatchers.IO) {
                                        api.mealsPutDietProfile(
                                            DietProfileIn(
                                                fatPerMealTargetG = targetG.toDoubleOrNull(),
                                                fatTargetSource =
                                                    targetSource.ifBlank { null },
                                                trackFatSoluble = trackVitamins,
                                                dailyKcalTarget = kcalTarget.toIntOrNull(),
                                            ),
                                        )
                                    }
                                    profile = p
                                    savedNote = true
                                } catch (e: Exception) {
                                    error = e.message ?: "save failed"
                                } finally {
                                    saving = false
                                }
                            }
                        },
                    ) { Text(if (saving) "Saving…" else "Save") }
                    if (savedNote) {
                        Text("  Saved", color = NeonMV.Lime, fontSize = 12.sp)
                    }
                }

                basisNow(profile)?.let {
                    Text(
                        it, color = NeonMV.Muted, fontSize = 11.sp, lineHeight = 16.sp,
                        modifier = Modifier.padding(top = 10.dp),
                    )
                }
            }
        }

        item {
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(NeonMV.Card)
                    .padding(12.dp),
            ) {
                Text(
                    "Check a meal", color = NeonMV.Ink, fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Read the fat off a package or a menu and see how it compares — " +
                        "no recipe or logging needed.",
                    color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 17.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Row(
                    Modifier.fillMaxWidth().padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = checkFat, onValueChange = { checkFat = it },
                        label = { Text("grams of fat") }, singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Button(
                        enabled = !checking && checkFat.toDoubleOrNull() != null,
                        onClick = {
                            scope.launch {
                                checking = true
                                try {
                                    val api = BackendClient.create(
                                        settings.backendUrl, settings.bearerToken,
                                    )
                                    checkResult = withContext(Dispatchers.IO) {
                                        api.mealsAssessFat(checkFat.toDouble())
                                    }
                                } catch (e: Exception) {
                                    error = e.message ?: "check failed"
                                } finally {
                                    checking = false
                                }
                            }
                        },
                        modifier = Modifier.padding(start = 8.dp),
                    ) { Text(if (checking) "…" else "Check") }
                }
                checkResult?.let {
                    Box(Modifier.padding(top = 10.dp)) { FatAssessmentCard(it) }
                }
            }
        }
    }
}

/** What the app will judge against right now, said plainly, so a verdict
 *  appearing on a recipe is never a surprise. */
private fun basisNow(p: DietProfile?): String? {
    if (p == null) return null
    p.fatPerMealTargetG?.let {
        return "Meals are judged against your ${trimNum(it)} g target."
    }
    if (p.comparisonMeals >= p.comparisonMealsNeeded) {
        return "No target set, so meals are judged against the median of your " +
            "${p.comparisonMeals} saved recipes."
    }
    return "No target set, and only ${p.comparisonMeals} of the " +
        "${p.comparisonMealsNeeded} saved recipes needed to compare against. " +
        "Meals will show \"not enough to judge\" until you set a target or add " +
        "more recipes."
}
