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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import timber.log.Timber

/**
 * Neon Refined (A1) Body tab — the phone mirror of web `BodyRefined.vue`.
 *
 * A "This week" header over a vertical list of tappable neon vitals cards:
 * Weight (+ an inline Canvas sparkline off the 14-day summary window), Body
 * fat, Blood pressure (with a Normal/Elevated/High pill), Skin-temp Δ, Resting
 * HR, HRV. Same data source + tap routes as [BodyScreen] (which it replaces
 * when the "Neon Refined home" toggle is on, wired in [NeonAppShell]).
 *
 * onOpen routes: "vitals/WEIGHT", "vitals/BP", "vitals/HR", "vitals/HRV".
 * Skin temp has no phone detail screen (the `Vital` enum stops at
 * HR/HRV/SLEEP/STEPS/WEIGHT/BP) so its card is non-clickable — matching
 * [BodyScreen].
 */
@Composable
fun RefinedBodyScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    val context = LocalContext.current
    var sum by remember { mutableStateOf<DailySummary?>(null) }
    // 30-day daily-summary window powering the weight sparkline (mirrors the web
    // BodyRefined.vue `api.weight({since:30d})` fetch, sourced from the same
    // summary series the classic BodyScreen already reads).
    var trend by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        // SWR: render the last-known summary instantly so cold/offline loads
        // don't paint a list of blank "—" cards. Shares the cache key with
        // [BodyScreen] so both variants hydrate off the same last-known value.
        runCatching {
            JsonCache.read<DailySummary>(context, REFINED_BODY_SUMMARY_KEY, DailySummary::class.java)
                ?.let { sum = it.value; loading = false }
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
                val trendD = async(Dispatchers.IO) {
                    runCatching {
                        api.summaryRange(
                            since = java.time.LocalDate.now().minusDays(29).toString(),
                        )
                    }.getOrNull()
                }
                // Only swap in a fresh value — keep the cached render on a
                // failed/null fetch rather than blanking back to dashes.
                sumD.await()?.let {
                    sum = it
                    JsonCache.write(context, REFINED_BODY_SUMMARY_KEY, DailySummary::class.java, it)
                }
                trendD.await()?.let { trend = it }
            }
        }.onFailure { Timber.w(it, "refined body load failed") }
        loading = false
    }

    val weightLb = sum?.weightKg?.let { it * 2.2046226 }
    val bodyFat = sum?.bodyFatPct
    val bpSys = sum?.bpSystolicAvg
    val bpDia = sum?.bpDiastolicAvg
    val skinTemp = sum?.skinTempDeltaAvg
    val restingHr = sum?.restingHr
    val hrv = sum?.hrvAvg

    // Weight series (lb) for the inline sparkline — same 14/30-day summary
    // window BodyScreen uses. Only render when there are ≥2 real points.
    val weightSpark = trend.map { it.weightKg?.toFloat()?.times(2.2046226f) }

    NeonScreen(title = "Body", contentPadding = contentPadding) {
        Text(
            "This week",
            color = NeonMV.Muted,
            fontFamily = NeonNumberFamily,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.4.sp,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        // Weight — with an inline 30-day sparkline when the series has data.
        VitalsCard(
            glyph = "⚖",
            label = "Weight",
            value = if (weightLb != null) "%.1f".format(weightLb) else "—",
            unit = if (weightLb != null) "lb" else null,
            ctx = "30-day trend",
            loading = loading,
            spark = weightSpark.takeIf { it.count { v -> v != null } >= 2 },
            onClick = { onOpen("vitals/WEIGHT") },
        )
        Spacer(Modifier.height(10.dp))

        // Body fat.
        VitalsCard(
            glyph = "◐",
            label = "Body fat",
            value = if (bodyFat != null) "%.1f".format(bodyFat) else "—",
            unit = if (bodyFat != null) "%" else null,
            ctx = "Bioimpedance estimate",
            loading = loading,
            onClick = { onOpen("vitals/WEIGHT") },
        )
        Spacer(Modifier.height(10.dp))

        // Blood pressure — with a Normal/Elevated/High verdict pill.
        val bp = bpCategory(bpSys, bpDia)
        VitalsCard(
            glyph = "♡",
            label = "Blood pressure",
            value = if (bpSys != null && bpDia != null) "${fmt(bpSys)}/${fmt(bpDia)}" else "—",
            unit = if (bpSys != null && bpDia != null) "mmHg" else null,
            ctx = "Measured this morning",
            loading = loading,
            pillLabel = bp.first,
            pillColor = bp.second,
            onClick = { onOpen("vitals/BP") },
        )
        Spacer(Modifier.height(10.dp))

        // Skin-temp Δ — non-clickable (no phone detail screen).
        VitalsCard(
            glyph = "🌡",
            label = "Skin-temp Δ",
            value = skinTemp?.let { (if (it > 0) "+" else "") + "%.1f".format(it) } ?: "—",
            unit = if (skinTemp != null) "°C" else null,
            ctx = "vs baseline",
            loading = loading,
            onClick = null,
        )
        Spacer(Modifier.height(10.dp))

        // Resting HR.
        VitalsCard(
            glyph = "♥",
            label = "Resting HR",
            value = fmt(restingHr),
            unit = if (restingHr != null) "bpm" else null,
            ctx = "Lower is better",
            loading = loading,
            onClick = { onOpen("vitals/HR") },
        )
        Spacer(Modifier.height(10.dp))

        // HRV.
        VitalsCard(
            glyph = "∿",
            label = "HRV",
            value = fmt(hrv),
            unit = if (hrv != null) "ms" else null,
            ctx = "Overnight average",
            loading = loading,
            onClick = { onOpen("vitals/HRV") },
        )

        Spacer(Modifier.height(24.dp))
    }
}

