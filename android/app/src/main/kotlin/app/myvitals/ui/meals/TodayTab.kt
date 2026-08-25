package app.myvitals.ui.meals

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
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
import app.myvitals.sync.LogDayOut
import app.myvitals.sync.LogEntryIn
import app.myvitals.sync.PrepTargetsOut
import app.myvitals.sync.RecentEntryOut
import app.myvitals.sync.RecipeOut
import app.myvitals.sync.RepeatDayIn
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

/**
 * Direction A — Meals IS today.
 *
 * The screen this replaces put ten destinations in a horizontally
 * scrolling chip row, of which about five fit. Four of the hidden ones
 * were weekly or occasional tasks competing for the same row as the one
 * thing done twice a day. Here the daily task owns the screen and
 * everything else lives behind a single door, so the common case costs
 * no navigation at all.
 *
 * Everything shown is fetched, never derived on the phone: the totals,
 * the per-slot grouping and the per-meal fat verdict all come from
 * `/meals/log`, and the energy target from `/meals/prep/targets`.
 */
@Composable
fun TodayTab(settings: SettingsRepository, onOpenMore: () -> Unit) {
    val scope = rememberCoroutineScope()
    var day by remember { mutableStateOf<LogDayOut?>(null) }
    var targets by remember { mutableStateOf<PrepTargetsOut?>(null) }
    var recents by remember { mutableStateOf<List<RecentEntryOut>>(emptyList()) }
    var recipes by remember { mutableStateOf<List<RecipeOut>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var adding by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }

    val today = LocalDate.now().toString()

    suspend fun fetch() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — set URL + token in Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) {
                day = api.mealsLog(today, 1).firstOrNull()
                // Each of these is optional context, never a reason to fail
                // the screen: a missing target means the ring says so.
                targets = runCatching { api.prepTargets() }.getOrNull()
                recents = runCatching { api.mealsLogRecent(12) }.getOrDefault(emptyList())
                if (recipes.isEmpty()) {
                    recipes = runCatching { api.mealsRecipes() }.getOrDefault(emptyList())
                }
            }
            error = null
        } catch (e: Exception) {
            if (day == null) error = e.message ?: "load failed"
        } finally {
            loading = false
        }
    }

    fun act(block: suspend (api: app.myvitals.sync.BackendApi) -> Unit) {
        if (busy) return
        busy = true
        scope.launch {
            runCatching {
                block(BackendClient.create(settings.backendUrl, settings.bearerToken))
            }.onFailure { error = it.message ?: "could not log" }
            fetch()
            busy = false
        }
    }

    LaunchedEffect(Unit) { fetch() }

    if (adding) {
        LogEntryDialog(
            settings = settings, day = today, recipes = recipes,
            onDismiss = { adding = false },
            onSave = { body ->
                adding = false
                act { api -> withContext(Dispatchers.IO) { api.mealsAddLogEntry(body) } }
            },
        )
    }

    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            Modifier.fillMaxSize().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.Bottom) {
                    Text("Today", color = NeonMV.Ink, fontSize = 22.sp,
                         fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.weight(1f))
                    Text(
                        LocalDate.now().format(DateTimeFormatter.ofPattern("EEE d MMM")),
                        color = NeonMV.Muted, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 3.dp),
                    )
                }
            }

            error?.let { msg -> item { Text(msg, color = NeonMV.Bad, fontSize = 12.sp) } }
            if (loading && day == null) item { Text("Loading…", color = NeonMV.Muted, fontSize = 12.sp) }

            item { TotalsCard(day, targets) }

            if (recents.isNotEmpty()) {
                item {
                    Row(
                        Modifier.horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        // First, not last. As the trailing item it sat past
                        // the right edge on a phone — which is precisely the
                        // hidden-affordance problem this screen exists to fix.
                        Text(
                            "Same as yesterday",
                            color = if (busy) NeonMV.Muted else NeonMV.Cyan, fontSize = 11.sp,
                            modifier = Modifier
                                .clip(RoundedCornerShape(999.dp))
                                .background(NeonMV.CardHigh)
                                .clickable(enabled = !busy) {
                                    act { api ->
                                        withContext(Dispatchers.IO) {
                                            api.mealsRepeatDay(
                                                RepeatDayIn(
                                                    source = LocalDate.now().minusDays(1).toString(),
                                                    target = today,
                                                ),
                                            )
                                        }
                                    }
                                }
                                .padding(horizontal = 10.dp, vertical = 6.dp),
                        )
                        recents.forEach { r ->
                            Row(
                                Modifier
                                    .clip(RoundedCornerShape(999.dp))
                                    .background(NeonMV.CardHigh)
                                    .clickable(enabled = !busy) {
                                        act { api ->
                                            withContext(Dispatchers.IO) {
                                                api.mealsAddLogEntry(
                                                    LogEntryIn(
                                                        day = today, slot = r.usualSlot,
                                                        foodId = r.foodId, recipeId = r.recipeId,
                                                        label = if (r.foodId == null && r.recipeId == null) r.label else null,
                                                        quantity = r.quantity, unit = r.unit,
                                                        servings = r.servings,
                                                        manualKcal = r.manualKcal,
                                                        manualFatG = r.manualFatG,
                                                    ),
                                                )
                                            }
                                        }
                                    }
                                    .padding(horizontal = 10.dp, vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(r.label, color = NeonMV.Ink, fontSize = 11.sp, maxLines = 1)
                                if (r.quantity != null) {
                                    Text(
                                        "  " + trimNum(r.quantity) + (r.unit?.let { " $it" } ?: ""),
                                        color = NeonMV.Muted, fontSize = 10.sp, maxLines = 1,
                                    )
                                }
                            }
                        }
                    }
                }
            }

            // One row per slot, always all four. An empty slot is shown as
            // empty rather than hidden: "I have not eaten lunch" and "lunch
            // is not a thing I log" look identical once the row disappears.
            for (slot in LOG_SLOTS) {
                item(key = "slot-$slot") { SlotRow(slot, day) }
            }

            item {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(18.dp))
                        .background(NeonMV.Card)
                        .clickable(onClick = onOpenMore)
                        .padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text("Plan & kitchen", color = NeonMV.Ink, fontSize = 13.sp,
                             fontWeight = FontWeight.SemiBold)
                        Text("Week, shopping, pantry, recipes", color = NeonMV.Muted,
                             fontSize = 11.sp, modifier = Modifier.padding(top = 2.dp))
                    }
                    Spacer(Modifier.weight(1f))
                    Icon(Icons.Filled.ChevronRight, null, tint = NeonMV.Muted)
                }
            }

            item { Spacer(Modifier.height(80.dp)) }
        }

        // The one action this screen exists for, always in reach.
        Row(
            Modifier
                .align(Alignment.BottomCenter)
                .padding(horizontal = 16.dp, vertical = 16.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(999.dp))
                .background(NeonMV.Lime)
                .clickable { adding = true }
                .padding(vertical = 15.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Add, null, tint = NeonMV.OnAccent, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("Log something", color = NeonMV.OnAccent, fontSize = 15.sp,
                 fontWeight = FontWeight.Bold)
        }
    }
}

