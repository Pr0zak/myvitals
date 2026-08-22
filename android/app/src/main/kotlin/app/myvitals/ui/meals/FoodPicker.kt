package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FoodOut
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/**
 * Type-ahead search over the food catalog, mirroring the web
 * `FoodPicker.vue` so the two surfaces behave identically.
 *
 * `ingredientsOnly` picks which half of the catalog is offered. The same
 * table holds whole ingredients and prepared foods — chicken breast and
 * a Big Mac — because a recipe needs the first and a food log needs the
 * second. The caller says which lens it wants.
 *
 * Ranking is the server's job. Do NOT re-sort here: the backend already
 * handles USDA's inverted naming ("Oil, olive, salad or cooking") and
 * demotes processed forms, and a second sort in Compose would silently
 * disagree with the web dashboard.
 */
@Composable
fun FoodPicker(
    settings: SettingsRepository,
    onPick: (FoodOut) -> Unit,
    modifier: Modifier = Modifier,
    ingredientsOnly: Boolean = false,
    placeholder: String = "Search foods…",
) {
    var term by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<FoodOut>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    // Debounce, then search. Keying the effect on the term means a new
    // keystroke cancels the previous coroutine before it fires, so only
    // the last query in a burst reaches the network and a slow early
    // response can never overwrite a newer one.
    LaunchedEffect(term, ingredientsOnly) {
        val q = term.trim()
        if (q.length < 2) {
            results = emptyList()
            error = null
            return@LaunchedEffect
        }
        delay(220)
        busy = true
        error = null
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            results = withContext(Dispatchers.IO) {
                api.mealsSearchFoods(q, ingredientsOnly, 20)
            }
        } catch (e: Exception) {
            error = e.message ?: "search failed"
            results = emptyList()
        } finally {
            busy = false
        }
    }

    Column(modifier = modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = term,
            onValueChange = { term = it },
            label = { Text(placeholder) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        val q = term.trim()
        when {
            error != null -> Hint(error!!, NeonMV.Bad)
            busy && results.isEmpty() -> Hint("Searching…")
            q.length == 1 -> Hint("Keep typing…")
            q.length >= 2 && !busy && results.isEmpty() -> Hint("Nothing matched \"$q\".")
        }

        if (results.isNotEmpty()) {
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 280.dp)
                    .padding(top = 6.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(NeonMV.Card),
                verticalArrangement = Arrangement.spacedBy(1.dp),
            ) {
                items(results, key = { it.id }) { f ->
                    FoodRow(f) {
                        onPick(f)
                        term = ""
                        results = emptyList()
                    }
                }
            }
        }
    }
}

@Composable
private fun FoodRow(f: FoodOut, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .background(NeonMV.CardHigh)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                // Concept first. USDA's full name is precise and
                // unscannable, so it is demoted to the line below rather
                // than hidden — the precision is what makes the
                // nutrition right.
                f.concept?.replaceFirstChar { it.uppercase() } ?: f.name,
                color = NeonMV.Ink,
                fontSize = 13.sp,
                lineHeight = 17.sp,
                modifier = Modifier.weight(1f),
            )
            if (f.source != "usda") {
                Text(
                    "yours",
                    color = NeonMV.Muted,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Medium,
                )
            }
        }
        if (f.concept != null) {
            Text(
                f.name, color = NeonMV.Muted, fontSize = 10.sp,
                lineHeight = 13.sp,
            )
        }
        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            modifier = Modifier.padding(top = 2.dp),
        ) {
            // A null nutrient renders as an em dash, never as 0 — "we do
            // not know this food's calories" is not "this food has none".
            Text(
                f.kcal?.let { "${it.roundToInt()} kcal" } ?: "— kcal",
                color = NeonMV.Ink,
                fontSize = 11.sp,
            )
            f.fatG?.let {
                Text(String.format("%.1fg fat", it), color = NeonMV.Muted, fontSize = 11.sp)
            }
            Text("per 100 g", color = NeonMV.Muted, fontSize = 11.sp)
        }
    }
}

@Composable
private fun Hint(text: String, color: androidx.compose.ui.graphics.Color = NeonMV.Muted) {
    Text(text, color = color, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
}
