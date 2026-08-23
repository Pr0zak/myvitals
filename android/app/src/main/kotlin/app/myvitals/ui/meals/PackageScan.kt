package app.myvitals.ui.meals

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FoodIn
import app.myvitals.sync.ImageIn
import app.myvitals.sync.LabelIn
import app.myvitals.sync.LabelScan
import app.myvitals.sync.QuickAddIn
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Scan a packaged food from photos of its packaging.
 *
 * Used in two places, because the same photos serve two intents:
 *
 *   Foods  — "define this product" (catalog entry only)
 *   Pantry — "I just bought this" (define it AND stock it)
 *
 * Putting a product definition in the catalog is the right taxonomy, but
 * making someone scan in Foods and then search for the result in Pantry
 * is two steps for one intent. `stock` collapses that.
 *
 * Several photos of the SAME pack: the Nutrition Facts panel has the
 * numbers and no product name, the front has the name and no numbers,
 * and a third of the ingredients list is transcribed verbatim.
 *
 * Nothing is saved until confirmed — a transcription error written
 * straight into the catalog is a wrong number nobody knows to look for.
 */
@Composable
fun PackageScan(
    settings: SettingsRepository,
    onSaved: () -> Unit,
    modifier: Modifier = Modifier,
    stock: Boolean = false,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var busy by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var scan by remember { mutableStateOf<LabelScan?>(null) }
    var name by remember { mutableStateOf("") }
    var servingG by remember { mutableStateOf("") }

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetMultipleContents(),
    ) { uris ->
        if (uris.isNullOrEmpty()) return@rememberLauncherForActivityResult
        if (uris.size > 4) {
            error = "Pick at most 4 photos — the front, the panel and the " +
                "ingredients is all it can use."
            return@rememberLauncherForActivityResult
        }
        scope.launch {
            busy = true
            error = null
            scan = null
            try {
                val encoded = withContext(Dispatchers.IO) {
                    uris.mapNotNull { downscaleUriToBase64(context, it) }
                }
                if (encoded.isEmpty()) {
                    error = "Could not read those images."
                    return@launch
                }
                val api = BackendClient.create(
                    settings.backendUrl, settings.bearerToken,
                )
                val r = withContext(Dispatchers.IO) {
                    api.mealsReadLabel(
                        LabelIn(encoded.map { ImageIn(imageBase64 = it) }),
                    )
                }
                scan = r
                name = r.name
                servingG = r.servingSizeG?.let { g ->
                    if (g == g.toLong().toDouble()) g.toLong().toString()
                    else g.toString()
                } ?: ""
            } catch (e: Exception) {
                error = e.message ?: "could not read those photos"
            } finally {
                busy = false
            }
        }
    }

    Column(
        modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text(
            "Scan a package", color = NeonMV.Ink, fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Photograph the front, the Nutrition Facts panel and, if you " +
                "like, the ingredients — select them together. The panel has " +
                "the numbers but no product name; the front has the name." +
                if (stock) " Saving adds it to your pantry too." else "",
            color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )

        Button(
            enabled = !busy,
            onClick = { picker.launch("image/*") },
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (busy) "Reading…" else "Choose photos") }

        error?.let {
            Text(
                it, color = NeonMV.Bad, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }

        scan?.let { r ->
            OutlinedTextField(
                value = name, onValueChange = { name = it },
                label = { Text("Name") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )

            if (!r.convertible) {
                Text(
                    r.reason ?: "Could not scale these figures to per 100 g.",
                    color = NeonMV.Amber, fontSize = 11.sp, lineHeight = 15.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
            } else {
                SectionLabel("Per 100 g")
                FoodStat("Calories", r.per100g["kcal"], 0, "")
                FoodStat("Fat", r.per100g["fat_g"], 1, " g", emphasise = true)
                FoodStat("Saturated", r.per100g["saturated_fat_g"], 1, " g")
                FoodStat("Protein", r.per100g["protein_g"], 1, " g")
                FoodStat("Carbs", r.per100g["carbs_g"], 1, " g")
                FoodStat("Fibre", r.per100g["fiber_g"], 1, " g")
                FoodStat("Sugar", r.per100g["sugar_g"], 1, " g")
                FoodStat("Sodium", r.per100g["sodium_mg"], 0, " mg")
            }

            OutlinedTextField(
                value = servingG, onValueChange = { servingG = it },
                label = { Text("Serving (g), optional") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )

            r.ingredients?.takeIf { it.isNotBlank() }?.let {
                SectionLabel("Ingredients")
                Text(it, color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp)
            }
            if (r.unreadable.isNotEmpty()) {
                Text(
                    "Couldn't read: " + r.unreadable.joinToString(", ") +
                        " — left blank rather than guessed.",
                    color = NeonMV.Amber, fontSize = 10.sp, lineHeight = 14.sp,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            r.notes.forEach {
                Text(
                    it, color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }

            Button(
                enabled = !saving && r.convertible && name.isNotBlank(),
                onClick = {
                    scope.launch {
                        saving = true
                        error = null
                        try {
                            val api = BackendClient.create(
                                settings.backendUrl, settings.bearerToken,
                            )
                            val food = withContext(Dispatchers.IO) {
                                api.mealsCreateFood(
                                    FoodIn(
                                        name = name.trim(),
                                        kcal = r.per100g["kcal"],
                                        proteinG = r.per100g["protein_g"],
                                        carbsG = r.per100g["carbs_g"],
                                        fatG = r.per100g["fat_g"],
                                        saturatedFatG = r.per100g["saturated_fat_g"],
                                        fiberG = r.per100g["fiber_g"],
                                        sugarG = r.per100g["sugar_g"],
                                        sodiumMg = r.per100g["sodium_mg"],
                                        ingredients = r.ingredients,
                                        unitGrams = servingG.toDoubleOrNull()
                                            ?.let { g -> mapOf("serving" to g) },
                                    ),
                                )
                            }
                            if (stock) {
                                withContext(Dispatchers.IO) {
                                    api.mealsQuickAddPantry(QuickAddIn(listOf(food.id)))
                                }
                            }
                            scan = null
                            name = ""
                            servingG = ""
                            onSaved()
                        } catch (e: Exception) {
                            error = e.message ?: "could not save"
                        } finally {
                            saving = false
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
            ) {
                Text(
                    when {
                        saving -> "Saving…"
                        stock -> "Save & add to pantry"
                        else -> "Save food"
                    },
                )
            }
        }
    }
}
