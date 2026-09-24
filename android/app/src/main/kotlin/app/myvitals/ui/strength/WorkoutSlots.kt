package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutExerciseRow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumberFamily

/*
 * UI-2 — one exercise slot in the list under the hero, in whichever of five
 * shapes its state calls for:
 *
 *   hero slot     the full card with the set grid (the NOW row outlined)
 *   up next       a compact line; tap it to make it the hero (out-of-order
 *                 logging, which every slot's own entry form used to allow)
 *   finished      a 56dp summary on a surface darker than Card, expandable
 *   skipped       SKIP-1 strip with Undo
 *   not logged    an untouched slot on a session that is over
 */

private val RowShape = RoundedCornerShape(14.dp)

@Composable
internal fun ExerciseSlot(
    st: StrengthTodayState,
    plan: StrengthWorkoutDetail,
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    isHero: Boolean,
    sessionOver: Boolean,
    actions: StrengthTodayActions,
    backendBaseUrl: String,
) {
    // SKIP-1 — Swap and Skip share one guard: nothing real logged against
    // this slot AND the session still open to edits.
    val canEditSlot = !sessionOver && wex.sets.none { it.actualReps != null && !it.skipped }
    val closed = isSlotClosed(wex, plan.status)
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    val label = "${wex.orderIndex + 1}. $name"
    val skipErr = st.skipError?.takeIf { it.first == wex.id }?.second

    @Composable
    fun fullCard() = ExerciseCard(
        wex = wex,
        info = info,
        inputs = st.setInputs,
        canSwap = canEditSlot,
        canSkip = canEditSlot,
        closed = closed,
        skipBusy = st.skipBusyWexId == wex.id,
        // Any skip in flight disables every Skip/Undo — two overlapping
        // PATCHes race whole-workout responses into the same state.
        skipLocked = st.skipBusyWexId != null,
        skipError = skipErr,
        heroSetNum = if (isHero) nextSetOf(wex) else null,
        sessionWritable = !sessionOver && plan.status != "paused",
        editingSetNum = st.editingSetKey
            ?.takeIf { it.startsWith("${wex.id}-") }
            ?.substringAfter("-")?.toIntOrNull(),
        // -1 is the Cancel signal from the correction row.
        onEditSet = { n ->
            st.editingSetKey = if (n < 0) null else "${wex.id}-$n"
            if (n < 0) st.setInputs.clear()
        },
        onDeleteSet = actions.deleteSet,
        onLogSet = { setNum, weight, reps, rating, setType ->
            actions.logSet(wex, setNum, weight, reps, rating, setType)
        },
        onYouTube = { slug, n -> actions.youTube(slug, n) },
        onSwap = { st.swapWexId = wex.id },
        onSkipChange = { skipped -> actions.skipExercise(wex, skipped) },
        onSetPref = { pref -> actions.setPref(wex.exerciseId, pref) },
        partnerName = wex.supersetId?.let { ss ->
            plan.exercises.firstOrNull { it.supersetId == ss && it.id != wex.id }
                ?.let { st.catalog[it.exerciseId]?.name ?: it.exerciseId.replace('_', ' ') }
        },
        backendBaseUrl = backendBaseUrl,
    )

    when {
        wex.skipped -> SlotStrip(label = label, state = "Skipped", error = skipErr) {
            // Undo rides the same guard as Skip.
            if (canEditSlot) {
                TextButton(
                    onClick = { actions.skipExercise(wex, false) },
                    enabled = st.skipBusyWexId == null,
                    modifier = Modifier.heightIn(min = 40.dp),
                ) {
                    Text(if (st.skipBusyWexId == wex.id) "Restoring…" else "Undo",
                        color = NeonMV.Cyan, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        // The session is over and this slot was never touched. Not a skip.
        closed && wex.sets.none { it.actualReps != null || it.skipped } ->
            SlotStrip(label = label, state = "Not logged")
        isHero -> fullCard()
        closed -> {
            val open = st.expandedDone[wex.id] == true
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                DoneSummaryRow(wex, label, open) { st.expandedDone[wex.id] = !open }
                if (open) fullCard()
            }
        }
        else -> UpNextRow(wex, info, label) { st.focusWexId = wex.id }
    }
}

/** A finished slot: one 56dp line on a surface darker than Card. */
@Composable
private fun DoneSummaryRow(
    wex: StrengthWorkoutExerciseRow,
    label: String,
    expanded: Boolean,
    onToggle: () -> Unit,
) {
    val complete = isSlotSettled(wex)
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clip(RowShape)
            .background(WorkoutDoneSurface)
            .border(1.dp, NeonMV.Line, RowShape)
            .clickable(onClick = onToggle)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            Icons.Outlined.CheckCircle, contentDescription = null,
            tint = if (complete) NeonMV.Lime else NeonMV.Muted,
            modifier = Modifier.size(20.dp),
        )
        Spacer(Modifier.width(10.dp))
        Text(label, color = NeonMV.Muted, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        Text(
            "${accountedSets(wex)}/${wex.targetSets} sets",
            color = NeonMV.Muted, fontSize = 12.sp, fontFamily = NeonNumberFamily,
        )
        Icon(
            if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore,
            contentDescription = if (expanded) "Collapse" else "Show sets",
            tint = NeonMV.Muted, modifier = Modifier.padding(start = 6.dp).size(20.dp),
        )
    }
}

/** An exercise still to come: compact, tap to make it the hero. */
@Composable
private fun UpNextRow(
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    label: String,
    onFocus: () -> Unit,
) {
    val timed = isTimedExercise(wex, info)
    val prescription = buildString {
        append("${wex.targetSets}×")
        append(repsRange(wex.targetRepsLow, wex.targetRepsHigh))
        if (timed) append("s")
        wex.targetWeightLb?.let { append(" · ${fmtLbPlain(it)} lb") }
    }
    val accounted = accountedSets(wex)
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clip(RowShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, RowShape)
            .clickable(onClick = onFocus)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(prescription, color = NeonMV.Muted, fontSize = 12.sp)
                if (wex.supersetId != null) {
                    Text("  ·  superset ${wex.supersetId}", color = NeonMV.Magenta, fontSize = 12.sp)
                }
            }
        }
        if (accounted > 0) {
            Text("$accounted/${wex.targetSets}", color = NeonMV.Cyan, fontSize = 12.sp,
                fontFamily = NeonNumberFamily, fontWeight = FontWeight.Bold)
        }
        Icon(Icons.Outlined.ChevronRight, contentDescription = "Log this next",
            tint = NeonMV.Muted, modifier = Modifier.padding(start = 4.dp).size(20.dp))
    }
}

