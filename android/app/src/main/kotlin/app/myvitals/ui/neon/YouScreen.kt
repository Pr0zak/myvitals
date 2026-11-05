package app.myvitals.ui.neon

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.EditNote
import androidx.compose.material.icons.outlined.HourglassEmpty
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Restaurant
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Timer
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.layout
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.JsonCache
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.AiGoal
import app.myvitals.sync.BackendClient
import app.myvitals.sync.FastingSession
import app.myvitals.sync.ProfileResponse
import app.myvitals.sync.SoberCurrentResponse
import app.myvitals.ui.common.GoalAway
import app.myvitals.ui.common.ShimmerBlock
import app.myvitals.ui.common.goalStateNote
import com.squareup.moshi.JsonClass
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import timber.log.Timber
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.floor
import kotlin.math.roundToInt

/**
 * You — the personal hub. Mirrors web `You.vue`.
 *
 *   title     "You", the profile summary as a subtitle under it
 *   hero      habits: the active fast as a ring (elapsed of target, stage,
 *             when it ends) beside the sober count
 *   goals     up to three small rings, coloured by the SERVER's state_tone
 *   grid      Journal · Coach · Meals · Sober · Fasting · Settings
 *
 * Failure is not absence (UX-F3). Each section remembers whether its request
 * actually SUCCEEDED: "Not fasting", "No active goals yet" and "Start
 * counting" are claims about the user and only render on a real answer. A
 * failed load with nothing cached shows the error banner and the navigation
 * grid, nothing else. Last-known data is cached (JsonCache SWR) so a tab
 * switch or an offline launch renders instantly.
 *
 * onOpen routes: "settings", "sober", "fasting", "journal", "coach", "meals".
 */
@Composable
fun YouScreen(
    settings: SettingsRepository,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf(YouData()) }
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
                // Each call reports success separately. A 200 with a null
                // body from /fasting/current IS an answer ("not fasting");
                // an exception or non-2xx is not.
                val fastingD = async(Dispatchers.IO) {
                    runCatching {
                        val r = api.fastingCurrent()
                        if (!r.isSuccessful) throw IllegalStateException("HTTP ${r.code()}")
                        r.body()
                    }
                }
                val soberD = async(Dispatchers.IO) { runCatching { api.soberCurrent() } }
                val goalsD = async(Dispatchers.IO) { runCatching { api.aiGoals(activeOnly = true) } }
                val profileD = async(Dispatchers.IO) { runCatching { api.profile() } }
                val f = fastingD.await()
                val s = soberD.await()
                val g = goalsD.await()
                val p = profileD.await()
                // Merge: a failed section keeps its cached value (and its
                // "known" flag) rather than blanking back to unknown.
                val prev = data
                val next = YouData(
                    fasting = if (f.isSuccess) f.getOrNull() else prev.fasting,
                    fastingKnown = f.isSuccess || prev.fastingKnown,
                    sober = s.getOrNull() ?: prev.sober,
                    goals = g.getOrNull() ?: prev.goals,
                    profile = p.getOrNull() ?: prev.profile,
                )
                data = next
                val allFailed = f.isFailure && s.isFailure && g.isFailure && p.isFailure
                error = if (allFailed) "Couldn't reach the backend." else null
                if (!allFailed) JsonCache.write(context, YOU_CACHE_KEY, YouData::class.java, next)
            }
        } catch (e: Exception) {
            Timber.w(e, "you-screen load failed")
            error = e.message?.take(140) ?: "Load failed"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) {
        runCatching {
            JsonCache.read<YouData>(context, YOU_CACHE_KEY, YouData::class.java)
                ?.let { data = it.value }
        }
        load()
    }
    app.myvitals.ui.common.LifecycleResumeEffect { scope.launch { load() } }

    val todayLabel = remember {
        runCatching {
            LocalDate.now().format(DateTimeFormatter.ofPattern("EEE, MMM d"))
        }.getOrDefault("")
    }

    YouContent(
        data = data,
        loading = loading,
        refreshing = refreshing,
        error = error,
        todayLabel = todayLabel,
        contentPadding = contentPadding,
        onOpen = onOpen,
        onRefresh = {
            scope.launch { refreshing = true; try { load() } finally { refreshing = false } }
        },
    )
}

