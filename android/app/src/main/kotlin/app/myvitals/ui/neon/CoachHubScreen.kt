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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForwardIos
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.FitnessCenter
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
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.CoachCard
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

/**
 * Coach — neon coaching hub. Mirrors web `CoachHub.vue`: a prominent
 * magenta "Open Coach" hero plus the latest *cached* coach headlines
 * (Workout / Recovery / Sleep) rendered as magenta-accented summary
 * cards.
 *
 * This screen NEVER triggers a paid POST generation — it only reads the
 * `/ai/coach/<kind>/latest` endpoints (cheap, cached). A 404 / null body
 * (no card generated yet) renders a quiet "tap to generate" placeholder.
 * Full generation + the rest of the coach surfaces live behind
 * [onOpen]("coach").
 */
@Composable
fun CoachHubScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    var workout by remember { mutableStateOf<CoachCard?>(null) }
    var recovery by remember { mutableStateOf<CoachCard?>(null) }
    var sleep by remember { mutableStateOf<CoachCard?>(null) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) { loading = false; return@LaunchedEffect }
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                // GET /latest only — bounded, no paid generation.
                val wD = async(Dispatchers.IO) {
                    runCatching { api.coachWorkoutLatest().takeIf { it.isSuccessful }?.body() }
                        .getOrNull()
                }
                val rD = async(Dispatchers.IO) {
                    runCatching { api.coachRecoveryLatest().takeIf { it.isSuccessful }?.body() }
                        .getOrNull()
                }
                val sD = async(Dispatchers.IO) {
                    runCatching { api.coachSleepLatest().takeIf { it.isSuccessful }?.body() }
                        .getOrNull()
                }
                workout = wD.await()
                recovery = rD.await()
                sleep = sD.await()
            }
        }
        loading = false
    }

    NeonScreen(title = "Coach", contentPadding = contentPadding) {
        // ── Open Coach hero — the prominent magenta CTA ──────────────
        OpenCoachCard(onClick = { onOpen("coach") })

        Spacer(Modifier.height(18.dp))

        SectionLabel("Latest read")

        if (loading) {
            ColdLoad()
        } else {
            CoachSummaryCard(
                icon = Icons.Outlined.FitnessCenter,
                label = "Workout",
                card = workout,
                onClick = { onOpen("coach") },
            )
            Spacer(Modifier.height(10.dp))
            CoachSummaryCard(
                icon = Icons.Outlined.FavoriteBorder,
                label = "Recovery",
                card = recovery,
                onClick = { onOpen("coach") },
            )
            Spacer(Modifier.height(10.dp))
            CoachSummaryCard(
                icon = Icons.Outlined.Bedtime,
                label = "Sleep",
                card = sleep,
                onClick = { onOpen("coach") },
            )
        }

        Spacer(Modifier.height(24.dp))
    }
}

/** Section eyebrow — Space Grotesk, uppercase, muted (matches web `.cap`). */
@Composable
private fun SectionLabel(text: String) {
    Text(
        text = text.uppercase(),
        color = NeonMV.Muted,
        fontFamily = NeonNumberFamily,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = 1.6.sp,
        modifier = Modifier.padding(bottom = 10.dp),
    )
}

/**
 * The hero CTA. Magenta gradient fill + magenta glow shadow, mirroring
 * the web `.hero` (magenta accent) and `.ask` send pill. Routes to the
 * full coach surface where paid generation lives.
 */
