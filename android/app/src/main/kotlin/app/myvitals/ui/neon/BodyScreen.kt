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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.TilePrefsOut
import app.myvitals.sync.VitalTile
import app.myvitals.sync.VitalTilesResponse
import app.myvitals.ui.common.ShimmerBlock
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import kotlin.math.abs

/**
 * Body — recovery hero + the shared metric cards, in two tiers. Mirrors web
 * `Body.vue`.
 *
 *   hero     recovery ring (the recovery tile's value and server wording),
 *            beside it HRV / resting HR / sleep with their server deltas,
 *            and "N of M vitals in range · synced Xm ago" from the rollup
 *   daily    steps, sleep, HR, HRV — 2-up MetricCards with a taller spark
 *   by hand  weight, blood pressure, skin temp — full-width compact rows
 *            with the reading's own date and a 14-day reading strip
 *
 * The tier is the tile's `cadence`, decided server-side (TILE_CADENCE), so
 * the phone and the web cannot keep different lists of which metrics are
 * taken by hand. Everything renders from ONE request, `/summary/tiles`; the
 * summaryToday / summaryRange / profile calls this screen used to make were
 * fetched, cached, and never read.
 *
 * onOpen routes: "vitals/<VITAL>" via KeyMetrics, "vitals/RECOVERY" (hero).
 */
@Composable
fun BodyScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var tiles by remember { mutableStateOf<VitalTilesResponse?>(null) }
    // TILE-1: the tile order is its own endpoint.
    var tilePrefs by remember { mutableStateOf<TilePrefsOut?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        if (!settings.isConfigured()) {
            error = "Backend not configured — open Settings."
            loading = false
            return
        }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            coroutineScope {
                val tilesD = async(Dispatchers.IO) { runCatching { api.summaryTiles() } }
                // Non-fatal: an older backend without /profile/tile-prefs
                // simply renders the tiles in their catalog order.
                val prefsD = async(Dispatchers.IO) { runCatching { api.tilePrefs() }.getOrNull() }
                tilesD.await()
                    .onSuccess {
                        tiles = it
                        error = null
                        JsonCache.write(context, BODY_TILES_KEY, VitalTilesResponse::class.java, it)
                    }
                    .onFailure {
                        Timber.w(it, "body tiles load failed")
                        // Keep the cached render; say the refresh failed.
                        error = "Couldn't reach the backend."
                    }
                prefsD.await()?.let {
                    tilePrefs = it
                    JsonCache.write(context, BODY_PREFS_KEY, TilePrefsOut::class.java, it)
                }
            }
        } catch (e: Exception) {
            Timber.w(e, "body load failed")
            error = e.message?.take(140) ?: "Load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        // SWR: last-known tiles render instantly; the fetch below swaps in
        // fresh ones. The spinner/skeleton only shows on a cold cache.
        runCatching {
            JsonCache.read<VitalTilesResponse>(context, BODY_TILES_KEY, VitalTilesResponse::class.java)
                ?.let { tiles = it.value }
            JsonCache.read<TilePrefsOut>(context, BODY_PREFS_KEY, TilePrefsOut::class.java)
                ?.let { tilePrefs = it.value }
        }
        load()
    }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }

    BodyContent(
        tiles = tiles,
        tilePrefs = tilePrefs,
        loading = loading,
        refreshing = refreshing,
        error = error,
        contentPadding = contentPadding,
        onOpen = onOpen,
        onRefresh = {
            scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
    )
}

/**
 * Stateless Body. [tiles] null = nothing has ever loaded (skeleton while
 * [loading], error banner once it failed); non-null with no tiles = the
 * server answered and simply has nothing yet, which is NOT a failure and is
 * not worded as one.
 */