/**
 * Everything You renders, cached as one unit. A null section means "never
 * successfully loaded" — except fasting, where null is also the legitimate
 * "not fasting" answer, so it carries its own [fastingKnown] flag.
 */
@JsonClass(generateAdapter = true)
data class YouData(
    val fasting: FastingSession? = null,
    val fastingKnown: Boolean = false,
    val sober: SoberCurrentResponse? = null,
    val goals: List<AiGoal>? = null,
    val profile: ProfileResponse? = null,
) {
    val nothingKnown: Boolean
        get() = !fastingKnown && sober == null && goals == null && profile == null
}

@Composable
fun YouContent(
    data: YouData,
    loading: Boolean,
    refreshing: Boolean,
    error: String?,
    todayLabel: String,
    contentPadding: PaddingValues,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
    zone: ZoneId = ZoneId.systemDefault(),
) {
    NeonScreen(
        title = "You",
        contentPadding = contentPadding,
        headerTrailing = {
            if (todayLabel.isNotEmpty()) {
                Text(todayLabel, color = NeonMV.Muted, fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold)
            }
        },
        refreshing = refreshing,
        onRefresh = onRefresh,
    ) {
        profileLine(data.profile)?.let { ProfileSubtitle(it) }

        if (data.nothingKnown) {
            if (error != null && !loading) {
                // UX-F3: say it failed. No "Not fasting", no "No active
                // goals yet" — those would be claims the app cannot make.
                NeonErrorBanner(error, title = "Couldn't load your habits and goals") { onRefresh() }
            } else {
                YouSkeleton()
            }
            NavGrid(onOpen)
            Spacer(Modifier.height(24.dp))
            return@NeonScreen
        }
        if (error != null) {
            NeonErrorBanner("Showing your last saved copy. $error", title = "Couldn't refresh") { onRefresh() }
        }

        HabitsHero(data, zone, onOpen)

        SectionHeading("Goals")
        GoalRings(data.goals)
        Spacer(Modifier.height(26.dp))

        SectionHeading("More")
        NavGrid(onOpen)
        Spacer(Modifier.height(24.dp))
    }
}

// ============================================================
// Profile subtitle
// ============================================================

private fun profileLine(profile: ProfileResponse?): String? {
    profile ?: return null
    val parts = buildList {
        profile.derived?.age?.let { add("$it yrs") }
        profile.sex?.takeIf { it.isNotBlank() }
            ?.let { add(it.replaceFirstChar { c -> c.titlecase() }) }
        profile.heightCm?.let {
            val totalIn = (it / 2.54).roundToInt()
            add("${totalIn / 12}'${totalIn % 12}\"")
        }
        profile.activityLevel?.takeIf { it.isNotBlank() }
            ?.let { add(it.replace("_", " ")) }
    }
    // Only said on a real answer — an unloaded profile says nothing.
    // A sentence, not a " · " string: "41 yrs, male, 5'11", moderately active".
    if (parts.isEmpty()) return "Add your details in Settings"
    return parts.mapIndexed { i, p -> if (i == 0) p else p.lowercase() }.joinToString(", ")
}

/** 12sp line tucked up under the title, where the old profile card's one
 *  useful sentence now lives. Pulled up into the title's bottom padding. */
@Composable
private fun ProfileSubtitle(text: String) {
    Text(
        text, color = NeonMV.Ink.copy(alpha = 0.85f), fontSize = 13.sp,
        maxLines = 1, overflow = TextOverflow.Ellipsis,
        modifier = Modifier
            .layout { m, c ->
                val p = m.measure(c)
                val lift = 10.dp.roundToPx()
                layout(p.width, (p.height - lift).coerceAtLeast(0)) { p.place(0, -lift) }
            }
            .padding(bottom = 18.dp),
    )
}

