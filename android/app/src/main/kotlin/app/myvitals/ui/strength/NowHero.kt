package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowDropDown
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.HourglassBottom
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Spa
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.sync.StrengthWorkoutDetail
import app.myvitals.sync.StrengthWorkoutExerciseRow
import app.myvitals.ui.common.ShimmerBlock
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonHeroCard
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import app.myvitals.ui.neon.NeonNumberFamily
import app.myvitals.ui.neon.NeonRing
import app.myvitals.ui.neon.NeonRingCaption
import app.myvitals.ui.neon.NeonStatTile

/*
 * UI-2 — the "Now" hero of the active-workout screen.
 *
 * The set you are about to do used to live inside the Nth card of a list,
 * below the Coach card and up to four same-weight banners, so the screen had
 * no focal point. The hero is pinned under the title and carries exactly one
 * thing: what to do next, with the controls to log it. The rest timer lives
 * in it too (it was a separate 76dp bar), and when nothing is left it turns
 * into the finish prompt, then into the session summary.
 *
 * Every number it shows is the server's: prefill from planned_sets (TD-6),
 * progress from the SKIP-1 counters, the summary from TD-4's session_summary.
 */

private val HeroButtonShape = RoundedCornerShape(14.dp)

/** Picks the hero for the session's state. */
@Composable
internal fun NowHeroArea(
    st: StrengthTodayState,
    plan: StrengthWorkoutDetail,
    heroWex: StrengthWorkoutExerciseRow?,
    info: StrengthExerciseInfo?,
    actions: StrengthTodayActions,
    onFinish: () -> Unit,
    onCardioLog: () -> Unit,
) {
    when {
        plan.status == "completed" -> CompletedHero(
            plan = plan,
            history = st.history,
            onRedo = { actions.regenerate(true) },
        )
        plan.status == "skipped" -> SkippedHero(deferring = st.deferring, onUndo = actions.unskipDay)
        plan.exercises.isEmpty() -> PrescriptionHero(
            plan = plan,
            finishing = st.finishing,
            onLog = {
                val isCardioDay = plan.splitFocus in listOf("cardio", "active_recovery", "yoga")
                if (isCardioDay) onCardioLog() else onFinish()
            },
            onResume = actions.resume,
        )
        plan.status == "paused" -> PausedHero(plan, heroWex, info, onResume = actions.resume)
        heroWex == null -> FinishHero(
            plan = plan,
            finishing = st.finishing,
            onFinish = onFinish,
            onAdd = { st.addSheetOpen = true },
        )
        else -> NowHero(st, plan, heroWex, info, actions)
    }
}

@Composable
private fun HeroEyebrow(text: String, color: Color = NeonMV.Muted, trailing: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text.uppercase(),
            color = color,
            fontFamily = NeonNumberFamily,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.4.sp,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        trailing()
    }
}

@Composable
private fun HeroTitle(text: String) {
    Text(
        text,
        color = NeonMV.Ink,
        fontSize = 22.sp,
        fontWeight = FontWeight.ExtraBold,
        letterSpacing = (-0.3).sp,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier.padding(top = 2.dp),
    )
}

@Composable
private fun HeroButton(
    label: String,
    color: Color,
    onClick: () -> Unit,
    enabled: Boolean = true,
    icon: ImageVector? = null,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        shape = HeroButtonShape,
        modifier = Modifier.fillMaxWidth().height(48.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = color,
            contentColor = NeonMV.OnAccent,
            disabledContainerColor = NeonMV.Track,
            disabledContentColor = NeonMV.Muted,
        ),
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
        }
        Text(label, fontWeight = FontWeight.Bold, fontSize = 15.sp)
    }
}

// ── The NOW set ──────────────────────────────────────────────────────────

