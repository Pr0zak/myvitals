package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.BarcodeHit
import app.myvitals.sync.FoodIn
import app.myvitals.sync.PantryItemIn
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/**
 * MEAL-BARCODE — scan a pack, look it up, confirm it.
 *
 * The catalog bundled with this app is USDA: generic foods, no brands.
 * About half this diet is packaged, so every packaged entry began by
 * typing a product name into a catalog that does not contain it. That is
 * the friction the meals plan said to wait for and then fix.
 *
 * Nothing is added by scanning. The lookup returns a CANDIDATE and this
 * shows it until the user says yes — the same rule the photo features
 * follow, and for the same reason: Open Food Facts is crowd-sourced and
 * its entries are sometimes wrong in ways only the person holding the
 * packet can see. A live probe of Lay's Classic Potato Chips came back
 * with an ingredients list for cheese.
 *
 * So the confirm step shows the pack size and the per-100 g figures
 * verbatim, and says where they came from. Those are what let someone
 * catch a wrong entry before it is in their catalog forever.
 */
@Composable
internal fun BarcodeAdd(
    settings: SettingsRepository,
    /** True in the pantry: confirming stocks it as well as defining it. */
    stock: Boolean,
    onAdded: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var hit by remember { mutableStateOf<BarcodeHit?>(null) }

    // Without this the first scan of the app's life stalls on a silent
    // module download while the button appears to do nothing.
    LaunchedEffect(Unit) { BarcodeScan.warmUp(context) }

    fun lookUp(code: String) {
        busy = true
        error = null
        scope.launch {
            runCatching {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                withContext(Dispatchers.IO) { api.mealsBarcode(code) }
            }.onSuccess { hit = it }.onFailure {
                // 404 is the ordinary outcome for a product neither source
                // knows, and it has a good next step, so it is not phrased
                // as a failure.
                error = if (it.message?.contains("404") == true) {
                    "Nothing found for that barcode. Scan the label instead " +
                        "— it needs no database."
                } else {
                    it.message ?: "could not look that up"
                }
            }
            busy = false
        }
    }

    fun confirm(h: BarcodeHit) {
        busy = true
        scope.launch {
            runCatching {
                val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
                withContext(Dispatchers.IO) {
                    // Already ours: nothing to define, only to stock.
                    val id = h.foodId ?: api.mealsCreateFood(
                        FoodIn(
                            name = h.name,
                            kcal = h.nutrition["kcal"],
                            proteinG = h.nutrition["protein_g"],
                            carbsG = h.nutrition["carbs_g"],
                            fatG = h.nutrition["fat_g"],
                            saturatedFatG = h.nutrition["saturated_fat_g"],
                            fiberG = h.nutrition["fiber_g"],
                            sugarG = h.nutrition["sugar_g"],
                            sodiumMg = h.nutrition["sodium_mg"],
                            ingredients = h.ingredients,
                            barcode = h.barcode,
                            category = h.category,
                        ),
                    ).id
                    if (stock) api.mealsAddPantry(PantryItemIn(foodId = id))
                }
            }.onSuccess {
                hit = null
                onAdded()
            }.onFailure { error = it.message ?: "could not save that" }
            busy = false
        }
    }

    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card).padding(12.dp),
    ) {
        Text(
            "Scan a barcode", color = NeonMV.Ink, fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
        )
        // "Looks the pack up by its barcode" restated the title, and went.
        // What stays is the promise, which the user cannot infer and which
        // is the reason to trust the button at all.
        Text(
            "Nothing is added until you confirm it.",
            color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 14.sp,
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )

        val current = hit
        if (current == null) {
            Button(
                enabled = !busy,
                onClick = {
                    BarcodeScan.scanner(context).startScan()
                        .addOnSuccessListener { b ->
                            val raw = b.rawValue
                            if (raw.isNullOrBlank()) {
                                error = "That barcode could not be read."
                            } else {
                                lookUp(raw)
                            }
                        }
                        .addOnCanceledListener { /* backed out; say nothing */ }
                        .addOnFailureListener {
                            error = it.message ?: "the scanner could not start"
                        }
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (busy) "Looking up…" else "Scan barcode") }
        } else {
            Text(current.name, color = NeonMV.Ink, fontSize = 14.sp,
                 fontWeight = FontWeight.Medium)
            Text(
                buildString {
                    append(
                        if (current.origin == "local") "already in your catalog"
                        else "from Open Food Facts",
                    )
                    current.packageSize?.let { append(" · $it") }
                },
                color = if (current.origin == "local") NeonMV.Lime else NeonMV.Muted,
                fontSize = 10.sp,
                modifier = Modifier.padding(top = 2.dp),
            )
            // Per 100 g, verbatim. A wrong Open Food Facts entry is
            // usually obvious from these — it is why they are shown
            // before anything is saved rather than after.
            Text(
                listOfNotNull(
                    current.nutrition["kcal"]?.let { "${it.roundToInt()} kcal" },
                    current.nutrition["fat_g"]?.let { "${it.roundToInt()} g fat" },
                    current.nutrition["protein_g"]?.let { "${it.roundToInt()} g protein" },
                ).joinToString(" · ").ifEmpty { "no nutrition published" }
                    + "  per 100 g",
                color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
            Row(
                Modifier.padding(top = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(
                    enabled = !busy,
                    onClick = { confirm(current) },
                    modifier = Modifier.weight(1f),
                ) { Text(if (stock) "Add to pantry" else "Add to catalog") }
                OutlinedButton(
                    enabled = !busy,
                    onClick = { hit = null },
                    modifier = Modifier.weight(1f),
                ) { Text("Discard") }
            }
        }

        error?.let {
            Text(
                it, color = NeonMV.Bad, fontSize = 11.sp, lineHeight = 15.sp,
                modifier = Modifier
                    .padding(top = 8.dp)
                    .clickable { error = null },
            )
        }
    }
}