/** Sentence-case section heading — replaces the tracked ALL-CAPS eyebrow. */
@Composable
private fun SectionHeading(text: String) {
    Text(
        text, color = NeonMV.Ink, fontSize = 18.sp, fontWeight = FontWeight.Medium,
        modifier = Modifier.padding(bottom = 10.dp),
    )
}

// ============================================================
// Habits hero
// ============================================================

private val STAGE_LABELS = mapOf(
    "fed" to "Fed state",
    "gut_rest" to "Gut rest",
    "glycogen_depleting" to "Glycogen depleting",
    "ketosis" to "Ketosis",
    "autophagy" to "Autophagy",
    "deep_autophagy" to "Deep autophagy",
    "extended_36" to "36h territory",
    "extended_48" to "48h territory",
    "extended_72" to "72h+ territory",
)

@Composable
private fun HabitsHero(data: YouData, zone: ZoneId, onOpen: (String) -> Unit) {
    // Hero on the page ground, in the Today brief's language: two blocks
    // side by side, separated by space rather than a card or a divider.
    Row(
        Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 26.dp),
        horizontalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        FastingHalf(data, zone, Modifier.weight(1f)) { onOpen("fasting") }
        SoberHalf(data, zone, Modifier.weight(1f)) { onOpen("sober") }
    }
}

/** Muted label with the 3dp identity bar — the legend's label, used as the
 *  heading of each hero block. */
@Composable
private fun BlockLabel(text: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(width = 3.dp, height = 14.dp).background(color, RoundedCornerShape(2.dp)))
        Spacer(Modifier.width(8.dp))
        Text(text, color = NeonMV.Muted, fontSize = 12.sp)
    }
}

/** The cyan primary pill. Decorative inside an already-clickable block. */
@Composable
private fun PrimaryPill(text: String) {
    Text(
        text, color = NeonMV.OnAccent, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(NeonMV.Cyan)
            .padding(horizontal = 14.dp, vertical = 6.dp),
    )
}

