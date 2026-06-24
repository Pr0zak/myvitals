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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.sync.ProfileResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import timber.log.Timber

/**
 * Body — consolidated vitals & recovery grid. Mirrors web `Body.vue`: a
 * 2-column grid of glanceable metric cards (heart rate, HRV, sleep, steps,
 * blood pressure, weight, skin temp) from /summary/today, plus a recovery
 * pill in the header. Each card drills into its detail screen via [onOpen].
 *
 * Domain colours are byte-identical to the web tokens: recovery / heart /
 * HRV / BP = cyan, sleep = magenta, steps = lime, weight = amber, skin
 * temp = muted. Skin temp has no phone detail screen (the `Vital` enum
 * stops at HR/HRV/SLEEP/STEPS/WEIGHT/BP) so its card is non-clickable.
 *
 * onOpen routes: "vitals/HR", "vitals/HRV", "vitals/SLEEP", "vitals/STEPS",
 * "vitals/BP", "vitals/WEIGHT".
 */
@Composable
fun BodyScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    val context = LocalContext.current
    var sum by remember { mutableStateOf<DailySummary?>(null) }
    var profile by remember { mutableStateOf<ProfileResponse?>(null) }
    // 14-day daily-summary window powering the inline sparklines on each card.
    var trend by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        // SWR: render the last-known summary instantly so cold/offline loads
        // don't paint a grid of blank "—" tiles. The fresh fetch below
        // overwrites once it lands. Keys mirror the other detail screens
        // (grep "JsonCache.write" to audit).
        runCatching {
            JsonCache.read<DailySummary>(context, BODY_SUMMARY_KEY, DailySummary::class.java)
                ?.let { sum = it.value; loading = false }
            JsonCache.read<ProfileResponse>(context, BODY_PROFILE_KEY, ProfileResponse::class.java)
                ?.let { profile = it.value }
        }

        if (!settings.isConfigured()) {
            loading = false
            return@LaunchedEffect
        }
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val sumD = async(Dispatchers.IO) {
                    runCatching { api.summaryToday() }.getOrNull()
                }
                val profileD = async(Dispatchers.IO) {
                    runCatching { api.profile() }.getOrNull()
                }
                val trendD = async(Dispatchers.IO) {
                    runCatching {
                        api.summaryRange(
                            since = java.time.LocalDate.now().minusDays(13).toString(),
                        )
                    }.getOrNull()
                }
                // Only swap in a fresh value — keep the cached render on a
                // failed/null fetch rather than blanking back to dashes.
                sumD.await()?.let {
                    sum = it
                    JsonCache.write(context, BODY_SUMMARY_KEY, DailySummary::class.java, it)
                }
                profileD.await()?.let {
                    profile = it
                    JsonCache.write(context, BODY_PROFILE_KEY, ProfileResponse::class.java, it)
                }
                trendD.await()?.let { trend = it }
            }
        }.onFailure { Timber.w(it, "body load failed") }
        loading = false
    }

    val recovery = sum?.recoveryScore
    val stepGoal = profile?.stepsGoal() ?: 10_000

    NeonScreen(
        title = "Body",
        contentPadding = contentPadding,
        headerTrailing = { RecoveryPill(recovery) { onOpen("vitals/HR") } },
    ) {
        Text(
            "Vitals & recovery · today",
            color = NeonMV.Muted,
            fontFamily = NeonNumberFamily,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.4.sp,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        // No data and not loading (cold/offline failure or a genuinely empty
        // day) — render a single hint card rather than a grid of blank "—"
        // tiles, which read as broken. SWR above means this only shows on a
        // truly cold cache; once a day has synced, the cached summary fills in.
        if (sum == null && !loading) {
            EmptyHintCard()
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }

        // ---- Row 1: Heart rate · HRV ----
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            MetricCard(
                modifier = Modifier.weight(1f),
                label = "Heart rate",
                value = fmt(sum?.restingHr),
                unit = "bpm",
                accent = NeonMV.Cyan,
                sub = "resting",
                loading = loading,
                onClick = { onOpen("vitals/HR") },
                spark = trend.map { it.restingHr?.toFloat() },
            )
            MetricCard(
                modifier = Modifier.weight(1f),
                label = "HRV",
                value = fmt(sum?.hrvAvg),
                unit = "ms",
                accent = NeonMV.Cyan,
                sub = "overnight avg",
                loading = loading,
                onClick = { onOpen("vitals/HRV") },
                spark = trend.map { it.hrvAvg?.toFloat() },
            )
        }

        Spacer(Modifier.height(12.dp))

        // ---- Row 2: Sleep · Steps ----
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            val sleepS = sum?.sleepDurationS
            val sleepH = sleepS?.let { it / 3600 }
            val sleepM = sleepS?.let { (it % 3600) / 60 }
            val score = sum?.sleepScore
            MetricCard(
                modifier = Modifier.weight(1f),
                label = "Sleep",
                value = if (sleepH != null) "${sleepH}h${sleepM ?: 0}m" else "—",
                unit = null,
                accent = NeonMV.Magenta,
                sub = if (score != null) "score ${fmt(score)}" else "no night",
                subColor = if (score != null) NeonMV.Magenta else NeonMV.Muted,
                loading = loading,
                onClick = { onOpen("vitals/SLEEP") },
                spark = trend.map { it.sleepDurationS?.toFloat() },
            )
            val steps = sum?.stepsTotal
            val stepsPct = steps?.let { Math.round(it.toFloat() / stepGoal * 100) }
            MetricCard(
                modifier = Modifier.weight(1f),
                label = "Steps",
                value = steps?.let { "%,d".format(it) } ?: "—",
                unit = null,
                accent = NeonMV.Lime,
                sub = if (stepsPct != null) "$stepsPct% of ${stepGoal / 1000}k" else "of ${stepGoal / 1000}k",
                subColor = if (stepsPct != null) NeonMV.Lime else NeonMV.Muted,
                loading = loading,
                onClick = { onOpen("vitals/STEPS") },
                spark = trend.map { it.stepsTotal?.toFloat() },
            )
        }

        Spacer(Modifier.height(12.dp))

        // ---- Row 3: Blood pressure (full width) ----
        BloodPressureCard(
            sys = sum?.bpSystolicAvg,
            dia = sum?.bpDiastolicAvg,
            loading = loading,
            onClick = { onOpen("vitals/BP") },
        )

        Spacer(Modifier.height(12.dp))

        // ---- Row 4: Weight · Skin temp (skin temp non-clickable) ----
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            val weightLb = sum?.weightKg?.let { it * 2.20462 }
            MetricCard(
                modifier = Modifier.weight(1f),
                label = "Weight",
                value = if (weightLb != null) "%.1f".format(weightLb) else "—",
                unit = "lb",
                accent = NeonMV.Amber,
                sub = "latest",
                loading = loading,
                onClick = { onOpen("vitals/WEIGHT") },
                spark = trend.map { it.weightKg?.toFloat()?.times(2.20462f) },
            )
            // Skin temp overnight delta vs baseline (signed). Same field the
            // web Body card shows; surfaced via DailySummary.skinTempDeltaAvg.
            // Non-clickable (no phone detail screen). Reads "—" when there's
            // genuinely no reading (e.g. the PW3/PW4 skin-temp firmware bug).
            val skinDelta = sum?.skinTempDeltaAvg
            MetricCard(
                modifier = Modifier.weight(1f),
                label = "Skin temp",
                value = skinDelta?.let { (if (it >= 0) "+" else "") + "%.1f".format(it) } ?: "—",
                unit = "°C",
                accent = NeonMV.Muted,
                sub = "vs baseline",
                loading = loading,
                onClick = null,
            )
        }

        Spacer(Modifier.height(24.dp))
    }
}

