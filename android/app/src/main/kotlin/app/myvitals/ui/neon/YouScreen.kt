package app.myvitals.ui.neon

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForwardIos
import androidx.compose.material.icons.outlined.EditNote
import androidx.compose.material.icons.outlined.HourglassEmpty
import androidx.compose.material.icons.outlined.LocalFireDepartment
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.Icon
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.AiGoal
import app.myvitals.sync.FastingSession
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.SoberCurrentResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import timber.log.Timber
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.floor
import kotlin.math.roundToInt

/**
 * You — neon personal hub. Mirrors web `You.vue`: a fasting habit card (cyan
 * ring) + a sober habit card (magenta flame), a goals progress strip from
 * aiGoals(), a profile summary line from profile(), and a column of quick-link
 * pills that drill into Journal / Settings / Sober / Fasting / Coach.
 *
 * Server is source of truth: everything renders from /fasting/current,
 * /sober/current, /ai/goals, /profile and /summary/today via BackendClient.
 *
 * onOpen routes used: "settings", "sober", "fasting", "journal", "coach".
 */
@Composable
fun YouScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    var fasting by remember { mutableStateOf<FastingSession?>(null) }
    var sober by remember { mutableStateOf<SoberCurrentResponse?>(null) }
    var goals by remember { mutableStateOf<List<AiGoal>>(emptyList()) }
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) { loading = false; return@LaunchedEffect }
        runCatching {
            val api = app.myvitals.sync.BackendClient.create(
                settings.backendUrl, settings.bearerToken,
            )
            coroutineScope {
                val fastingD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.fastingCurrent()
                        if (r.isSuccessful) r.body() else null
                    }.getOrNull()
                }
                val soberD = async(Dispatchers.IO) {
                    runCatching { api.soberCurrent() }.getOrNull()
                }
                val goalsD = async(Dispatchers.IO) {
                    runCatching { api.aiGoals(activeOnly = true) }.getOrDefault(emptyList())
                }
                val profileD = async(Dispatchers.IO) {
                    runCatching { api.profile() }.getOrNull()
                }
                fasting = fastingD.await()
                sober = soberD.await()
                goals = goalsD.await()
                profile = profileD.await()
            }
        }.onFailure { Timber.w(it, "you-screen load failed") }
        loading = false
    }

    val todayLabel = remember {
        runCatching {
            LocalDate.now().format(DateTimeFormatter.ofPattern("EEE, MMM d"))
        }.getOrDefault("")
    }

    NeonScreen(
        title = "You",
        contentPadding = contentPadding,
        headerTrailing = {
            if (todayLabel.isNotEmpty()) {
                Text(
                    todayLabel,
                    color = NeonMV.Muted,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        },
    ) {
        // ── Profile summary line ──────────────────────────────────
        ProfileSummary(profile)
        Spacer(Modifier.height(14.dp))

        // ── Habits: Fasting (cyan ring) + Sober (magenta flame) ────
        SectionCap("Habits")
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            FastingCard(
                fasting = fasting,
                loading = loading,
                modifier = Modifier.weight(1f),
                onClick = { onOpen("fasting") },
            )
            SoberCard(
                sober = sober,
                loading = loading,
                modifier = Modifier.weight(1f),
                onClick = { onOpen("sober") },
            )
        }
        Spacer(Modifier.height(16.dp))

        // ── Goals progress strip ──────────────────────────────────
        GoalsCard(goals = goals, loading = loading)
        Spacer(Modifier.height(16.dp))

        // ── Personal & system quick links ─────────────────────────
        SectionCap("Personal & system")
        Spacer(Modifier.height(8.dp))
        LinkPill(
            icon = Icons.Outlined.EditNote, tint = NeonMV.Magenta,
            title = "Journal", subtitle = "Notes & reflections",
            onClick = { onOpen("journal") },
        )
        Spacer(Modifier.height(8.dp))
        LinkPill(
            icon = Icons.Outlined.Timer, tint = NeonMV.Magenta,
            title = "Sober time", subtitle = "Streak & history",
            onClick = { onOpen("sober") },
        )
        Spacer(Modifier.height(8.dp))
        LinkPill(
            icon = Icons.Outlined.HourglassEmpty, tint = NeonMV.Cyan,
            title = "Fasting", subtitle = "Protocol & stages",
            onClick = { onOpen("fasting") },
        )
        Spacer(Modifier.height(8.dp))
        LinkPill(
            icon = Icons.Outlined.Settings, tint = NeonMV.Amber,
            title = "Settings", subtitle = "Profile · integrations · about",
            onClick = { onOpen("settings") },
        )

        Spacer(Modifier.height(24.dp))
    }
}