@Composable
private fun FastingHalf(data: YouData, zone: ZoneId, modifier: Modifier, onClick: () -> Unit) {
    val f = data.fasting?.takeIf { it.isActive }
    val target = f?.targetHours
    Column(
        modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick),
        horizontalAlignment = Alignment.Start,
    ) {
        BlockLabel("Fasting", NeonMV.Cyan)
        Spacer(Modifier.height(10.dp))
        NeonRing(
            // elapsed / target, both from /fasting/current. No target, no
            // fraction — the ring stays empty rather than assume 16h.
            fraction = if (f != null && target != null && target > 0) (f.elapsedH / target).toFloat() else 0f,
            color = NeonMV.Cyan,
            size = 140.dp,
            stroke = 12.dp,
            // UI-F5: a tick at each stage threshold the server sends that
            // falls inside the target — the same stages the Fasting ring
            // marks. Nothing is drawn without a target to scale against.
            ticks = if (f != null && target != null && target > 0)
                f.stages.map { (it.atH / target).toFloat() }.filter { it > 0f && it < 1f }
            else emptyList(),
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                if (f != null) {
                    // "14.3h" over "of 16h" — never "14:16", which reads as
                    // a clock time.
                    Text(
                        "%.1fh".format(f.elapsedH), color = NeonMV.Ink, fontSize = 28.sp,
                        fontFamily = NeonNumberFamily, fontWeight = FontWeight.Medium,
                        letterSpacing = (-0.5).sp,
                    )
                    Text(if (target != null) "of ${trimNum(target)}h" else "no target",
                        color = NeonMV.Muted, fontSize = 11.sp)
                } else {
                    Text("—", color = NeonMV.Muted, fontSize = 28.sp, fontFamily = NeonNumberFamily)
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        when {
            f != null -> {
                Text(
                    STAGE_LABELS[f.currentStage] ?: f.currentStage.replace('_', ' ')
                        .replaceFirstChar { it.uppercase() },
                    color = NeonMV.Ink, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
                fastEnds(f, zone)?.let {
                    Text(it.replaceFirstChar { c -> c.uppercase() }, color = NeonMV.Muted, fontSize = 11.sp)
                }
            }
            // Only a SUCCESSFUL "no active fast" may say this.
            data.fastingKnown -> {
                Text("Not fasting", color = NeonMV.Muted, fontSize = 11.sp)
                Spacer(Modifier.height(6.dp))
                PrimaryPill("Start a fast")
            }
            else -> Text("Couldn't load", color = NeonMV.Muted, fontSize = 11.sp)
        }
    }
}

/** "ends 8:30 PM" (or "target reached 8:30 PM") in local time: the start
 *  plus the target the session itself carries. */
private fun fastEnds(f: FastingSession, zone: ZoneId): String? {
    val t = f.targetHours ?: return null
    return runCatching {
        val end = OffsetDateTime.parse(f.startedAt).toInstant()
            .plusSeconds((t * 3600).toLong()).atZone(zone)
        val clock = end.format(DateTimeFormatter.ofPattern("h:mm a"))
        if (f.elapsedH >= t) "target reached $clock" else "ends $clock"
    }.getOrNull()
}

@Composable
private fun SoberHalf(data: YouData, zone: ZoneId, modifier: Modifier, onClick: () -> Unit) {
    val s = data.sober
    val active = s?.active
    Column(
        modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick),
        horizontalAlignment = Alignment.Start,
    ) {
        BlockLabel("Sober", NeonMV.Magenta)
        // Same height as the fasting ring so the two blocks' text lines up.
        Box(Modifier.height(150.dp), contentAlignment = Alignment.CenterStart) {
            when {
                active != null -> {
                    val days = s?.days ?: floor(active.days).toInt()
                    // Ink, never a warning colour — the count is never a
                    // warning, and a reset is never one either. The magenta
                    // bar carries the identity.
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(
                            days.toString(), color = NeonMV.Ink, fontSize = 58.sp,
                            fontFamily = NeonNumberFamily, fontWeight = FontWeight.Medium,
                            letterSpacing = (-2).sp,
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(if (days == 1) "day" else "days", color = NeonMV.Muted,
                            fontSize = 14.sp, modifier = Modifier.padding(bottom = 12.dp))
                    }
                }
                else -> Text("—", color = NeonMV.Muted, fontSize = 58.sp, fontFamily = NeonNumberFamily)
            }
        }
        when {
            active != null -> sinceLabel(active.startAt, zone)?.let {
                Text(it.replaceFirstChar { c -> c.uppercase() }, color = NeonMV.Muted, fontSize = 11.sp)
            }
            // A real answer with no active streak: neutral, an invitation.
            s != null -> PrimaryPill("Start counting")
            else -> Text("Couldn't load", color = NeonMV.Muted, fontSize = 11.sp)
        }
    }
}

private fun sinceLabel(iso: String, zone: ZoneId): String? = runCatching {
    val d = OffsetDateTime.parse(iso).atZoneSameInstant(zone).toLocalDate()
    val fmt = if (d.year == LocalDate.now(zone).year) "MMM d" else "MMM d, yyyy"
    "since " + d.format(DateTimeFormatter.ofPattern(fmt))
}.getOrNull()

// ============================================================
// Goals as rings
// ============================================================

@Composable
private fun GoalRings(goals: List<AiGoal>?) {
    when {
        goals == null -> Text(
            "Couldn't load goals", color = NeonMV.Muted, fontSize = 13.sp,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        goals.isEmpty() -> Text(
            "No active goals yet", color = NeonMV.Muted, fontSize = 13.sp,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        else -> Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            goals.take(3).forEach { g -> GoalRing(g, Modifier.weight(1f)) }
            // Keep ring widths constant when fewer than three goals exist.
            repeat(3 - goals.take(3).size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

/**
 * Colour comes from the server's `state_tone`, NEVER from list position —
 * the old strip painted goal #1 cyan and #2 magenta, so a regressing goal
 * could wear an achievement colour just by sorting first. Fill is
 * `progress_pct` verbatim; null is an empty ring that says so. There is
 * deliberately no `current / target` fallback: for a weight goal approached
 * from above that ratio is > 1 and painted a FULL ring on the goal doing
 * worst (GOAL-STATE).
 */
@Composable
private fun GoalRing(g: AiGoal, modifier: Modifier) {
    val pct = g.progressPct
    val tone = g.stateTone
    val color = when {
        pct == null || tone == "unknown" -> NeonMV.Track
        tone == "positive" -> NeonMV.Lime
        tone == "caution" -> GoalAway
        else -> NeonMV.Muted
    }
    val note = if (pct == null) "no reading yet" else goalStateNote(g)
    Column(
        modifier
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .padding(horizontal = 8.dp, vertical = 14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        NeonRing(
            fraction = ((pct ?: 0.0) / 100.0).toFloat(),
            color = color,
            size = 72.dp,
            stroke = 7.dp,
        ) {
            NeonNumber(
                pct?.let { "${it.roundToInt()}%" } ?: "—",
                color = if (pct == null) NeonMV.Muted else NeonMV.Ink,
                size = 16,
            )
        }
        Spacer(Modifier.height(8.dp))
        Text(
            g.title, color = NeonMV.Ink, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
            maxLines = 2, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
            lineHeight = 15.sp,
        )
        note?.let {
            Spacer(Modifier.height(2.dp))
            Text(
                it,
                color = if (tone == "caution" && pct != null) GoalAway else NeonMV.Muted,
                fontSize = 10.5.sp, maxLines = 2, textAlign = TextAlign.Center,
                lineHeight = 13.sp,
            )
        }
    }
}

// ============================================================
// Navigation grid
// ============================================================

private data class NavTile(val label: String, val icon: ImageVector, val tint: Color, val route: String)

private val NAV_TILES = listOf(
    NavTile("Journal", Icons.Outlined.EditNote, NeonMV.Magenta, "journal"),
    NavTile("Coach", Icons.Outlined.Psychology, NeonMV.Periwinkle, "coach"),
    NavTile("Meals", Icons.Outlined.Restaurant, NeonMV.Lime, "meals"),
    NavTile("Sober", Icons.Outlined.Timer, NeonMV.Magenta, "sober"),
    NavTile("Fasting", Icons.Outlined.HourglassEmpty, NeonMV.Cyan, "fasting"),
    NavTile("Settings", Icons.Outlined.Settings, NeonMV.Amber, "settings"),
)

@Composable
private fun NavGrid(onOpen: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        NAV_TILES.chunked(3).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { t ->
                    Column(
                        Modifier
                            .weight(1f)
                            .clip(NeonCardShape)
                            .background(NeonMV.Card)
                            .clickable { onOpen(t.route) }
                            .padding(vertical = 16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        // Tinted glyph only; the filled circle behind it was a
                        // second colour field per tile.
                        Icon(t.icon, contentDescription = null, tint = t.tint,
                            modifier = Modifier.size(24.dp))
                        Spacer(Modifier.height(8.dp))
                        Text(t.label, color = NeonMV.Ink, fontSize = 13.sp,
                            fontWeight = FontWeight.Medium)
                    }
                }
            }
        }
    }
}

// ============================================================
// Loading
// ============================================================

@Composable
private fun YouSkeleton() {
    @Composable
    fun Block(label: String, accent: Color, height: Dp, modifier: Modifier) {
        Box(modifier.height(height)) {
            ShimmerBlock(Modifier.fillMaxWidth(), height = height, cornerRadius = 20.dp, accent = accent)
            Text(label, color = accent.copy(alpha = 0.75f), fontSize = 12.sp,
                modifier = Modifier.padding(14.dp))
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Block("Fasting", NeonMV.Cyan, 200.dp, Modifier.weight(1f))
        Block("Sober", NeonMV.Magenta, 200.dp, Modifier.weight(1f))
    }
    Spacer(Modifier.height(14.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(3) { Block(if (it == 0) "Goals" else "", NeonMV.Lime, 140.dp, Modifier.weight(1f)) }
    }
    Spacer(Modifier.height(24.dp))
}

private fun trimNum(v: Double): String =
    if (v == floor(v)) v.toLong().toString() else "%.1f".format(v)

// SWR cache key (grep "JsonCache.write" to audit)
private const val YOU_CACHE_KEY = "neon_you_v2"