/** Cyan recovery pill in the header — drills to the HR detail (no RECOVERY vital). */
@Composable
private fun RecoveryPill(recovery: Double?, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .clip(NeonPillShape)
            .background(NeonMV.Cyan.copy(alpha = 0.10f))
            .border(1.dp, NeonMV.Cyan.copy(alpha = 0.32f), NeonPillShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 13.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(8.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(NeonMV.Cyan),
        )
        Spacer(Modifier.width(9.dp))
        Column {
            Text(
                "RECOVERY",
                color = NeonMV.Cyan,
                fontFamily = NeonNumberFamily,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.2.sp,
            )
            NeonNumber(fmt(recovery), color = NeonMV.Ink, size = 19)
        }
    }
}

/**
 * Centered "no data" hint shown when today's summary failed to load (cold
 * launch / offline) or there's genuinely nothing for today yet. Replaces the
 * grid of blank tiles so the screen never looks broken.
 */
@Composable
private fun EmptyHintCard() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.CardHigh)
            .border(1.dp, NeonMV.Cyan.copy(alpha = 0.22f), NeonCardShape)
            .padding(horizontal = 20.dp, vertical = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .size(10.dp)
                .clip(RoundedCornerShape(5.dp))
                .background(NeonMV.Cyan.copy(alpha = 0.55f)),
        )
        Spacer(Modifier.height(14.dp))
        Text(
            "Couldn't load today's data",
            color = NeonMV.Ink,
            fontFamily = NeonNumberFamily,
            fontSize = 15.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = (-0.2).sp,
        )
        Spacer(Modifier.height(7.dp))
        Text(
            "Pull down or check your connection — vitals will appear once today has synced.",
            color = NeonMV.Muted,
            fontSize = 12.5.sp,
            fontWeight = FontWeight.Medium,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            lineHeight = 17.sp,
        )
    }
}