@Composable
private fun NowHero(
    st: StrengthTodayState,
    plan: StrengthWorkoutDetail,
    wex: StrengthWorkoutExerciseRow,
    info: StrengthExerciseInfo?,
    actions: StrengthTodayActions,
) {
    val n = nextSetOf(wex) ?: return
    val key = "${wex.id}-$n"
    val timed = isTimedExercise(wex, info)
    // Read, never getOrPut: writing the map during composition re-triggers
    // it. The seed is the server's prefill, the same the table used to show.
    val input = st.setInputs[key] ?: seedInput(wex, n)
    val side = bilateralSideLabel(n, wex.targetSets, info)
    val planned = wex.plannedSets.firstOrNull { it.setNumber == n }
    val sorted = plan.exercises.sortedBy { it.orderIndex }
    val pos = sorted.indexOfFirst { it.id == wex.id } + 1
    val total = plan.exercisesTotal.takeIf { it > 0 } ?: plan.exercises.size
    val name = info?.name ?: wex.exerciseId.replace('_', ' ')
    val repsTarget = if (planned?.isAmrap == true) "${wex.targetRepsLow}+ (AMRAP)"
        else repsRange(wex.targetRepsLow, wex.targetRepsHigh)
    // OG3-B3: "per side" is the server's words, not ours.
    val perSide = planned?.takeIf { it.perSide }?.sideLabel
    val targetW = planned?.targetWeightLb ?: wex.targetWeightLb
    var editOpen by remember(key) { mutableStateOf(false) }

    NeonHeroCard(accent = NeonMV.Cyan) {
        HeroEyebrow("Now · exercise $pos of $total", color = NeonMV.Cyan) {
            if (wex.supersetId != null) {
                Text(
                    "SUPERSET ${wex.supersetId}",
                    color = NeonMV.Magenta, fontSize = 10.sp,
                    fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
                    modifier = Modifier.padding(end = 6.dp),
                )
            }
            // SETTYPE-1: a warm-up logged as "working" enters the volume
            // audit and seeds next session's load. Same three the web offers.
            if (!timed) {
                SetTypePill(input.setType) { st.setInputs[key] = input.copy(setType = it) }
            }
        }
        HeroTitle(name)
        val setLine = buildString {
            if (side != null) append(if (side == "R") "Right side · " else "Left side · ")
            append("Set $n of ${wex.targetSets}")
            if (timed) {
                append(" · ${wex.targetRepsLow}s hold")
            } else {
                append(" · target ")
                if (targetW != null) append("${fmtLbPlain(targetW)} lb × ")
                append(repsTarget)
                if (perSide != null) append(" $perSide")
            }
        }
        Text(setLine, color = NeonMV.Muted, fontSize = 13.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(10.dp))

        val resting = st.restTotal > 0L && st.restRemainingS > 0L
        if (timed) {
            if (resting) {
                RestRingRow(st, nextLabel = "${wex.targetRepsLow}s hold")
                Spacer(Modifier.height(10.dp))
            }
            // The countdown, its full-screen overlay and the Easy/Good/Failed
            // prompt are the existing TimedSetRow, unchanged — keyed per set
            // so a finished hold cannot leak its state into the next one.
            key(key) {
                TimedSetRow(
                    n = n, holdSeconds = wex.targetRepsLow,
                    exerciseName = name,
                    sideLabel = side,
                    onComplete = { elapsed, rating ->
                        actions.logSet(wex, n, null, elapsed, rating, "working")
                        st.setInputs.remove(key)
                    },
                    hero = true,
                )
            }
            return@NeonHeroCard
        }

        if (resting) {
            RestRingRow(st, nextLabel = "${input.weight.ifBlank { "BW" }} lb × ${input.reps}")
        } else {
            TargetReadout(input.weight, input.reps, onTap = { editOpen = true })
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                val ladder = wex.loadLadderLb?.takeIf { it.isNotEmpty() }
                // Bodyweight slot (no target, no ladder): no weight stepper —
                // the readout still takes a typed weight for a loaded variant.
                if (ladder != null || targetW != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        val down = nextWeight(input.weight, targetW, ladder, up = false)
                        val up = nextWeight(input.weight, targetW, ladder, up = true)
                        StepPill(
                            if (ladder == null) "−2.5" else down?.let { "↓${fmtLbPlain(it)}" } ?: "↓—",
                            down?.let { "Lighter: ${fmtLbPlain(it)} pounds" } ?: "No lighter load",
                        ) { if (down != null) st.setInputs[key] = input.copy(weight = fmtLbPlain(down)) }
                        StepPill(
                            if (ladder == null) "+2.5" else up?.let { "↑${fmtLbPlain(it)}" } ?: "↑—",
                            up?.let { "Heavier: ${fmtLbPlain(it)} pounds" } ?: "No heavier load",
                        ) { if (up != null) st.setInputs[key] = input.copy(weight = fmtLbPlain(up)) }
                    }
                } else {
                    Spacer(Modifier.width(1.dp))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    StepPill("−1", "One fewer rep") {
                        val r = (input.reps.toIntOrNull() ?: wex.targetRepsLow) - 1
                        st.setInputs[key] = input.copy(reps = r.coerceAtLeast(0).toString())
                    }
                    StepPill("+1", "One more rep") {
                        val r = (input.reps.toIntOrNull() ?: wex.targetRepsLow) + 1
                        st.setInputs[key] = input.copy(reps = r.toString())
                    }
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        RatingChips(selected = input.rating) { st.setInputs[key] = input.copy(rating = it) }
        Spacer(Modifier.height(10.dp))
        HeroButton(
            label = "Log set $n",
            color = NeonMV.Cyan,
            icon = Icons.Outlined.Check,
            enabled = input.rating != null && input.reps.isNotBlank(),
            onClick = {
                actions.logSet(
                    wex, n, input.weight.toDoubleOrNull(), input.reps.toIntOrNull(),
                    input.rating, input.setType,
                )
                st.setInputs.remove(key)
            },
        )
    }

    if (editOpen) {
        NumberEntryDialog(
            weight = input.weight,
            reps = input.reps,
            onDismiss = { editOpen = false },
            onConfirm = { w, r ->
                st.setInputs[key] = input.copy(weight = w, reps = r)
                editOpen = false
            },
        )
    }
}

@Composable
private fun SetTypePill(value: String, onChange: (String) -> Unit) {
    val options = listOf("working" to "work", "warmup" to "warm-up", "drop" to "drop")
    var open by remember { mutableStateOf(false) }
    Box {
        Row(
            Modifier
                .heightIn(min = 32.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(NeonMV.Card)
                .border(1.dp, NeonMV.Line, RoundedCornerShape(16.dp))
                .clickable { open = true }
                .semantics { contentDescription = "Set type" }
                .padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(options.firstOrNull { it.first == value }?.second ?: value,
                color = NeonMV.Ink, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            Icon(Icons.Outlined.ArrowDropDown, null, tint = NeonMV.Muted, modifier = Modifier.size(16.dp))
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false },
            containerColor = NeonMV.CardHigh) {
            for ((k, label) in options) {
                DropdownMenuItem(
                    text = { Text(label, color = if (k == value) NeonMV.Cyan else NeonMV.Ink) },
                    onClick = { open = false; onChange(k) },
                )
            }
        }
    }
}

/** The weight one stepper tap moves to, from the typed value (or the target
 *  when the field is blank). UI-F4: walks the server's [ladder] of loads the
 *  user's gear can actually make — the next rung strictly above / below —
 *  and returns null when there is none in that direction. With no ladder (an
 *  older server) it falls back to a fixed 2.5 lb step, floored at zero. */
internal fun nextWeight(current: String, target: Double?, ladder: List<Double>?, up: Boolean): Double? {
    val base = current.toDoubleOrNull() ?: target
    if (ladder.isNullOrEmpty()) {
        return ((base ?: 0.0) + if (up) 2.5 else -2.5).coerceAtLeast(0.0)
    }
    if (base == null) return if (up) ladder.first() else null
    return if (up) ladder.firstOrNull { it > base + 0.01 }
    else ladder.lastOrNull { it < base - 0.01 }
}

/** "47.5 lb × 8" — tap to type. */
@Composable
private fun TargetReadout(weight: String, reps: String, onTap: () -> Unit) {
    val big = SpanStyle(fontSize = 40.sp, fontWeight = FontWeight.Bold, color = NeonMV.Ink)
    val small = SpanStyle(fontSize = 18.sp, fontWeight = FontWeight.Medium, color = NeonMV.Muted)
    Text(
        buildAnnotatedString {
            if (weight.isBlank()) {
                withStyle(big) { append("BW") }
            } else {
                withStyle(big) { append(weight) }
                withStyle(small) { append(" lb") }
            }
            withStyle(small) { append("  ×  ") }
            withStyle(big) { append(reps.ifBlank { "—" }) }
        },
        fontFamily = NeonNumberFamily,
        letterSpacing = (-0.5).sp,
        maxLines = 1,
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onTap)
            .semantics { contentDescription = "Weight $weight pounds, $reps reps. Tap to type." }
            .padding(vertical = 2.dp),
    )
}

@Composable
private fun StepPill(label: String, description: String, onClick: () -> Unit) {
    Box(
        Modifier
            .size(width = 62.dp, height = 40.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = NeonMV.Ink, fontFamily = NeonNumberFamily,
            fontSize = 15.sp, fontWeight = FontWeight.Bold)
    }
}

/** Fail / Hard / Good / Easy — WP-16 values 1 / 2 / 4 / 5. Nothing is
 *  pre-selected: the rating feeds next session's weight choice. */
@Composable
internal fun RatingChips(selected: Int?, onRate: (Int) -> Unit) {
    val pal = LocalStrengthPalette.current
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        for ((value, label) in listOf(1 to "Fail", 2 to "Hard", 4 to "Good", 5 to "Easy")) {
            val on = selected == value
            val color = ratingColor(value, pal)
            Box(
                Modifier
                    .weight(1f)
                    .height(40.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(if (on) color else color.copy(alpha = 0.08f))
                    .border(1.dp, if (on) color else color.copy(alpha = 0.40f), RoundedCornerShape(12.dp))
                    .clickable { onRate(value) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label, color = if (on) NeonMV.OnAccent else color,
                    fontWeight = FontWeight.Bold, fontSize = 13.sp)
            }
        }
    }
}

/** The rest timer, inside the hero: a depleting ring around mm:ss. */
@Composable
private fun RestRingRow(st: StrengthTodayState, nextLabel: String) {
    val remaining = st.restRemainingS
    val totalS = st.restTotal / 1000
    val frac = if (totalS > 0) remaining.toFloat() / totalS else 0f
    Row(verticalAlignment = Alignment.CenterVertically) {
        NeonRing(fraction = frac, color = NeonMV.Cyan, size = 96.dp, stroke = 8.dp) {
            NeonNumber(mmss(remaining), size = 22)
            NeonRingCaption("rest")
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text("Resting", color = NeonMV.Cyan, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text("of ${mmss(totalS)}", color = NeonMV.Muted, fontSize = 12.sp)
            Spacer(Modifier.height(4.dp))
            Text("Next: $nextLabel", color = NeonMV.Ink, fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            SmallPill("+30s") { st.restEndsAt += 30_000 }
            SmallPill("Skip") { st.restEndsAt = st.nowMs; st.restTotal = 0L }
        }
    }
}

internal fun mmss(s: Long): String = "${s / 60}:${(s % 60).toString().padStart(2, '0')}"

@Composable
private fun SmallPill(label: String, onClick: () -> Unit) {
    Box(
        Modifier
            .size(width = 64.dp, height = 40.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = NeonMV.Ink, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun NumberEntryDialog(
    weight: String,
    reps: String,
    onDismiss: () -> Unit,
    onConfirm: (String, String) -> Unit,
) {
    var w by remember { mutableStateOf(weight) }
    var r by remember { mutableStateOf(reps) }
    NeonAlertDialog(
        onDismissRequest = onDismiss,
        title = "Weight and reps",
        confirmLabel = "Use these",
        onConfirm = { onConfirm(w.trim(), r.trim()) },
        dismissLabel = "Cancel",
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(
                value = w, onValueChange = { w = it.take(6) },
                label = { Text("lb") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                colors = neonFieldColors(),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(
                value = r, onValueChange = { r = it.filter(Char::isDigit).take(3) },
                label = { Text("reps") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                colors = neonFieldColors(),
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
internal fun neonFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = NeonMV.Cyan,
    unfocusedBorderColor = NeonMV.Track,
    focusedLabelColor = NeonMV.Cyan,
    unfocusedLabelColor = NeonMV.Muted,
    focusedTextColor = NeonMV.Ink,
    unfocusedTextColor = NeonMV.Ink,
    cursorColor = NeonMV.Cyan,
)

/** The screen's dialogs, themed: CardHigh container, Lime confirm, Muted dismiss. */
@Composable
internal fun NeonAlertDialog(
    onDismissRequest: () -> Unit,
    title: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    confirmEnabled: Boolean = true,
    dismissLabel: String? = null,
    onDismiss: () -> Unit = onDismissRequest,
    text: @Composable () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismissRequest,
        containerColor = NeonMV.CardHigh,
        titleContentColor = NeonMV.Ink,
        textContentColor = NeonMV.Muted,
        shape = RoundedCornerShape(22.dp),
        title = { Text(title, fontWeight = FontWeight.Bold) },
        text = text,
        confirmButton = {
            TextButton(onClick = onConfirm, enabled = confirmEnabled) {
                Text(confirmLabel, color = if (confirmEnabled) NeonMV.Lime else NeonMV.Muted,
                    fontWeight = FontWeight.SemiBold)
            }
        },
        dismissButton = dismissLabel?.let { label ->
            { TextButton(onClick = onDismiss) { Text(label, color = NeonMV.Muted) } }
        },
    )
}

// ── Other hero states ────────────────────────────────────────────────────

@Composable
private fun PausedHero(
    plan: StrengthWorkoutDetail,
    wex: StrengthWorkoutExerciseRow?,
    info: StrengthExerciseInfo?,
    onResume: () -> Unit,
) {
    NeonHeroCard(accent = NeonMV.Cyan) {
        val sorted = plan.exercises.sortedBy { it.orderIndex }
        val pos = wex?.let { w -> sorted.indexOfFirst { it.id == w.id } + 1 }
        val total = plan.exercisesTotal.takeIf { it > 0 } ?: plan.exercises.size
        HeroEyebrow(if (pos != null) "Paused · exercise $pos of $total" else "Paused",
            color = NeonMV.Cyan)
        HeroTitle(wex?.let { info?.name ?: it.exerciseId.replace('_', ' ') } ?: "Workout paused")
        Text(
            "Resume to keep logging — time away won't count toward your session length.",
            color = NeonMV.Muted, fontSize = 13.sp, lineHeight = 18.sp,
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp),
        )
        HeroButton("Resume workout", NeonMV.Cyan, onResume)
    }
}

@Composable
private fun FinishHero(
    plan: StrengthWorkoutDetail,
    finishing: Boolean,
    onFinish: () -> Unit,
    onAdd: () -> Unit,
) {
    NeonHeroCard(accent = NeonMV.Lime) {
        HeroEyebrow("All sets done", color = NeonMV.Lime)
        HeroTitle("Finish the session")
        Text(
            "All ${plan.setsTotal} prescribed sets accounted for.",
            color = NeonMV.Muted, fontSize = 13.sp,
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp),
        )
        HeroButton(
            if (finishing) "Finishing…" else "Finish workout",
            NeonMV.Lime, onFinish, enabled = !finishing, icon = Icons.Outlined.Check,
        )
        TextButton(onClick = onAdd, modifier = Modifier.fillMaxWidth().heightIn(min = 44.dp)) {
            Text("Add exercise", color = NeonMV.Muted, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun CompletedHero(
    plan: StrengthWorkoutDetail,
    history: List<app.myvitals.sync.StrengthWorkoutSummary>,
    onRedo: () -> Unit,
) {
    // TD-4's summary, as the server computed it. A cached plan from before
    // the field reached this model falls back to the history row.
    val s = plan.sessionSummary ?: history.firstOrNull { it.id == plan.id }?.sessionSummary
    NeonHeroCard(accent = NeonMV.Lime) {
        HeroEyebrow("Workout complete", color = NeonMV.Lime) {
            // Replay: regenerate with force=true.
            TextButton(onClick = onRedo, modifier = Modifier.heightIn(min = 40.dp)) {
                Text("Redo", color = NeonMV.Muted, fontSize = 13.sp)
            }
        }
        HeroTitle(plan.splitFocus.replace('_', ' ').replaceFirstChar(Char::titlecase) + " — see you tomorrow")
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // Tonnage over bodyweight-only work is zero by arithmetic, not
            // by effort: say so rather than print a discouraging 0.
            val bodyweightOnly = s != null && s.totalVolumeLb <= 0.0 && s.workingSets > 0
            NeonStatTile(
                value = when {
                    s == null -> "—"
                    bodyweightOnly -> "BW"
                    else -> "%,d".format(Math.round(s.totalVolumeLb))
                },
                label = if (bodyweightOnly) "bodyweight" else "lb lifted",
                accent = NeonMV.Lime,
                modifier = Modifier.weight(1f),
            )
            NeonStatTile(
                value = s?.workingSets?.toString() ?: "—",
                label = "working sets",
                modifier = Modifier.weight(1f),
            )
            NeonStatTile(
                value = s?.netDurationS?.let { "${Math.round(it / 60.0)} min" } ?: "—",
                label = "duration",
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(10.dp))
        // SKIP-1 — what the session amounted to, straight from the counters.
        Text(
            "${plan.setsDone}/${plan.setsTotal} sets · " +
                "${plan.exercisesDone}/${plan.exercisesTotal} exercises",
            color = NeonMV.Muted, fontSize = 12.sp,
        )
    }
}

@Composable
private fun SkippedHero(deferring: Boolean, onUndo: () -> Unit) {
    NeonHeroCard(accent = NeonMV.Muted) {
        HeroEyebrow("Skipped")
        HeroTitle("Skipped today's workout day.")
        Text("Tomorrow will generate fresh.", color = NeonMV.Muted, fontSize = 13.sp,
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp))
        OutlinedButton(
            onClick = onUndo, enabled = !deferring, shape = HeroButtonShape,
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) { Text(if (deferring) "Restoring…" else "Undo", color = NeonMV.Ink) }
    }
}

/** Cardio / notes-only plans come back with exercises=[] and the
 *  prescription in `notes`. */
@Composable
private fun PrescriptionHero(
    plan: StrengthWorkoutDetail,
    finishing: Boolean,
    onLog: () -> Unit,
    onResume: () -> Unit,
) {
    val isCardioDay = plan.splitFocus in listOf("cardio", "active_recovery", "yoga")
    NeonHeroCard(accent = NeonMV.Lime) {
        HeroEyebrow("Today", color = NeonMV.Lime)
        HeroTitle(
            when (plan.splitFocus) {
                "cardio" -> "Cardio prescription"
                "yoga" -> "Mobility flow"
                "rest" -> "Rest day"
                else -> plan.splitFocus.replace('_', ' ').replaceFirstChar(Char::titlecase)
            },
        )
        plan.notes?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = NeonMV.Muted, fontSize = 13.sp, lineHeight = 18.sp,
                modifier = Modifier.padding(top = 4.dp))
        }
        Spacer(Modifier.height(12.dp))
        if (plan.status == "paused") {
            HeroButton("Resume workout", NeonMV.Cyan, onResume)
        } else {
            HeroButton(
                when {
                    isCardioDay -> "Log this workout"
                    finishing -> "Finishing…"
                    else -> "Complete workout"
                },
                NeonMV.Lime, onLog, enabled = !finishing,
            )
        }
    }
}

/** No plan today: rest-day advice, offline, or a first generate. Only
 *  reached when the load SUCCEEDED — a failed load renders a banner. */
@Composable
internal fun NoPlanHero(
    recoveryReason: String?,
    online: Boolean,
    generating: Boolean,
    onGenerate: (force: Boolean) -> Unit,
) {
    when {
        recoveryReason != null -> NeonHeroCard(accent = NeonMV.Amber) {
            HeroEyebrow("Rest day", color = NeonMV.Amber)
            HeroTitle("Rest day recommended")
            Text(recoveryReason, color = NeonMV.Muted, fontSize = 13.sp, lineHeight = 18.sp,
                modifier = Modifier.padding(top = 4.dp, bottom = 12.dp))
            OutlinedButton(
                onClick = { onGenerate(true) }, enabled = !generating, shape = HeroButtonShape,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) { Text(if (generating) "Generating…" else "Generate anyway", color = NeonMV.Ink) }
        }
        // Generating needs the backend (recovery context + RNG); the button
        // would just fail, so say why instead.
        !online -> NeonHeroCard(accent = NeonMV.Amber) {
            HeroEyebrow("Offline", color = NeonMV.Amber)
            HeroTitle("Workout not cached yet")
            Text(
                "Today's plan needs the server to generate (recovery + history). " +
                    "Reconnect and the workout will load. Logged sets from offline " +
                    "sessions will sync automatically.",
                color = NeonMV.Muted, fontSize = 13.sp, lineHeight = 18.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        else -> NeonHeroCard(accent = NeonMV.Cyan) {
            HeroEyebrow("No plan yet", color = NeonMV.Cyan)
            HeroTitle("Today's workout")
            Text("Built from your recovery, sleep and recent sessions.",
                color = NeonMV.Muted, fontSize = 13.sp,
                modifier = Modifier.padding(top = 4.dp, bottom = 12.dp))
            HeroButton(if (generating) "Generating…" else "Generate today's plan",
                NeonMV.Cyan, { onGenerate(false) }, enabled = !generating)
        }
    }
}

/** Loading: the hero's shape, shimmering, so the page does not jump. */
@Composable
internal fun WorkoutHeroSkeleton() {
    NeonHeroCard(accent = NeonMV.Cyan) {
        ShimmerBlock(width = 150.dp, height = 11.dp, accent = NeonMV.Cyan)
        Spacer(Modifier.height(8.dp))
        ShimmerBlock(Modifier.fillMaxWidth(0.7f), height = 24.dp, accent = NeonMV.Cyan)
        Spacer(Modifier.height(8.dp))
        ShimmerBlock(Modifier.fillMaxWidth(0.55f), height = 13.dp, accent = NeonMV.Cyan)
        Spacer(Modifier.height(14.dp))
        ShimmerBlock(Modifier.fillMaxWidth(0.6f), height = 44.dp, accent = NeonMV.Cyan)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            repeat(4) {
                ShimmerBlock(Modifier.weight(1f), height = 40.dp, cornerRadius = 12.dp, accent = NeonMV.Cyan)
            }
        }
        Spacer(Modifier.height(10.dp))
        ShimmerBlock(Modifier.fillMaxWidth(), height = 48.dp, cornerRadius = 14.dp, accent = NeonMV.Cyan)
    }
    // The list below, as three ghost rows.
    repeat(3) {
        ShimmerBlock(Modifier.fillMaxWidth().padding(bottom = 8.dp), height = 56.dp, cornerRadius = 14.dp)
    }
}

// ── Progress + chips ─────────────────────────────────────────────────────

/**
 * One segment per exercise, beside the server's set counter. The segment
 * states mirror the backend predicates (`accountedSets` / `isSlotSettled`
 * are the client copies of `_accounted_sets` / `_exercise_done`); the only
 * number printed is `sets_done/sets_total`, verbatim.
 */
@Composable
internal fun SegmentedProgress(plan: StrengthWorkoutDetail) {
    val done = plan.setsTotal > 0 && plan.setsDone >= plan.setsTotal
    Row(verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            for (wex in plan.exercises.sortedBy { it.orderIndex }) {
                val frac = if (wex.targetSets > 0) accountedSets(wex).toFloat() / wex.targetSets else 0f
                Box(
                    Modifier.weight(1f).height(8.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(NeonMV.Track),
                ) {
                    val fill = when {
                        wex.skipped -> NeonMV.Muted.copy(alpha = 0.35f)
                        isSlotSettled(wex) -> NeonMV.Lime
                        else -> NeonMV.Cyan
                    }
                    val f = if (wex.skipped || isSlotSettled(wex)) 1f else frac
                    if (f > 0f) Box(Modifier.fillMaxWidth(f).fillMaxHeight().background(fill))
                }
            }
        }
        Spacer(Modifier.width(10.dp))
        Text(
            "${plan.setsDone}/${plan.setsTotal} sets",
            color = if (done) NeonMV.Lime else NeonMV.Muted,
            fontFamily = NeonNumberFamily,
            fontSize = 12.sp, fontWeight = FontWeight.Bold,
        )
    }
}

internal data class BannerChip(
    val key: String, val label: String, val icon: ImageVector, val tint: Color,
)

/** Which chips a plan carries — same conditions the four banners had. */
internal fun bannerChips(plan: StrengthWorkoutDetail, coach: CoachCardState): List<BannerChip> {
    val open = plan.status == "planned" || plan.status == "in_progress"
    return buildList {
        if (open) {
            val sev = coach.deload?.severity?.takeIf { it != "none" }
            add(BannerChip("coach", if (sev != null) "Coach · deload $sev" else "Coach",
                Icons.Outlined.Psychology, if (sev != null) NeonMV.Amber else NeonMV.Magenta))
        }
        // FAST-18 — only past the 18h volume-modulation threshold.
        val f = plan.fastingContext
        if (f != null && f.active && f.modulation != "normal") {
            add(BannerChip("fasting", "Fasted ${f.currentHours.toInt()}h",
                Icons.Outlined.HourglassBottom, NeonMV.Amber))
        }
        if (plan.deloadFactor < 1.0 && open) {
            val pct = Math.round((1.0 - plan.deloadFactor) * 100).toInt()
            add(BannerChip("deload", "Load eased $pct%", Icons.Outlined.Spa, NeonMV.Cyan))
        }
        if (plan.status == "paused") {
            add(BannerChip("paused", "Paused", Icons.Outlined.PauseCircle, NeonMV.Cyan))
        }
        // OG2-D-2 — the generator's notes, behind a disclosure.
        if (plan.exercises.isNotEmpty() && !plan.notes.isNullOrBlank()) {
            val n = plan.notes.trim().lines().count { it.isNotBlank() }
            add(BannerChip("why", "Why this plan · $n", Icons.Outlined.Info, NeonMV.Muted))
        }
    }
}

@Composable
internal fun BannerChipStrip(
    plan: StrengthWorkoutDetail,
    coach: CoachCardState,
    onOpen: (String) -> Unit,
) {
    val chips = bannerChips(plan, coach)
    if (chips.isEmpty()) return
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (c in chips) {
            Row(
                Modifier
                    .heightIn(min = 36.dp)
                    .clip(RoundedCornerShape(18.dp))
                    .background(c.tint.copy(alpha = 0.12f))
                    .border(1.dp, c.tint.copy(alpha = 0.35f), RoundedCornerShape(18.dp))
                    .clickable { onOpen(c.key) }
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(c.icon, contentDescription = null, tint = c.tint, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text(c.label, color = if (c.tint == NeonMV.Muted) NeonMV.Ink else c.tint,
                    fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
            }
        }
    }
}

/** Finish / pause, one scroll away from anywhere in the session. */
@Composable
internal fun SessionActions(
    plan: StrengthWorkoutDetail,
    finishing: Boolean,
    onFinish: () -> Unit,
    onPause: () -> Unit,
    onResume: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().padding(top = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (plan.status == "paused") {
            OutlinedButton(
                onClick = onResume, shape = HeroButtonShape,
                modifier = Modifier.weight(1f).height(48.dp),
            ) { Text("Resume workout", color = NeonMV.Cyan) }
        } else {
            // WP-14 — Pause, for sessions already underway.
            if (plan.setsDone > 0 || plan.status == "in_progress") {
                OutlinedButton(
                    onClick = onPause, shape = HeroButtonShape,
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text("Pause", color = NeonMV.Ink) }
            }
            // SKIP-1: no "you haven't logged anything" gate — finishing a
            // session you walked away from is the flagship flow, and the
            // confirmation names what it will close.
            OutlinedButton(
                onClick = onFinish, enabled = !finishing, shape = HeroButtonShape,
                modifier = Modifier.weight(1f).height(48.dp),
            ) { Text(if (finishing) "Finishing…" else "Finish workout", color = NeonMV.Lime) }
        }
    }
}

/** A banner chip's content, as it was in the banner — same text, same action. */
@Composable
internal fun BannerSheetBody(
    key: String,
    plan: StrengthWorkoutDetail,
    actions: StrengthTodayActions,
    coachSheetBody: @Composable () -> Unit,
    close: () -> Unit,
) {
    val pal = LocalStrengthPalette.current
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
        when (key) {
            "coach" -> {
                SheetTitle("Coach")
                coachSheetBody()
            }
            "fasting" -> {
                val f = plan.fastingContext ?: return@Column
                SheetTitle("Fasted training")
                val hrs = f.currentHours.toInt()
                val stage = f.stage.replace('_', ' ')
                val body = if (f.modulation == "volume_-20%") {
                    "You're ${hrs}h fasted ($stage) — volume trimmed ~20%, rest +15s."
                } else {
                    "You're ${hrs}h fasted ($stage) — volume trimmed ~30%, rest +30s. " +
                        "A Z2 cardio block alongside is a strong option."
                }
                Text(body, color = pal.ink, fontSize = 14.sp, lineHeight = 20.sp)
            }
            "deload" -> {
                val pct = Math.round((1.0 - plan.deloadFactor) * 100).toInt()
                SheetTitle("Load eased ~${pct}% for recovery")
                Text(
                    (plan.deloadReason ?: "low recovery").replaceFirstChar { it.uppercase() } +
                        " — feeling strong?",
                    color = pal.muted, fontSize = 14.sp,
                )
                Spacer(Modifier.height(14.dp))
                HeroButton("Full weight", NeonMV.Cyan, { close(); actions.fullWeight() })
            }
            "paused" -> {
                SheetTitle("Workout paused")
                Text(
                    "Resume to keep logging — time away won't count toward your session length.",
                    color = pal.muted, fontSize = 14.sp, lineHeight = 20.sp,
                )
                Spacer(Modifier.height(14.dp))
                HeroButton("Resume", NeonMV.Cyan, { close(); actions.resume() })
            }
            "why" -> {
                SheetTitle("Why this plan")
                // One ROW per note: the generator produces a list.
                val lines = plan.notes.orEmpty().trim().lines().filter { it.isNotBlank() }
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (line in lines) {
                        Row {
                            Box(
                                Modifier.padding(top = 7.dp, end = 10.dp).size(5.dp)
                                    .clip(RoundedCornerShape(3.dp)).background(pal.muted),
                            )
                            Text(line, color = pal.ink, fontSize = 13.sp, lineHeight = 19.sp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SheetTitle(text: String) {
    Text(text, color = NeonMV.Ink, fontSize = 18.sp, fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(bottom = 10.dp))
}
