package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.FoodOut
import app.myvitals.ui.neon.NeonMV
import kotlin.math.roundToInt

/**
 * Quantity + unit for a chosen food, offering the food's OWN measures.
 *
 * A free-text unit box makes the user guess at something the app already
 * knows. Raw chicken breast carries `{oz: 28.25, package: 926, piece:
 * 272}` from USDA — so "1 piece" is one breast — but a blank field never
 * says so, and a plausible guess like "breast" or "each" resolves to
 * nothing and silently produces an uncosted line.
 *
 * Each chip shows what the unit weighs, and the running total underneath
 * confirms the conversion landed before anything is saved.
 */

/** Mass units correct for any food. Volume is deliberately absent: a cup
 *  of flour and a cup of honey differ by more than a factor of two, so a
 *  generic "cup" would be a wrong answer dressed as a convenience. */
private val GENERIC_UNITS = listOf(
    "g" to 1.0,
    "oz" to 28.3495,
    "lb" to 453.592,
    "kg" to 1000.0,
)

@Composable
fun QuantityPicker(
    food: FoodOut?,
    quantity: String,
    unit: String,
    onQuantityChange: (String) -> Unit,
    onUnitChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String = "How much?",
    /** Measures to offer when the caller holds the map but not the whole
     *  food — the recipe editor keeps only what it needs per line. */
    ownUnits: Map<String, Double>? = null,
) {
    val own = (ownUnits ?: food?.unitGrams ?: emptyMap()).toList()
        .sortedBy { it.second }
    val ownNames = own.map { it.first }.toSet()
    val generic = GENERIC_UNITS.filterNot { it.first in ownNames }

    val grams: Double? = quantity.toDoubleOrNull()?.takeIf { it > 0 }?.let { q ->
        val per = (ownUnits ?: food?.unitGrams)?.get(unit)
            ?: GENERIC_UNITS.firstOrNull { it.first == unit }?.second
        per?.let { q * it }
    }

    Column(modifier.fillMaxWidth()) {
        OutlinedTextField(
            value = quantity,
            onValueChange = onQuantityChange,
            label = { Text(label) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        if (own.isNotEmpty()) {
            Text(
                "This food",
                color = NeonMV.Muted, fontSize = 9.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                own.forEach { (name, g) ->
                    UnitChip(
                        label = "$name · ${fmtGrams(g)}",
                        selected = unit == name,
                        onClick = { onUnitChange(name) },
                    )
                }
            }
        }

        Text(
            "By weight",
            color = NeonMV.Muted, fontSize = 9.sp,
            modifier = Modifier.padding(top = 6.dp),
        )
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            generic.forEach { (name, _) ->
                UnitChip(
                    label = name,
                    selected = unit == name,
                    onClick = { onUnitChange(name) },
                )
            }
        }

        when {
            grams != null -> Text(
                "= ${fmtGrams(grams)}",
                color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
            quantity.isNotBlank() && unit.isNotBlank() -> Text(
                "This food has no conversion for “$unit” — pick another " +
                    "unit or enter it by weight.",
                color = NeonMV.Amber, fontSize = 10.sp, lineHeight = 14.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
private fun UnitChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label,
        color = if (selected) NeonMV.OnAccent else NeonMV.Muted,
        fontSize = 11.sp,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (selected) NeonMV.Lime else NeonMV.CardHigh)
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 5.dp),
    )
}

private fun fmtGrams(g: Double): String =
    if (g >= 1000) String.format("%.2f kg", g / 1000) else "${g.roundToInt()} g"