/** Blood-pressure category → (label, colour), mirroring the web `bp` computed. */
private fun bpCategory(sys: Double?, dia: Double?): Pair<String, Color> = when {
    sys == null || dia == null -> "—" to NeonMV.Muted
    sys < 130 && dia < 80 -> "Normal" to NeonMV.Lime
    sys < 140 || dia < 90 -> "Elevated" to NeonMV.Amber
    else -> "High" to NeonMV.Bad
}

/**
 * A single tappable refined vitals row: glyph badge (cyan), label + big value +
 * unit + context line, an optional verdict pill on the label, an optional
 * inline sparkline, and a trailing chevron. `onClick = null` → non-interactive.
 */
@Composable
private fun VitalsCard(
    glyph: String,
    label: String,
    value: String,
    unit: String?,
    ctx: String,
    loading: Boolean,
    onClick: (() -> Unit)?,
    pillLabel: String? = null,
    pillColor: Color = NeonMV.Muted,
    spark: List<Float?>? = null,
) {
    Row(
        modifier = Modifier
            .clip(NeonCardShape)
            .background(NeonMV.CardHigh)
            .border(1.dp, NeonMV.Cyan.copy(alpha = 0.14f), NeonCardShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 15.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        Box(
            modifier = Modifier
                .size(42.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(NeonMV.Cyan.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center,
        ) {
            Text(glyph, color = NeonMV.Cyan, fontSize = 19.sp)
        }
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    label.uppercase(),
                    color = NeonMV.Muted,
                    fontFamily = NeonNumberFamily,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 0.5.sp,
                )
                if (pillLabel != null && pillLabel != "—") {
                    Spacer(Modifier.width(6.dp))
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(20.dp))
                            .background(pillColor.copy(alpha = 0.14f))
                            .padding(horizontal = 7.dp, vertical = 2.dp),
                    ) {
                        Text(
                            pillLabel.uppercase(),
                            color = pillColor,
                            fontFamily = NeonNumberFamily,
                            fontSize = 8.5.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 0.6.sp,
                        )
                    }
                }
            }
            Spacer(Modifier.height(3.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(
                    if (loading && value == "—") "…" else value,
                    color = NeonMV.Ink,
                    size = 22,
                )
                if (unit != null) {
                    Spacer(Modifier.width(3.dp))
                    Text(
                        unit,
                        color = NeonMV.Muted,
                        fontFamily = NeonNumberFamily,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier.padding(bottom = 2.dp),
                    )
                }
            }
            Spacer(Modifier.height(3.dp))
            Text(
                ctx,
                color = NeonMV.Muted,
                fontSize = 11.5.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        if (spark != null) {
            app.myvitals.ui.vitals.SparkLine(
                values = spark,
                color = NeonMV.Cyan.copy(alpha = 0.85f),
                modifier = Modifier
                    .width(76.dp)
                    .height(28.dp),
            )
        } else {
            Text("›", color = NeonMV.Muted, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        }
    }
}

// ============================================================
// SWR cache key (grep "JsonCache.write" to audit)
// ============================================================

private const val REFINED_BODY_SUMMARY_KEY = "neon_refined_body_summary"

/** Mirror the web `fmt` helper — 0-decimal or an em-dash for null. */
private fun fmt(n: Double?): String = if (n == null) "—" else "%.0f".format(n)