@Composable
private fun OpenCoachCard(onClick: () -> Unit) {
    // NOTE: no Modifier.shadow() — a colored elevation shadow on the obsidian
    // background renders as a dark halo/square behind the card. The gradient
    // fill + magenta border carry the "glow" instead.
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(
                Brush.linearGradient(
                    colors = listOf(
                        NeonMV.Magenta.copy(alpha = 0.28f),
                        NeonMV.Cyan.copy(alpha = 0.12f),
                    ),
                ),
            )
            .border(1.dp, NeonMV.Magenta.copy(alpha = 0.45f), NeonCardShape)
            .clickable { onClick() }
            .padding(18.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(NeonPillShape)
                    .background(NeonMV.Magenta.copy(alpha = 0.22f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Outlined.AutoAwesome,
                    contentDescription = null,
                    tint = NeonMV.Magenta,
                    modifier = Modifier.size(24.dp),
                )
            }
            Spacer(Modifier.size(14.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "ASK YOUR COACH",
                    color = NeonMV.Magenta,
                    fontFamily = NeonNumberFamily,
                    fontSize = 10.5.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 2.sp,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "Open Coach",
                    color = NeonMV.Ink,
                    fontSize = 19.sp,
                    fontWeight = FontWeight.ExtraBold,
                    letterSpacing = (-0.3).sp,
                )
                Spacer(Modifier.height(3.dp))
                Text(
                    "Workout · recovery · sleep · fasting reads, on tap.",
                    color = NeonMV.Ink.copy(alpha = 0.78f),
                    fontSize = 12.5.sp,
                    lineHeight = 17.sp,
                )
            }
            Spacer(Modifier.size(10.dp))
            Icon(
                Icons.AutoMirrored.Outlined.ArrowForwardIos,
                contentDescription = "Open Coach",
                tint = NeonMV.Magenta,
                modifier = Modifier.size(16.dp),
            )
        }
    }
}

/**
 * One coach domain's latest cached read. Renders the structured-output
 * `headline` + (where present) `recommendation`. Null card = no cached
 * generation yet → quiet placeholder. Tapping always routes to the full
 * coach surface (where generation happens) — this screen stays read-only.
 */
@Composable
private fun CoachSummaryCard(
    icon: ImageVector,
    label: String,
    card: CoachCard?,
    onClick: () -> Unit,
) {
    val analysis = card?.analysis
    val headline = (analysis?.get("headline") as? String)?.takeIf { it.isNotBlank() }
    val detail = listOf("recommendation", "what_to_change", "recommendation_text")
        .firstNotNullOfOrNull { (analysis?.get(it) as? String)?.takeIf { s -> s.isNotBlank() } }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Magenta.copy(alpha = 0.16f), NeonCardShape)
            .clickable { onClick() }
            .padding(16.dp),
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(30.dp)
                        .clip(NeonPillShape)
                        .background(NeonMV.Magenta.copy(alpha = 0.14f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        icon,
                        contentDescription = null,
                        tint = NeonMV.Magenta,
                        modifier = Modifier.size(17.dp),
                    )
                }
                Spacer(Modifier.size(10.dp))
                Text(
                    label.uppercase(),
                    color = NeonMV.Magenta,
                    fontFamily = NeonNumberFamily,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 1.4.sp,
                    modifier = Modifier.weight(1f),
                )
                if (card?.cached == true) {
                    Text(
                        "cached",
                        color = NeonMV.Muted,
                        fontSize = 9.5.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
            Spacer(Modifier.height(9.dp))
            Text(
                headline ?: "—",
                color = if (headline != null) NeonMV.Ink else NeonMV.Muted,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
                lineHeight = 20.sp,
            )
            if (headline != null && detail != null) {
                Spacer(Modifier.height(5.dp))
                Text(
                    detail,
                    color = NeonMV.Muted,
                    fontSize = 12.5.sp,
                    lineHeight = 17.sp,
                    maxLines = 2,
                )
            } else if (headline == null) {
                Spacer(Modifier.height(4.dp))
                Text(
                    "No read yet — tap to generate in Coach.",
                    color = NeonMV.Muted,
                    fontSize = 12.sp,
                    lineHeight = 16.sp,
                )
            }
        }
    }
}

/** Quiet cold-load placeholder — three dim surfaces, no spinner churn. */
@Composable
private fun ColdLoad() {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(3) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(78.dp)
                    .clip(NeonCardShape)
                    .background(NeonMV.Card.copy(alpha = 0.6f)),
                contentAlignment = Alignment.CenterStart,
            ) {
                Text(
                    "Loading…",
                    color = NeonMV.Muted,
                    fontSize = 12.sp,
                    modifier = Modifier.padding(start = 16.dp),
                )
            }
        }
    }
}