// ============================================================
// Profile summary
// ============================================================

@Composable
private fun ProfileSummary(profile: ProfileResponse?) {
    val parts = remember(profile) {
        buildList {
            profile?.derived?.age?.let { add("$it yrs") }
            profile?.sex?.takeIf { it.isNotBlank() }
                ?.let { add(it.replaceFirstChar { c -> c.titlecase() }) }
            profile?.heightCm?.let {
                val totalIn = (it / 2.54).roundToInt()
                add("${totalIn / 12}'${totalIn % 12}\"")
            }
            profile?.activityLevel?.takeIf { it.isNotBlank() }
                ?.let { add(it.replace("_", " ")) }
        }
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(RoundedCornerShape(50))
                .background(NeonMV.Cyan.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Outlined.Person, contentDescription = null,
                tint = NeonMV.Cyan, modifier = Modifier.size(22.dp),
            )
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                "Your profile", color = NeonMV.Ink,
                fontSize = 15.sp, fontWeight = FontWeight.Bold,
            )
            Text(
                if (parts.isEmpty()) "Add your details in Settings"
                else parts.joinToString(" · "),
                color = NeonMV.Muted, fontSize = 12.sp,
            )
        }
    }
}

// ============================================================
// Habit cards
// ============================================================

@Composable
private fun FastingCard(
    fasting: FastingSession?,
    loading: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val accent = NeonMV.Cyan
    val active = fasting?.isActive == true
    val elapsedH = fasting?.elapsedH ?: 0.0
    val target = fasting?.targetHours ?: 16.0
    val pct = if (active) (elapsedH / target).coerceIn(0.0, 1.0) else 0.0
    val complete = active && elapsedH >= target

    HabitCard(
        label = "Fasting",
        accent = accent,
        modifier = modifier,
        onClick = onClick,
    ) {
        Box(
            modifier = Modifier.size(74.dp),
            contentAlignment = Alignment.Center,
        ) {
            androidx.compose.foundation.Canvas(Modifier.size(74.dp)) {
                val stroke = androidx.compose.ui.graphics.drawscope.Stroke(
                    width = 8.dp.toPx(),
                    cap = androidx.compose.ui.graphics.StrokeCap.Round,
                )
                val pad = stroke.width / 2f
                val arcSize = androidx.compose.ui.geometry.Size(
                    size.width - pad * 2, size.height - pad * 2,
                )
                val topLeft = androidx.compose.ui.geometry.Offset(pad, pad)
                drawArc(
                    color = NeonMV.Track,
                    startAngle = 0f, sweepAngle = 360f, useCenter = false,
                    topLeft = topLeft, size = arcSize, style = stroke,
                )
                if (pct > 0.0) {
                    drawArc(
                        color = accent,
                        startAngle = -90f,
                        sweepAngle = (360.0 * pct).toFloat(),
                        useCenter = false,
                        topLeft = topLeft, size = arcSize, style = stroke,
                    )
                }
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                val big = when {
                    !active -> "—"
                    else -> "${floor(elapsedH).toInt()}:${target.roundToInt()}"
                }
                NeonNumber(big, color = accent, size = 18)
                Text("hours", color = NeonMV.Muted, fontSize = 9.sp)
            }
        }
        Spacer(Modifier.height(8.dp))
        val tag = when {
            loading && fasting == null -> "…"
            !active -> "Not fasting"
            complete -> "Complete ✓"
            else -> "${floor(elapsedH).toInt()} / ${target.roundToInt()}h"
        }
        HabitTag(tag, accent)
    }
}

