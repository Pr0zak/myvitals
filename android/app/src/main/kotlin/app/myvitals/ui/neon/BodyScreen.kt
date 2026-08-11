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
/**
 * "· from Aug 9" for a value /summary/today backfilled from an earlier day.
 *
 * The screen is headed "today". Without this it states a day-old HRV — or a
 * three-month-old weight — as today's fact, which is the same quiet lie the
 * tiles endpoint was fixed for.
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
    var vitalTiles by remember {
        mutableStateOf<List<app.myvitals.sync.VitalTile>>(emptyList())
    }
    var groupOrder by remember { mutableStateOf<List<String>>(emptyList()) }
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
                val tilesD = async(Dispatchers.IO) {
                    runCatching { api.summaryTiles() }.getOrNull()
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
                tilesD.await()?.let { r ->
                    if (r.tiles.isNotEmpty()) vitalTiles = r.tiles
                    groupOrder = r.groupOrder
                }
            }
        }.onFailure { Timber.w(it, "body load failed") }
        loading = false
    }

    val recovery = sum?.recoveryScore
    val stepGoal = profile?.stepsGoal() ?: 10_000

    NeonScreen(
        title = "Body",
        contentPadding = contentPadding,
    ) {
        // The SAME cards the home uses. This screen used to declare its own
        // private MetricCard and render gradient-tinted cards with uppercase
        // labels — a second card vocabulary, which is exactly what the
        // redesign exists to remove. It showed the same seven metrics as
        // Key metrics, in a different language, with its own client-side
        // blood-pressure verdict that ignored staleness.
        app.myvitals.ui.common.KeyMetrics(
            tiles = vitalTiles,
            onOpen = onOpen,
            order = profile?.extra?.vitalsOrder ?: emptyList(),
            hidden = profile?.extra?.vitalsHidden?.toSet() ?: emptySet(),
            groupOrder = groupOrder,
        )

        if (vitalTiles.isEmpty() && !loading) {
            EmptyHintCard()
        }
        Spacer(Modifier.height(24.dp))
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

/** Full-width blood-pressure card with a category verdict (cyan). */

// ============================================================
// SWR cache keys (grep "JsonCache.write" to audit)
// ============================================================

private const val BODY_SUMMARY_KEY = "neon_body_summary"
private const val BODY_PROFILE_KEY = "neon_body_profile"

// ============================================================
// Formatters (mirror the web `fmt` helper)
// ============================================================