/** Dialogs and sheets owned by the screen. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun WorkoutDialogsAndSheets(
    st: StrengthTodayState,
    actions: StrengthTodayActions,
    coach: CoachCardState,
    coachSheetBody: @Composable () -> Unit,
    onFinishRequested: () -> Unit,
) {
    val plan = st.workout
    val catalog = st.catalog

    if (st.confirmSkipNames.isNotEmpty()) {
        val n = st.confirmSkipNames.size
        val names = st.confirmSkipNames.joinToString(", ")
        // Copy is canonical and shared verbatim with StrengthToday.vue.
        NeonAlertDialog(
            onDismissRequest = { st.confirmSkipNames = emptyList() },
            title = if (n == 1) "Finish with unlogged exercise?"
                else "Finish with unlogged exercises?",
            confirmLabel = if (st.finishing) "Finishing…" else "Finish workout",
            confirmEnabled = !st.finishing,
            onConfirm = {
                st.confirmSkipNames = emptyList()
                actions.finish(true)
            },
            // "Go back" does NOT set completeDialogDismissed — that would
            // silence the separate auto prompt, which nobody asked for.
            dismissLabel = "Go back",
        ) {
            Text(
                if (n == 1) "1 exercise unlogged: $names. Mark it skipped and finish?"
                else "$n exercises unlogged: $names. Mark them skipped and finish?",
            )
        }
    }

    if (st.showCompleteDialog && plan != null) {
        NeonAlertDialog(
            onDismissRequest = {
                st.showCompleteDialog = false
                st.completeDialogDismissed = true
            },
            title = "Workout complete?",
            confirmLabel = "Finish workout",
            onConfirm = {
                st.showCompleteDialog = false
                onFinishRequested()
            },
            dismissLabel = "Keep going",
        ) {
            Text(
                "All ${plan.setsTotal} prescribed sets accounted for. Finish and stamp " +
                    "the session, or keep going if you want to add bonus work.",
            )
        }
    }

    if (st.showCardioLog && plan != null) {
        CardioLogDialog(
            defaultLabel = "Les Mills VR",
            defaultDurationMin = 30,
            submitting = st.cardioLogging,
            onDismiss = { if (!st.cardioLogging) st.showCardioLog = false },
            onSubmit = { label, type, durationMin, endedAt ->
                actions.submitCardio(label, type, durationMin, endedAt)
            },
        )
    }

    // Banner chips → their content, in a sheet.
    val sheet = st.openSheet
    if (sheet != null && plan != null) {
        ModalBottomSheet(
            onDismissRequest = { st.openSheet = null },
            containerColor = NeonMV.CardHigh,
        ) {
            BannerSheetBody(
                key = sheet, plan = plan, actions = actions,
                coachSheetBody = coachSheetBody,
                close = { st.openSheet = null },
            )
        }
    }

    // Swap sheet
    if (st.swapWexId != null && plan != null) {
        val wex = plan.exercises.firstOrNull { it.id == st.swapWexId }
        val current = wex?.let { catalog[it.exerciseId] }
        if (wex != null && current != null) {
            val inWorkout = plan.exercises.map { it.exerciseId }.toSet()
            val alternatives = catalog.values
                .filter {
                    it.id != wex.exerciseId &&
                        it.id !in inWorkout &&
                        (it.primaryMuscle == current.primaryMuscle ||
                            it.movementPattern == current.movementPattern)
                }
                .sortedWith(compareBy(
                    { if (it.movementPattern == current.movementPattern) 0 else 1 },
                    { it.name },
                ))
                .take(12)
            ModalBottomSheet(
                onDismissRequest = { st.swapWexId = null },
                containerColor = NeonMV.CardHigh,
            ) {
                Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                    Text("Swap exercise", color = NeonMV.Ink, fontSize = 18.sp,
                        fontWeight = FontWeight.Bold)
                    Text("Currently: ${current.name}", color = NeonMV.Muted, fontSize = 13.sp,
                        modifier = Modifier.padding(top = 2.dp, bottom = 10.dp))
                    if (alternatives.isEmpty()) {
                        Text("No alternatives in your equipment for this slot.",
                            color = NeonMV.Muted, fontSize = 13.sp)
                    } else {
                        alternatives.forEach { alt ->
                            PickRow(alt, enabled = !st.swapping) { actions.swapTo(wex.id, alt.id) }
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }

    // Add-exercise sheet (TD-10)
    if (st.addSheetOpen && plan != null) {
        val inWorkout = plan.exercises.map { it.exerciseId }.toSet()
        val q = st.addQuery.trim().lowercase()
        val candidates = catalog.values
            .filter { it.id !in inWorkout }
            .filter {
                q.isEmpty() ||
                    it.name.lowercase().contains(q) ||
                    it.primaryMuscle.lowercase().contains(q)
            }
            .sortedBy { it.name }
            .take(20)
        ModalBottomSheet(
            onDismissRequest = { st.addSheetOpen = false },
            containerColor = NeonMV.CardHigh,
        ) {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                Text("Add exercise", color = NeonMV.Ink, fontSize = 18.sp,
                    fontWeight = FontWeight.Bold)
                Text(
                    "The weight comes from your history, the same way the planner " +
                        "does it — you pick the movement.",
                    color = NeonMV.Muted, fontSize = 13.sp,
                    modifier = Modifier.padding(top = 2.dp, bottom = 10.dp),
                )
                OutlinedTextField(
                    value = st.addQuery,
                    onValueChange = { st.addQuery = it },
                    singleLine = true,
                    label = { Text("Search by name or muscle") },
                    colors = neonFieldColors(),
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                )
                if (candidates.isEmpty()) {
                    Text(
                        "Nothing matches — every exercise in your equipment is " +
                            "either already in today's session or filtered out.",
                        color = NeonMV.Muted, fontSize = 13.sp,
                    )
                } else {
                    candidates.forEach { alt ->
                        PickRow(alt, enabled = !st.adding) { actions.addExercise(alt.id) }
                    }
                }
                Spacer(Modifier.height(16.dp))
            }
        }
    }

    if (st.customSheetOpen) {
        CustomWorkoutSheet(
            generating = st.customGenerating,
            onDismiss = { st.customSheetOpen = false },
            onGenerate = { type, durationMin, difficulty ->
                actions.customGenerate(type, durationMin, difficulty)
            },
        )
    }
}

@Composable
private fun PickRow(alt: StrengthExerciseInfo, enabled: Boolean, onPick: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .clip(RowShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, RowShape)
            .clickable(enabled = enabled, onClick = onPick)
            .heightIn(min = 56.dp)
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Text(alt.name, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
        Text(
            "${alt.movementPattern.replace('_', ' ')} · ${alt.primaryMuscle}",
            color = NeonMV.Muted, fontSize = 12.sp,
        )
    }
}