@Composable
private fun SoberCard(
    sober: SoberCurrentResponse?,
    loading: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val accent = NeonMV.Magenta
    val days = sober?.days
    HabitCard(
        label = "Sober",
        accent = accent,
        modifier = modifier,
        onClick = onClick,
    ) {
        Icon(
            Icons.Outlined.LocalFireDepartment,
            contentDescription = null,
            tint = accent,
            modifier = Modifier.size(38.dp).padding(top = 4.dp, bottom = 2.dp),
        )
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            NeonNumber(days?.toString() ?: "—", color = accent, size = 26)
            Spacer(Modifier.width(4.dp))
            Text(
                if (days == 1) "day" else "days",
                color = NeonMV.Muted, fontSize = 12.sp,
                modifier = Modifier.padding(bottom = 3.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        val tag = when {
            loading && sober == null -> "…"
            sober?.active != null -> "Active streak"
            else -> "Tap to start"
        }
        HabitTag(tag, accent)
    }
}

@Composable
private fun HabitCard(
    label: String,
    accent: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, accent.copy(alpha = 0.22f), NeonCardShape)
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            label.uppercase(),
            color = accent,
            fontFamily = NeonNumberFamily,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.sp,
        )
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
private fun HabitTag(text: String, accent: Color) {
    Box(
        modifier = Modifier
            .clip(NeonPillShape)
            .background(accent.copy(alpha = 0.14f))
            .padding(horizontal = 11.dp, vertical = 4.dp),
    ) {
        Text(
            text, color = accent,
            fontSize = 11.sp, fontWeight = FontWeight.Bold,
        )
    }
}

// ============================================================
// Goals card
// ============================================================

@Composable
private fun GoalsCard(goals: List<AiGoal>, loading: Boolean) {
    val top = goals.take(3)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        Text(
            "GOALS",
            color = NeonMV.Muted,
            fontFamily = NeonNumberFamily,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.5.sp,
        )
        Spacer(Modifier.height(10.dp))
        when {
            top.isNotEmpty() -> {
                top.forEachIndexed { i, g ->
                    GoalRow(g, GOAL_ACCENTS[i % GOAL_ACCENTS.size])
                    if (i < top.lastIndex) Spacer(Modifier.height(12.dp))
                }
            }
            loading -> Text("Loading goals…", color = NeonMV.Muted, fontSize = 13.sp)
            else -> Text("No active goals yet", color = NeonMV.Muted, fontSize = 13.sp)
        }
    }
}

private val GOAL_ACCENTS = listOf(NeonMV.Cyan, NeonMV.Magenta, NeonMV.Lime)

@Composable
private fun GoalRow(g: AiGoal, accent: Color) {
    // Server-computed progress is the source of truth; fall back to a
    // current/target ratio only when progress_pct is absent.
    val pct: Float? = when {
        g.progressPct != null -> (g.progressPct / 100.0).toFloat().coerceIn(0f, 1f)
        g.currentValue != null && g.targetValue != null && g.targetValue != 0.0 ->
            (g.currentValue / g.targetValue).toFloat().coerceIn(0f, 1f)
        else -> null
    }
    val valueText: String = when {
        g.currentValue != null && g.targetValue != null ->
            "${trimNum(g.currentValue)} / ${trimNum(g.targetValue)}" +
                (g.targetUnit?.let { " $it" } ?: "")
        g.targetValue != null ->
            trimNum(g.targetValue) + (g.targetUnit?.let { " $it" } ?: "")
        else -> "Active"
    }
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom,
        ) {
            Text(
                g.title, color = NeonMV.Ink,
                fontSize = 14.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                valueText,
                color = if (pct != null) accent else NeonMV.Muted,
                fontFamily = NeonNumberFamily,
                fontSize = 13.sp, fontWeight = FontWeight.Bold,
            )
        }
        if (pct != null) {
            Spacer(Modifier.height(6.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .clip(RoundedCornerShape(7.dp))
                    .background(NeonMV.Track),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(pct)
                        .height(7.dp)
                        .clip(RoundedCornerShape(7.dp))
                        .background(
                            Brush.horizontalGradient(
                                listOf(accent, accent.copy(alpha = 0.75f)),
                            ),
                        ),
                )
            }
        }
    }
}

private fun trimNum(v: Double): String =
    if (v == floor(v)) v.toLong().toString() else "%.1f".format(v)

// ============================================================
// Quick-link pills
// ============================================================

@Composable
private fun LinkPill(
    icon: ImageVector,
    tint: Color,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonPillShape)
            .background(NeonMV.Card)
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .clip(RoundedCornerShape(50))
                .background(tint.copy(alpha = 0.14f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(18.dp))
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = NeonMV.Ink, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text(subtitle, color = NeonMV.Muted, fontSize = 11.5.sp)
        }
        Icon(
            Icons.AutoMirrored.Outlined.ArrowForwardIos,
            contentDescription = "Open",
            tint = NeonMV.Muted,
            modifier = Modifier.size(13.dp),
        )
    }
}

// ============================================================
// Helpers
// ============================================================

@Composable
private fun SectionCap(text: String) {
    Text(
        text.uppercase(),
        color = NeonMV.Muted,
        fontFamily = NeonNumberFamily,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.5.sp,
    )
}
