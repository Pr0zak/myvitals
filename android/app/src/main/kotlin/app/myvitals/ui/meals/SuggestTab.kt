package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
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
import app.myvitals.sync.MealSuggestion
import app.myvitals.sync.MealSuggestionCard
import app.myvitals.sync.PlanEntryIn
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import kotlin.math.roundToInt

/**
 * AI meal suggestions — the phone mirror of the web's Meal ideas view.
 *
 * The fat verdict beside each suggestion is NOT the model's opinion: the
 * server re-judges every estimate with the same deterministic function
 * the recipe pages use, so this card cannot disagree with the rest of the
 * app about the one number a cholecystectomy makes matter.
 *
 * Generation is explicit — a button, never on entering the tab. Each run
 * is billed against the user's own Anthropic key, and a screen that
 * spends money by being opened is a bad screen. The cached card loads
 * silently on arrival because reading it costs nothing.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SuggestTab(settings: SettingsRepository) {
    val scope = rememberCoroutineScope()
    var card by remember { mutableStateOf<MealSuggestionCard?>(null) }
    var stamp by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var planned by remember { mutableStateOf<Set<String>>(emptySet()) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            return@LaunchedEffect
        }
        // Reading the last card does not bill, so it is safe on arrival.
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val resp = withContext(Dispatchers.IO) { api.mealsSuggestLatest() }
            if (resp.isSuccessful) {
                resp.body()?.let {
                    card = it.analysis
                    stamp = it.generatedAt
                }
            }
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Button(
                enabled = !loading,
                onClick = {
                    scope.launch {
                        loading = true
                        error = null
                        try {
                            val api = BackendClient.create(
                                settings.backendUrl, settings.bearerToken,
                            )
                            val env = withContext(Dispatchers.IO) { api.mealsSuggest() }
                            card = env.analysis
                            stamp = env.generatedAt
                        } catch (e: Exception) {
                            error = e.message ?: "could not generate"
                        } finally {
                            loading = false
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Filled.AutoAwesome, contentDescription = null)
                Text(
                    when {
                        loading -> "  Thinking…"
                        card != null -> "  Refresh suggestions"
                        else -> "  Get suggestions"
                    },
                )
            }
        }
        error?.let { item { ErrorText(it) } }

        val c = card
        if (c == null && !loading) {
            item {
                MutedText(
                    "Suggestions are built from what's in your pantry plus " +
                        "today's training load, fasting state and weight goal. " +
                        "Nothing is generated until you ask — each run uses " +
                        "your own Anthropic key.",
                )
            }
        }

        c?.let { data ->
            item {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(NeonMV.Card)
                        .padding(12.dp),
                ) {
                    Text(
                        data.headline, color = NeonMV.Ink, fontSize = 14.sp,
                        lineHeight = 20.sp,
                    )
                    stamp?.let {
                        Text(
                            // "Suggested Sun 23 Aug, 03:24", not the raw
                            // "2026-08-23T03:24" with its T poked out.
                            prettyStamp(it),
                            color = NeonMV.Muted, fontSize = 10.sp,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }
            }

            items(data.suggestions, key = { it.name }) { s ->
                SuggestionCard(
                    s = s,
                    planned = s.name in planned,
                    onPlan = {
                        scope.launch {
                            try {
                                val api = BackendClient.create(
                                    settings.backendUrl, settings.bearerToken,
                                )
                                withContext(Dispatchers.IO) {
                                    // Added as a NOTE, not a recipe — it is
                                    // not one, and pretending otherwise would
                                    // put invented nutrition into the plan.
                                    api.mealsAddPlanEntry(
                                        PlanEntryIn(
                                            day = LocalDate.now().toString(),
                                            slot = s.slot.ifBlank { "dinner" },
                                            note = s.name,
                                        ),
                                    )
                                }
                                planned = planned + s.name
                            } catch (e: Exception) {
                                error = e.message ?: "could not add to plan"
                            }
                        }
                    },
                )
            }

            if (data.notes.isNotEmpty()) {
                item {
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(NeonMV.Card)
                            .padding(12.dp),
                    ) {
                        data.notes.forEach {
                            Text(
                                it, color = NeonMV.Muted, fontSize = 12.sp,
                                lineHeight = 17.sp,
                                modifier = Modifier.padding(bottom = 4.dp),
                            )
                        }
                    }
                }
            }

            item {
                Text(
                    "Fat and calorie figures here are the model's estimates, " +
                        "not measured values. The verdict beside each one is " +
                        "computed from your own target, but the number it " +
                        "judges is a guess — check the label if it matters.",
                    color = NeonMV.Muted, fontSize = 10.sp, lineHeight = 15.sp,
                    modifier = Modifier.padding(vertical = 8.dp),
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SuggestionCard(
    s: MealSuggestion,
    planned: Boolean,
    onPlan: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card)
            .padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    s.name, color = NeonMV.Ink, fontSize = 14.sp,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    buildString {
                        append(s.slot)
                        s.estPrepMin?.let { append(" · $it min") }
                        s.estKcal?.let { append(" · ${it.roundToInt()} kcal") }
                    },
                    color = NeonMV.Muted, fontSize = 11.sp,
                )
            }
            TextButton(enabled = !planned, onClick = onPlan) {
                Icon(Icons.Filled.EventAvailable, contentDescription = null)
                Text(if (planned) " Planned" else " Plan today")
            }
        }

        Text(
            s.why, color = NeonMV.Muted, fontSize = 12.sp, lineHeight = 17.sp,
            modifier = Modifier.padding(top = 6.dp),
        )

        s.fatAssessment?.let {
            Box(Modifier.padding(top = 8.dp)) { FatAssessmentCard(it, compact = true) }
        }

        if (s.usesFromPantry.isNotEmpty()) {
            ChipRow("from pantry", s.usesFromPantry, NeonMV.Lime)
        }
        if (s.alsoNeeds.isNotEmpty()) {
            ChipRow("also needs", s.alsoNeeds, NeonMV.Amber)
        }

        s.basedOnSavedRecipe?.takeIf { it.isNotBlank() }?.let {
            Text(
                "Based on your saved recipe “$it”.",
                color = NeonMV.Muted, fontSize = 10.sp,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChipRow(
    label: String,
    items: List<String>,
    tint: androidx.compose.ui.graphics.Color,
) {
    FlowRow(
        Modifier.fillMaxWidth().padding(top = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(label, color = NeonMV.Muted, fontSize = 10.sp)
        items.forEach {
            Text(
                it,
                color = tint,
                fontSize = 10.sp,
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .background(NeonMV.CardHigh)
                    .padding(horizontal = 7.dp, vertical = 3.dp),
            )
        }
    }
}


/** An ISO instant as a person reads it. Falls back to the raw string
 *  rather than hiding a value that failed to parse. */
private fun prettyStamp(iso: String): String = runCatching {
    val t = java.time.OffsetDateTime.parse(iso)
        .atZoneSameInstant(java.time.ZoneId.systemDefault())
    "Suggested " + t.format(
        java.time.format.DateTimeFormatter.ofPattern("EEE d MMM, HH:mm"),
    )
}.getOrElse {
    runCatching {
        val t = java.time.LocalDateTime.parse(iso.take(19))
        "Suggested " + t.format(
            java.time.format.DateTimeFormatter.ofPattern("EEE d MMM, HH:mm"),
        )
    }.getOrDefault(iso)
}