@Composable
fun BodyContent(
    tiles: VitalTilesResponse?,
    tilePrefs: TilePrefsOut?,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
    nowMs: Long = System.currentTimeMillis(),
) {
    NeonScreen(
        title = "Body",
        contentPadding = contentPadding,
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        if (tiles == null) {
            if (error != null && !loading) {
                NeonErrorBanner(error, title = "Couldn't load your metrics") { onRefresh() }
            } else {
                BodySkeleton()
            }
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        // A cached render whose refresh failed: keep the numbers, say so.
        if (error != null) {
            NeonErrorBanner("Showing your last saved copy. $error", title = "Couldn't refresh") { onRefresh() }
        }
        if (tiles.tiles.isEmpty()) {
            NothingYetCard()
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }

        RecoveryHero(tiles, nowMs = nowMs, onOpen = onOpen)

        app.myvitals.ui.common.KeyMetrics(
            tiles = tiles.tiles,
            onOpen = onOpen,
            order = tilePrefs?.order ?: emptyList(),
            hidden = tilePrefs?.hidden?.toSet() ?: emptySet(),
            groupOrder = tiles.groupOrder,
            // The screen title already says what this is.
            title = null,
            // Recovery is the hero; a second card for it said it twice.
            exclude = setOf("recovery"),
            tiered = true,
            chartHeight = 56.dp,
        )
        Spacer(Modifier.height(24.dp))
    }
}

// ============================================================
// Recovery hero
// ============================================================

@Composable
private fun RecoveryHero(r: VitalTilesResponse, nowMs: Long, onOpen: (String) -> Unit) {
    val byKey = r.tiles.associateBy { it.key }
    val rec = byKey["recovery"]
    val recValue = (rec?.value as? Number)?.toDouble()
    // Hero on the page ground, in the Today brief's language: the ring on
    // the left, a coloured-bar legend carrying the numbers on the right,
    // then one quiet status line. No card, border or glow.
    Column(Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 22.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .clip(RoundedCornerShape(88.dp))
                    .clickable { onOpen("vitals/RECOVERY") },
            ) {
                NeonRing(
                    // Recovery is a 0-100 composite; the ring draws it on its
                    // own scale. Null draws an empty ring and says so.
                    fraction = ((recValue ?: 0.0) / 100.0).toFloat(),
                    color = NeonMV.Cyan,
                    size = 176.dp,
                    stroke = 13.dp,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            recValue?.let { rec?.displayValue() } ?: "—",
                            color = if (recValue != null) NeonMV.Ink else NeonMV.Muted,
                            fontSize = 38.sp, fontFamily = NeonNumberFamily,
                            fontWeight = FontWeight.Medium, letterSpacing = (-1).sp,
                        )
                        Text("Recovery", color = NeonMV.Muted, fontSize = 11.sp)
                    }
                }
            }
            Spacer(Modifier.width(18.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                DriverRow(byKey["hrv"], NeonMV.Cyan, onOpen)
                DriverRow(byKey["resting_hr"], NeonMV.Cyan, onOpen)
                DriverRow(byKey["sleep_duration"], NeonMV.Magenta, onOpen)
            }
        }
        val roll = r.summary?.takeIf { it.judged > 0 }
        val chipText = rec?.statusReason?.replaceFirstChar { it.uppercase() }
            ?: if (recValue == null) "No reading yet" else null
        val recNote = listOfNotNull(chipText, staleNote(rec)).joinToString(", ").ifBlank { null }
        BriefStatusLine(
            text = roll?.let { "${it.inRange} of ${it.judged} vitals in your range" } ?: recNote,
            warn = roll?.let { it.inRange < it.judged } ?: (rec?.status == "watch"),
            showDot = roll != null,
            trailing = r.lastSync?.let { syncAge(it, nowMs) }?.let { "Synced $it" },
        )
        // The recovery wording gets its own line when the roll-up took the
        // status line; amber only when the server says "watch".
        if (roll != null && recNote != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                recNote,
                color = if (rec?.status == "watch") NeonMV.Amber else NeonMV.Muted,
                fontSize = 12.sp,
            )
        }
    }
}

/** One legend row beside the ring: label, value + unit, and the server's
 *  delta against baseline as the sub line (verbatim — the client never
 *  subtracts). */
@Composable
private fun DriverRow(t: VitalTile?, accent: Color, onOpen: (String) -> Unit) {
    if (t == null) return
    val hasData = t.value != null
    val d = t.delta
    var subColor = NeonMV.Muted
    val sub: String? = if (hasData && d != null && abs(d) >= 0.05) {
        val better = when (t.higherIsBetter) {
            true -> d > 0
            false -> d < 0
            null -> null
        }
        subColor = when (better) {
            true -> NeonMV.Lime
            false -> NeonMV.Amber
            null -> NeonMV.Muted
        }
        "${if (d > 0) "▲" else "▼"} ${"%.1f".format(abs(d))} vs your normal"
    } else if (hasData && t.target != null && t.key == "sleep_duration") {
        // Sleep is judged against a target, not a baseline, so it carries
        // no delta. Name the target rather than invent one.
        "of ${trimNum(t.target)}h"
    } else null
    BriefLegendRow(
        color = accent,
        label = t.label,
        value = if (hasData) t.displayValue() else "—",
        unit = t.unit.takeIf { hasData && it.isNotBlank() },
        sub = sub,
        subColor = subColor,
    ) {
        when (t.key) {
            "hrv" -> onOpen("vitals/HRV")
            "resting_hr" -> onOpen("vitals/HR")
            "sleep_duration" -> onOpen("vitals/SLEEP")
        }
    }
}

/** Legend row in the Today brief's shape: 3dp bar, muted label, value in
 *  the number face, muted sub line. Shared by Body and You. */
