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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import app.myvitals.sync.CanMakeOut
import app.myvitals.sync.CanMakeRecipeOut
import app.myvitals.ui.common.PullableMetricBox
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/**
 * What can I cook right now — the phone mirror of the web's CanMake view.
 *
 * The deterministic counterpart to the AI suggestion card: free, offline,
 * and answering which of the user's OWN saved recipes are cookable from
 * what is actually in the house.
 *
 * Two care points, both mirrored from the server's contract:
 *
 * Staples are assumed and the screen says so. Nearly every savoury recipe
 * lists salt and oil, so a strict test answers "no" to everything — but a
 * user who cannot see the assumption cannot tell why a recipe says yes.
 *
 * A recipe with an unidentifiable ingredient renders as "probably", never
 * as cookable, and below the verified ones. Putting the least certain
 * recipe at the top is where it would do the most damage.
 */
@Composable
fun CanMakeTab(
    settings: SettingsRepository,
    /** Lets the empty state hand the user straight to the fix it
     *  names, instead of describing a place they must go find. */
    onOpenRecipes: (() -> Unit)? = null,
) {
    var data by remember { mutableStateOf<CanMakeOut?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var showStaples by remember { mutableStateOf(false) }

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            data = withContext(Dispatchers.IO) { api.mealsCanMake() }
            error = null
        } catch (e: Exception) {
            if (data == null) error = e.message ?: "load failed"
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
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            error?.let { item { ErrorText(it) } }
            if (loading && data == null) item { MutedText("Checking the pantry…") }

            val d = data ?: return@LazyColumn
            if (d.summary.totalRecipes == 0) {
                item {
                    // "this tab" outlived the tabs. And an empty state that
                    // names the fix without offering it is a dead end: the
                    // user has to go back, find Recipes in the list and
                    // start again. Direction A's rule applies here too —
                    // the thing to do next is a button.
                    Column {
                        MutedText(
                            "Nothing to check yet. Save a recipe and this " +
                                "screen tells you which ones your pantry " +
                                "already covers.",
                        )
                        onOpenRecipes?.let { go ->
                            Text(
                                "Go to Recipes",
                                color = NeonMV.Cyan, fontSize = 12.sp,
                                modifier = Modifier
                                    .padding(top = 10.dp)
                                    .clickable(onClick = go),
                            )
                        }
                    }
                }
                return@LazyColumn
            }

            item {
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                        .background(NeonMV.Card).padding(12.dp),
                ) {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(
                            "${d.summary.cookableNow}",
                            color = NeonMV.Ink, fontSize = 26.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            "  cookable now · ${d.summary.missingOne} one item away",
                            color = NeonMV.Muted, fontSize = 12.sp,
                            modifier = Modifier.padding(bottom = 3.dp),
                        )
                    }
                    Text(
                        "From ${d.pantryConcepts} thing" +
                            (if (d.pantryConcepts == 1) "" else "s") +
                            " in your pantry, across ${d.summary.totalRecipes} recipes.",
                        color = NeonMV.Muted, fontSize = 11.sp,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                    Text(
                        if (showStaples) "hide assumptions" else "what's assumed?",
                        color = NeonMV.Cyan, fontSize = 11.sp,
                        modifier = Modifier
                            .padding(top = 4.dp)
                            .clickable { showStaples = !showStaples },
                    )
                    if (showStaples) {
                        Text(
                            "Assumed in the house, never blocking a match: " +
                                d.staplesAssumed.joinToString(", ") + ". Butter is " +
                                "deliberately not among them — half a stick is 46 g " +
                                "of fat, which would silently vanish from a per-meal " +
                                "total.",
                            color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 15.sp,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }
            }

            if (d.unlock.isNotEmpty()) {
                item {
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .background(NeonMV.Card).padding(12.dp),
                    ) {
                        Text(
                            "Buy one thing", color = NeonMV.Amber, fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        d.unlock.forEach { u ->
                            Row(
                                Modifier.fillMaxWidth().padding(top = 4.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    u.item, color = NeonMV.Ink, fontSize = 12.sp,
                                    fontWeight = FontWeight.Medium,
                                    modifier = Modifier.weight(1f),
                                )
                                Text(
                                    "unlocks ${u.unlocks}",
                                    color = NeonMV.Amber, fontSize = 11.sp,
                                )
                            }
                            Text(
                                u.recipes.joinToString(", "),
                                color = NeonMV.Muted, fontSize = 10.sp,
                            )
                        }
                    }
                }
            }

            val cookable = d.recipes.filter { it.cookable }
            val nearly = d.recipes.filter { !it.cookable && it.missing.size == 1 }
            val uncertain = d.recipes.filter { it.uncertain }
            val far = d.recipes.filter { !it.cookable && !it.uncertain && it.missing.size > 1 }

            if (cookable.isNotEmpty()) {
                item { SectionLabel("COOK NOW") }
                items(cookable, key = { it.recipeId }) { RecipeRow(it, NeonMV.Lime) }
            }
            if (nearly.isNotEmpty()) {
                item { SectionLabel("ONE ITEM AWAY") }
                items(nearly, key = { it.recipeId }) { RecipeRow(it, NeonMV.Amber) }
            }
            if (uncertain.isNotEmpty()) {
                item { SectionLabel("PROBABLY — ONE INGREDIENT UNRECOGNISED") }
                items(uncertain, key = { it.recipeId }) { RecipeRow(it, NeonMV.Muted) }
            }
            if (far.isNotEmpty()) {
                item { SectionLabel("FURTHER OFF") }
                items(far, key = { it.recipeId }) { RecipeRow(it, NeonMV.Line) }
            }

            item {
                Text(
                    "This tab costs nothing to run. For ideas beyond your saved " +
                        "recipes, see the Ideas tab.",
                    color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 15.sp,
                    modifier = Modifier.padding(vertical = 10.dp),
                )
            }
        }
    }
}

@Composable
private fun RecipeRow(r: CanMakeRecipeOut, accent: Color) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
            .background(NeonMV.Card),
    ) {
        Box(Modifier.width(3.dp).background(accent).fillMaxWidth(0f))
        Column(Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    r.name, color = NeonMV.Ink, fontSize = 13.sp,
                    modifier = Modifier.weight(1f),
                )
                if (!r.cookable && !r.uncertain) {
                    Text(
                        "${(r.coverage * 100).roundToInt()}%",
                        color = NeonMV.Muted, fontSize = 11.sp,
                    )
                }
            }
            when {
                r.uncertain -> Text(
                    "couldn't identify: " + r.unknown.joinToString(", ") +
                        " — edit the recipe to pick a catalog food",
                    color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
                )
                r.missing.isNotEmpty() -> Text(
                    "needs " + r.missing.joinToString(", "),
                    color = NeonMV.Amber, fontSize = 10.sp,
                )
                r.fromStaples.isNotEmpty() -> Text(
                    "assuming you have " + r.fromStaples.joinToString(", "),
                    color = NeonMV.Muted, fontSize = 10.sp,
                )
            }
        }
    }
}