/**
 * Energy and fat so far, against the target when there is one.
 *
 * With no target the bar is absent and the figure stands alone — an
 * invented denominator would make a real number look like progress
 * toward something nobody set. Fat carries no target at all here by
 * design: tolerance after a cholecystectomy varies too much between
 * people for the app to guess one, and the per-meal verdict on each
 * slot is where that judgement belongs.
 */
@Composable
private fun TotalsCard(day: LogDayOut?, targets: PrepTargetsOut?) {
    val kcal = day?.totals?.get("kcal")
    val fat = day?.totals?.get("fat_g")
    val target = targets?.takeIf { it.ok }?.targetKcal
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(NeonMV.Card)
            .padding(16.dp),
    ) {
        if (kcal == null) {
            // Nothing logged yet. A 32sp em-dash hovering over "of 2,310
            // kcal" is honest about the absence and reads as a rendering
            // fault; a sentence says the same thing and looks deliberate.
            Text("Nothing logged yet today", color = NeonMV.Ink, fontSize = 15.sp,
                 fontWeight = FontWeight.Medium)
            Text(
                target?.let { "Target %,d kcal".format(it) }
                    ?: "No energy target set — add your profile in Settings",
                color = NeonMV.Muted, fontSize = 11.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        } else {
            Row(verticalAlignment = Alignment.Bottom) {
                Column {
                    Text(
                        "%,d".format(kcal.roundToInt()),
                        color = NeonMV.Ink, fontSize = 32.sp, fontWeight = FontWeight.Bold,
                    )
                    Text(
                        target?.let { "of %,d kcal".format(it) } ?: "kcal — no target set",
                        color = NeonMV.Muted, fontSize = 11.sp,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
                Spacer(Modifier.weight(1f))
                Column(horizontalAlignment = Alignment.End) {
                    // Null stays null: a day with no costable entry has an
                    // UNKNOWN fat total, not a zero one.
                    Text(
                        fat?.let { String.format("%.0f g", it) } ?: "—",
                        color = NeonMV.Amber, fontSize = 19.sp, fontWeight = FontWeight.Bold,
                    )
                    Text("fat today", color = NeonMV.Muted, fontSize = 11.sp,
                         modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
        if (kcal != null && target != null && target > 0) {
            val frac = (kcal / target).coerceIn(0.0, 1.0).toFloat()
            Box(
                Modifier
                    .fillMaxWidth()
                    .padding(top = 14.dp)
                    .height(6.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(NeonMV.Track),
            ) {
                Box(
                    Modifier
                        .fillMaxWidth(frac)
                        .height(6.dp)
                        .clip(RoundedCornerShape(999.dp))
                        .background(if (kcal > target) NeonMV.Amber else NeonMV.Lime),
                )
            }
        }
        if (day != null && day.unresolvedCount > 0) {
            Text(
                "${day.unresolvedCount} not costed — this understates the total",
                color = NeonMV.Amber, fontSize = 10.sp,
                modifier = Modifier.padding(top = 10.dp),
            )
        }
    }
}

/** One meal. The fat verdict belongs here, not on the day: without a
 *  gall bladder the constraint is how much fat lands at once. */
@Composable
private fun SlotRow(slot: String, day: LogDayOut?) {
    val meal = day?.meals?.firstOrNull { it.slot == slot }
    val entries = meal?.entries.orEmpty()
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(NeonMV.Card)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                slot.replaceFirstChar { it.uppercase() },
                color = if (entries.isEmpty()) NeonMV.Muted else NeonMV.Ink,
                fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.width(78.dp),
            )
            if (entries.isEmpty()) {
                Text("not logged", color = NeonMV.Muted, fontSize = 12.sp,
                     modifier = Modifier.weight(1f))
            } else {
                Text(
                    entries.joinToString(" · ") { it.label },
                    color = NeonMV.Muted, fontSize = 12.sp, maxLines = 2,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    meal?.totals?.get("kcal")?.let { "${it.roundToInt()}" } ?: "—",
                    color = NeonMV.Muted, fontSize = 12.sp,
                )
            }
        }
        // Grey when it cannot be judged, never green: "no target set" must
        // not borrow the reassurance of "this is fine".
        meal?.fatAssessment?.let { fa ->
            Text(
                fa.reason ?: fatVerdictLabel(fa.verdict),
                color = when (fa.verdict) {
                    "very_high", "high" -> NeonMV.Bad
                    "approaching" -> NeonMV.Amber
                    "ok" -> NeonMV.Lime
                    // "unknown" included: grey, never green. A verdict the
                    // app cannot reach must not borrow the reassurance of
                    // one it can.
                    else -> NeonMV.Muted
                },
                fontSize = 10.sp,
                modifier = Modifier.padding(top = 6.dp, start = 78.dp),
            )
        }
    }
}

/** The verdict in words, for when the server sent no reason line. */
private fun fatVerdictLabel(v: String): String = when (v) {
    "very_high" -> "well over your per-meal fat target"
    "high" -> "over your per-meal fat target"
    "approaching" -> "close to your per-meal fat target"
    "ok" -> "within your per-meal fat target"
    else -> "no per-meal fat target set"
}