@Composable
internal fun BriefLegendRow(
    color: Color,
    label: String,
    value: String,
    unit: String? = null,
    sub: String? = null,
    subColor: Color = NeonMV.Muted,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier
                .padding(top = 5.dp)
                .size(width = 3.dp, height = 30.dp)
                .background(color, RoundedCornerShape(2.dp)),
        )
        Spacer(Modifier.width(10.dp))
        Column {
            Text(label, color = NeonMV.Muted, fontSize = 12.sp)
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    value, color = NeonMV.Ink, fontSize = 20.sp,
                    fontFamily = NeonNumberFamily, fontWeight = FontWeight.Medium,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
                unit?.let {
                    Spacer(Modifier.width(3.dp))
                    Text(it, color = NeonMV.Muted, fontSize = 11.sp,
                        modifier = Modifier.padding(bottom = 3.dp))
                }
            }
            sub?.let {
                Text(it, color = subColor, fontSize = 11.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** The one quiet line under a hero: optional dot (lime, amber when
 *  [warn]), the text, and a muted trailing note on the right. */
@Composable
internal fun BriefStatusLine(
    text: String?,
    warn: Boolean,
    showDot: Boolean = true,
    trailing: String? = null,
) {
    if (text == null && trailing == null) return
    Spacer(Modifier.height(14.dp))
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        if (text != null) {
            if (showDot) {
                Box(
                    Modifier.size(6.dp).background(
                        if (warn) NeonMV.Amber else NeonMV.Lime, RoundedCornerShape(3.dp),
                    ),
                )
                Spacer(Modifier.width(8.dp))
            }
            Text(
                text,
                color = if (!showDot && warn) NeonMV.Amber else NeonMV.Ink.copy(alpha = 0.85f),
                fontSize = 13.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                // Only the text takes the slack: two weight(1f) children split
                // the row in half and truncated "4 of 5 vitals in your range".
                modifier = Modifier.weight(1f),
            )
        } else {
            Spacer(Modifier.weight(1f))
        }
        trailing?.let {
            Text(it, color = NeonMV.Muted, fontSize = 12.sp, maxLines = 1,
                modifier = Modifier.padding(start = 12.dp))
        }
    }
}

private fun trimNum(v: Double): String =
    if (v == v.toLong().toDouble()) v.toLong().toString() else "%.1f".format(v)

private fun staleNote(t: VitalTile?): String? {
    val sd = t?.staleDays ?: return null
    if (sd <= 0 || t.asOf == null) return null
    return runCatching {
        "as of " + LocalDate.parse(t.asOf).format(DateTimeFormatter.ofPattern("MMM d"))
    }.getOrNull()
}

/** "just now" / "12m ago" / "3h ago" / "2d ago" from an ISO instant. */
private fun syncAge(iso: String, nowMs: Long): String? = runCatching {
    val ms = runCatching { java.time.OffsetDateTime.parse(iso).toInstant().toEpochMilli() }
        .getOrElse { java.time.Instant.parse(iso).toEpochMilli() }
    val min = ((nowMs - ms) / 60_000L).coerceAtLeast(0)
    when {
        min < 1 -> "just now"
        min < 60 -> "${min}m ago"
        min < 60 * 24 -> "${min / 60}h ago"
        else -> "${min / (60 * 24)}d ago"
    }
}.getOrNull()

// ============================================================
// Empty / loading
// ============================================================

/** The server answered and has no tiles — a fresh install, or nothing has
 *  synced yet. Worded as that, never as a failure. */
@Composable
private fun NothingYetCard() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .padding(horizontal = 20.dp, vertical = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            "No vitals yet",
            color = NeonMV.Ink, fontFamily = NeonNumberFamily,
            fontSize = 15.sp, fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(7.dp))
        Text(
            "They appear here once your watch has synced through Health Connect.",
            color = NeonMV.Muted, fontSize = 12.5.sp, textAlign = TextAlign.Center,
            lineHeight = 17.sp,
        )
    }
}

@Composable
private fun BodySkeleton() {
    @Composable
    fun Block(label: String, accent: Color, height: Dp, modifier: Modifier) {
        Box(modifier.height(height)) {
            ShimmerBlock(Modifier.fillMaxWidth(), height = height, cornerRadius = 20.dp, accent = accent)
            Text(label, color = accent.copy(alpha = 0.75f), fontSize = 12.sp,
                modifier = Modifier.padding(14.dp))
        }
    }
    Block("Recovery", NeonMV.Cyan, 190.dp, Modifier.fillMaxWidth())
    Spacer(Modifier.height(14.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Block("HRV", NeonMV.Cyan, 180.dp, Modifier.weight(1f))
        Block("Resting HR", NeonMV.Cyan, 180.dp, Modifier.weight(1f))
    }
    Spacer(Modifier.height(10.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Block("Sleep", NeonMV.Magenta, 180.dp, Modifier.weight(1f))
        Block("Steps", NeonMV.Lime, 180.dp, Modifier.weight(1f))
    }
    Spacer(Modifier.height(10.dp))
    Block("Weight", NeonMV.Amber, 92.dp, Modifier.fillMaxWidth())
    Spacer(Modifier.height(10.dp))
    Block("Blood pressure", NeonMV.Cyan, 92.dp, Modifier.fillMaxWidth())
}

// ============================================================
// SWR cache keys (grep "JsonCache.write" to audit)
// ============================================================

private const val BODY_TILES_KEY = "neon_body_tiles"
private const val BODY_PREFS_KEY = "neon_body_tile_prefs"