/**
 * Single glanceable metric card — tiny label, big NeonNumber value + unit,
 * sub-context line. A subtle accent-coloured border supplies the neon glow
 * the web cards get from drop-shadow filters. `onClick = null` renders a
 * non-interactive card (skin temp).
 */
@Composable
private fun MetricCard(
    label: String,
    value: String,
    unit: String?,
    accent: Color,
    sub: String,
    loading: Boolean,
    onClick: (() -> Unit)?,
    subColor: Color = NeonMV.Muted,
    spark: List<Float?>? = null,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .height(124.dp)
            .clip(NeonCardShape)
            // Slightly stronger surface than the flat Card fill: a faint
            // accent-tinted top-to-bottom wash over the elevated card colour
            // so the tile reads as a lit surface, not an empty rectangle.
            .background(NeonMV.CardHigh)
            .background(
                Brush.verticalGradient(
                    colors = listOf(accent.copy(alpha = 0.10f), Color.Transparent),
                ),
            )
            .border(1.dp, accent.copy(alpha = 0.26f), NeonCardShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        // Bolder variant: the 14-day trend rides the lower half of the card as
        // a faint accent backdrop behind the value, not a thin line under it.
        if (spark != null && spark.count { it != null } >= 2) {
            app.myvitals.ui.vitals.SparkLine(
                values = spark,
                color = accent.copy(alpha = 0.30f),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(64.dp)
                    .align(Alignment.BottomCenter),
            )
        }
        Column(
            Modifier.fillMaxSize().padding(horizontal = 14.dp, vertical = 13.dp),
        ) {
            Text(
                label.uppercase(),
                color = accent.copy(alpha = 0.85f),
                fontFamily = NeonNumberFamily,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.2.sp,
            )
            Spacer(Modifier.weight(1f))
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(
                    if (loading && value == "—") "…" else value,
                    color = NeonMV.Ink,
                    size = 25,
                )
                if (unit != null) {
                    Spacer(Modifier.width(4.dp))
                    Text(
                        unit,
                        color = NeonMV.Muted,
                        fontFamily = NeonNumberFamily,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(bottom = 3.dp),
                    )
                }
            }
            Spacer(Modifier.height(7.dp))
            Text(
                sub,
                color = subColor,
                fontSize = 11.5.sp,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

/** Full-width blood-pressure card with a category verdict (cyan). */
@Composable
private fun BloodPressureCard(
    sys: Double?,
    dia: Double?,
    loading: Boolean,
    onClick: () -> Unit,
) {
    val label = when {
        sys == null || dia == null -> "—"
        sys < 120 && dia < 80 -> "Optimal"
        sys < 130 && dia < 80 -> "Normal"
        sys < 140 || dia < 90 -> "Elevated"
        else -> "High"
    }
    val labelColor = if (sys != null && sys >= 140) NeonMV.Bad else NeonMV.Cyan
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.CardHigh)
            .background(
                Brush.verticalGradient(
                    colors = listOf(NeonMV.Cyan.copy(alpha = 0.10f), Color.Transparent),
                ),
            )
            .border(1.dp, NeonMV.Cyan.copy(alpha = 0.26f), NeonCardShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text(
                "BLOOD PRESSURE",
                color = NeonMV.Cyan.copy(alpha = 0.85f),
                fontFamily = NeonNumberFamily,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.2.sp,
            )
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(
                    if (sys != null && dia != null) "${fmt(sys)}/${fmt(dia)}"
                    else if (loading) "…" else "—",
                    color = NeonMV.Ink,
                    size = 27,
                )
                Spacer(Modifier.width(4.dp))
                Text(
                    "mmHg",
                    color = NeonMV.Muted,
                    fontFamily = NeonNumberFamily,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(bottom = 3.dp),
                )
            }
            Spacer(Modifier.height(7.dp))
            Text(
                label,
                color = labelColor,
                fontFamily = NeonNumberFamily,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

// ============================================================
// SWR cache keys (grep "JsonCache.write" to audit)
// ============================================================

private const val BODY_SUMMARY_KEY = "neon_body_summary"
private const val BODY_PROFILE_KEY = "neon_body_profile"

// ============================================================
// Formatters (mirror the web `fmt` helper)
// ============================================================

private fun fmt(n: Double?): String = if (n == null) "—" else "%.0f".format(n)
