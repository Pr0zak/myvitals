package app.myvitals.ui.strength

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.ThumbDown
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.platform.LocalContext
import coil.compose.AsyncImage
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.EquipmentPayload
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun StrengthCatalogScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    val repo = remember(settings) { StrengthRepository(context, settings) }

    // Vitality Neon — when the neon shell is active these screens adopt the
    // neon palette; when it's off every color stays byte-for-byte classic.
    val neon = settings.neonShellEnabled
    val accent      = if (neon) NeonMV.Cyan    else MV.BrandRed
    val bg          = if (neon) NeonMV.Bg      else MV.Bg
    val card        = if (neon) NeonMV.Card    else MV.SurfaceContainer
    val cardHigh    = if (neon) NeonMV.CardHigh else MV.SurfaceContainerHigh
    val cardLow     = if (neon) NeonMV.Bg      else MV.SurfaceContainerLow
    val ink         = if (neon) NeonMV.Ink     else MV.OnSurface
    val muted       = if (neon) NeonMV.Muted   else MV.OnSurfaceVariant
    val dim         = if (neon) NeonMV.Muted   else MV.OnSurfaceDim
    val outline     = if (neon) NeonMV.Line    else MV.OutlineVariant
    val good        = if (neon) NeonMV.Lime    else MV.Green
    val favColor    = if (neon) NeonMV.Amber   else MV.Amber
    val badColor    = if (neon) NeonMV.Bad     else MV.Red
    // Exercise tag / muscle / icon tint — violet silhouettes become cyan
    // under neon to cohere with the heart/info accent family.
    val iconTint    = if (neon) NeonMV.Cyan    else Color(0xFFA78BFA)
    val iconTintBg  = if (neon) NeonMV.Cyan.copy(alpha = 0.08f) else Color(0x14A78BFA)

    var catalog by remember { mutableStateOf<List<StrengthExerciseInfo>>(emptyList()) }
    var equipment by remember { mutableStateOf<EquipmentPayload?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var search by remember { mutableStateOf("") }
    val prefs = remember { mutableStateMapOf<String, String>() }
    val activeCategories = remember { mutableStateMapOf<String, Boolean>() }
    var muscleFilter by remember { mutableStateOf("") }
    var detailEx by remember { mutableStateOf<StrengthExerciseInfo?>(null) }
    var detailStats by remember { mutableStateOf<app.myvitals.sync.StrengthExerciseStats?>(null) }
    var detailStatsLoading by remember { mutableStateOf(false) }
    val statsSummary = remember {
        mutableStateMapOf<String, app.myvitals.sync.StrengthExerciseStatsSummary>()
    }
    // Sort options mirror the web catalog (StrengthCatalog.vue):
    //   NAME · MOST_DONE · LEAST_DONE · RECENT · HEAVIEST · VOLUME
    var sortBy by remember { mutableStateOf("name") }
    var sortMenuOpen by remember { mutableStateOf(false) }

    val equipmentType = remember { EquipmentPayload::class.java as java.lang.reflect.Type }

    LaunchedEffect(Unit) {
        // Catalog has its own cache in StrengthPlanCache; equipment did
        // not. SWR-render cached equipment immediately so the catalog
        // renders availability flags correctly offline.
        app.myvitals.data.JsonCache.read<EquipmentPayload>(
            context, "strength_equipment", equipmentType,
        )?.let {
            equipment = it.value
            prefs.clear()
            prefs.putAll(it.value.exercisePrefs)
            loading = false
        }
        try {
            val cat = repo.catalog()
            catalog = cat.values.sortedBy { it.name }
            val eq = repo.equipment()
            equipment = eq.payload
            prefs.clear()
            prefs.putAll(eq.payload.exercisePrefs)
            app.myvitals.data.JsonCache.write(
                context, "strength_equipment", equipmentType, eq.payload,
            )
            // Non-critical: fetch per-exercise stats for pill + sort.
            val ss = repo.exercisesStatsSummary()
            statsSummary.clear()
            statsSummary.putAll(ss)
        } catch (e: Exception) {
            Timber.w(e, "catalog load failed")
            if (catalog.isEmpty() && equipment == null) error = e.message?.take(160)
        } finally { loading = false }
    }

    fun isAvailable(ex: StrengthExerciseInfo): Boolean {
        val e = equipment ?: return false
        for (tag in ex.equipment) {
            when (tag) {
                "bodyweight" -> {}
                "bench" -> if (!(e.bench.flat || e.bench.incline || e.bench.decline)) return false
                "dumbbell" -> if (e.dumbbells.type == "none") return false
                "barbell" -> if (!e.barbell) return false
                "cable" -> if (!e.cableStack) return false
                "kettlebell" -> if (e.kettlebellsLb.isEmpty()) return false
                "bands" -> if (!e.resistanceBands) return false
            }
        }
        return true
    }

    fun fuzzyScore(ex: StrengthExerciseInfo, q: String): Int? {
        if (q.isBlank()) return 0
        val needle = q.lowercase().trim()
        val name = ex.name.lowercase()
        val haystack = buildString {
            append(name); append(' ')
            append(ex.primaryMuscle.lowercase()); append(' ')
            append(ex.movementPattern.lowercase().replace('_', ' ')); append(' ')
            append(ex.equipment.joinToString(" ").lowercase()); append(' ')
            append(ex.secondaryMuscles.joinToString(" ").lowercase())
        }
        var score = 0
        for (tok in needle.split(Regex("\\s+")).filter { it.isNotEmpty() }) {
            val idx = haystack.indexOf(tok)
            if (idx < 0) {
                // Subsequence fallback ("rdl" → Romanian Deadlift)
                var h = 0
                for (ch in tok) {
                    val found = haystack.indexOf(ch, h)
                    if (found < 0) return null
                    h = found + 1
                }
                score += 1
            } else {
                score += 10
                if (name.startsWith(tok)) score += 30 else if (name.contains(tok)) score += 20
            }
        }
        return score
    }

    fun matchesCategory(ex: StrengthExerciseInfo, key: String): Boolean = when (key) {
        "yoga"       -> ex.movementPattern == "mobility"
        "bodyweight" -> ex.equipment.size == 1 && ex.equipment[0] == "bodyweight"
        "dumbbell"   -> ex.equipment.contains("dumbbell")
        "bench"      -> ex.equipment.contains("bench")
        "compound"   -> ex.isCompound
        "isolation"  -> !ex.isCompound && ex.movementPattern != "mobility"
        else         -> true
    }

    val muscleOptions by remember(catalog) {
        derivedStateOf { catalog.map { it.primaryMuscle }.distinct().sorted() }
    }

    fun statSortKey(ex: StrengthExerciseInfo): Double {
        val s = statsSummary[ex.id]
        if (s == null) {
            // Never-performed exercises surface first for least_done.
            return if (sortBy == "least_done") Double.POSITIVE_INFINITY else 0.0
        }
        return when (sortBy) {
            "most_done"  -> s.timesPerformed.toDouble()
            // Negate so DESC sort surfaces lowest count first.
            "least_done" -> -s.timesPerformed.toDouble()
            "recent"     -> s.lastPerformedDate?.let {
                runCatching { java.time.LocalDate.parse(it).toEpochDay().toDouble() }
                    .getOrDefault(0.0)
            } ?: 0.0
            "heaviest"   -> s.maxWeightLb ?: 0.0
            "volume"     -> s.totalVolumeLb
            else         -> 0.0
        }
    }

    val visible by remember(
        catalog, equipment, search, activeCategories.toMap(), muscleFilter,
        sortBy, statsSummary.toMap(),
    ) {
        derivedStateOf {
            var base = catalog.filter { isAvailable(it) }
            val activeKeys = activeCategories.filterValues { it }.keys
            if (activeKeys.isNotEmpty()) {
                base = base.filter { ex -> activeKeys.all { matchesCategory(ex, it) } }
            }
            if (muscleFilter.isNotEmpty()) {
                base = base.filter { it.primaryMuscle == muscleFilter }
            }
            val q = search.trim()
            val afterSearch = if (q.isEmpty()) base
            else base.mapNotNull { ex ->
                fuzzyScore(ex, q)?.let { s -> ex to s }
            }.sortedWith(compareByDescending<Pair<StrengthExerciseInfo, Int>> { it.second }
                .thenBy { it.first.name })
                .map { it.first }
            // Stat sort only applies when not searching — search ranks
            // by fuzzy score (matches web catalog behaviour).
            if (q.isEmpty() && sortBy != "name") {
                afterSearch.sortedWith(
                    compareByDescending<StrengthExerciseInfo> { statSortKey(it) }
                        .thenBy { it.name }
                )
            } else afterSearch
        }
    }

    fun setPref(exId: String, requested: String) {
        val cur = prefs[exId]
        val next = if (cur == requested) "neutral" else requested
        scope.launch {
            try {
                repo.setPref(exId, next)
                if (next == "neutral") prefs.remove(exId) else prefs[exId] = next
            } catch (e: Exception) {
                Timber.w(e, "setPref failed"); error = e.message?.take(160)
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().background(bg).padding(horizontal = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = ink)
            }
            Text(
                "Workout catalog",
                color = ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            "⭐ favorite · 👎 avoid · 🚫 disabled · tap to toggle",
            color = dim, fontSize = 11.sp,
            modifier = Modifier.padding(start = 4.dp, bottom = 8.dp),
        )

        androidx.compose.material3.OutlinedTextField(
            value = search,
            onValueChange = { search = it },
            placeholder = { Text("Search by name, muscle, equipment…",
                fontSize = 13.sp, color = muted) },
            singleLine = true,
            trailingIcon = if (search.isNotEmpty()) {
                {
                    IconButton(onClick = { search = "" }) {
                        Icon(Icons.Outlined.Close, contentDescription = "Clear",
                            tint = muted)
                    }
                }
            } else null,
            modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
            textStyle = androidx.compose.ui.text.TextStyle(
                color = ink, fontSize = 14.sp,
            ),
        )

        // Category filter chips (Yoga / Bodyweight only / Dumbbell / Bench
        // / Compound / Isolation). Multi-select; combine with AND.
        val categoryDefs = listOf(
            "yoga" to "Yoga / mobility",
            "bodyweight" to "Bodyweight",
            "dumbbell" to "Dumbbell",
            "bench" to "Bench",
            "compound" to "Compound",
            "isolation" to "Isolation",
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(bottom = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for ((key, label) in categoryDefs) {
                val on = activeCategories[key] == true
                Box(
                    Modifier
                        .clip(RoundedCornerShape(50))
                        .background(if (on) accent.copy(alpha = 0.18f) else card)
                        .border(1.dp,
                            if (on) accent.copy(alpha = 0.5f) else outline,
                            RoundedCornerShape(50))
                        .clickable {
                            activeCategories[key] = !(activeCategories[key] ?: false)
                        }
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Text(label,
                        color = if (on) accent else muted,
                        fontSize = 11.sp)
                }
            }
        }

        // Muscle-group dropdown (single-select).
        var muscleMenuOpen by remember { mutableStateOf(false) }
        Box(modifier = Modifier.padding(bottom = 8.dp)) {
            androidx.compose.material3.OutlinedButton(
                onClick = { muscleMenuOpen = true },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    if (muscleFilter.isEmpty()) "All muscle groups"
                    else if (muscleFilter == "flexibility") "yoga / mobility"
                    else muscleFilter.replace('_', ' '),
                    color = ink, fontSize = 13.sp,
                )
            }
            DropdownMenu(
                expanded = muscleMenuOpen,
                onDismissRequest = { muscleMenuOpen = false },
            ) {
                DropdownMenuItem(
                    text = { Text("All muscle groups") },
                    onClick = { muscleFilter = ""; muscleMenuOpen = false },
                )
                for (m in muscleOptions) {
                    DropdownMenuItem(
                        text = { Text(
                            if (m == "flexibility") "yoga / mobility"
                            else m.replace('_', ' ')
                        ) },
                        onClick = { muscleFilter = m; muscleMenuOpen = false },
                    )
                }
            }
        }

        // Sort-by dropdown (mirrors the web catalog).
        val sortLabels = listOf(
            "name"       to "Sort: A-Z by muscle",
            "most_done"  to "Sort: most done",
            "least_done" to "Sort: never / least done",
            "recent"     to "Sort: recently done",
            "heaviest"   to "Sort: heaviest weight",
            "volume"     to "Sort: total volume",
        )
        Box(modifier = Modifier.padding(bottom = 8.dp)) {
            androidx.compose.material3.OutlinedButton(
                onClick = { sortMenuOpen = true },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    sortLabels.firstOrNull { it.first == sortBy }?.second
                        ?: "Sort: A-Z by muscle",
                    color = ink, fontSize = 13.sp,
                )
            }
            DropdownMenu(
                expanded = sortMenuOpen,
                onDismissRequest = { sortMenuOpen = false },
            ) {
                for ((key, label) in sortLabels) {
                    DropdownMenuItem(
                        text = { Text(label) },
                        onClick = { sortBy = key; sortMenuOpen = false },
                    )
                }
            }
        }

        when {
            loading -> Text("Loading…", color = muted)
            error != null -> Text(error!!, color = badColor)
            visible.isEmpty() && search.isNotBlank() -> Text(
                "No matches for \"$search\".",
                color = muted,
            )
            visible.isEmpty() -> Text(
                "No available exercises — check your equipment in Settings.",
                color = muted,
            )
            else -> LazyColumn(
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(visible, key = { it.id }) { ex ->
                    val pref = prefs[ex.id]
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = when (pref) {
                                "favorite" -> cardHigh
                                "disabled" -> cardLow
                                else -> card
                            },
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .border(
                                width = if (pref != null) 2.dp else 0.dp,
                                color = when (pref) {
                                    "favorite" -> favColor
                                    "disabled" -> badColor
                                    "avoid" -> muted
                                    else -> Color.Transparent
                                },
                                shape = RoundedCornerShape(12.dp),
                            )
                            .clickable {
                                detailEx = ex
                                detailStats = null
                                detailStatsLoading = true
                                scope.launch {
                                    try {
                                        val api = app.myvitals.sync.BackendClient.create(
                                            settings.backendUrl, settings.bearerToken,
                                        )
                                        detailStats = withContext(Dispatchers.IO) {
                                            api.strengthExerciseStats(ex.id)
                                        }
                                    } catch (e: Exception) {
                                        Timber.w(e, "exercise stats failed")
                                    } finally { detailStatsLoading = false }
                                }
                            },
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            // Thumbnail: prefer Noun Project image_front
                            // (tinted violet), fall back to hand-drawn yoga
                            // silhouette for mobility entries. Use the
                            // SettingsRepository passed into the screen
                            // instead of re-reading SharedPreferences.
                            val baseUrl = remember(settings) {
                                settings.backendUrl.trimEnd('/')
                            }
                            if (ex.imageFront != null && baseUrl.isNotEmpty()) {
                                // Photo (.jpg from base catalog) → render as-is.
                                // Icon (.png from Noun Project) → tint violet.
                                // Mirrors web's image() vs thumb-mask split.
                                val isPhoto = ex.imageFront!!
                                    .lowercase().let { it.endsWith(".jpg") || it.endsWith(".jpeg") }
                                Box(
                                    Modifier
                                        .size(36.dp)
                                        .clip(RoundedCornerShape(6.dp))
                                        .background(iconTintBg),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    AsyncImage(
                                        model = baseUrl + ex.imageFront,
                                        contentDescription = ex.name,
                                        modifier = if (isPhoto) Modifier.size(36.dp)
                                                   else Modifier.size(28.dp),
                                        colorFilter = if (isPhoto) null
                                                      else ColorFilter.tint(iconTint),
                                    )
                                }
                                Spacer(Modifier.width(8.dp))
                            } else if (ex.movementPattern == "mobility"
                                && app.myvitals.ui.hasYogaPoseIcon(ex.id)) {
                                Box(
                                    Modifier
                                        .size(36.dp)
                                        .clip(RoundedCornerShape(6.dp))
                                        .background(iconTintBg),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    app.myvitals.ui.YogaPoseIcon(
                                        id = ex.id, size = 26.dp,
                                        tint = iconTint,
                                    )
                                }
                                Spacer(Modifier.width(8.dp))
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(ex.name, color = ink, fontSize = 14.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        modifier = Modifier.weight(1f, fill = false))
                                    val count = statsSummary[ex.id]?.timesPerformed ?: 0
                                    val pillBg = if (count > 0)
                                        (if (neon) NeonMV.Lime.copy(alpha = 0.18f) else Color(0x2D22C55E))
                                        else (if (neon) NeonMV.Muted.copy(alpha = 0.15f) else Color(0x26B0BEC5))
                                    val pillFg = if (count > 0)
                                        good else muted
                                    Spacer(Modifier.width(6.dp))
                                    Box(
                                        Modifier
                                            .clip(RoundedCornerShape(50))
                                            .background(pillBg)
                                            .padding(horizontal = 7.dp, vertical = 1.dp),
                                    ) {
                                        Text(
                                            if (count > 0) "${count}×" else "never",
                                            color = pillFg, fontSize = 10.sp,
                                            fontWeight = FontWeight.SemiBold,
                                        )
                                    }
                                }
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    val musclePath = muscleIconPath(ex.primaryMuscle)
                                    if (musclePath != null && baseUrl.isNotEmpty()) {
                                        AsyncImage(
                                            model = baseUrl + musclePath,
                                            contentDescription = null,
                                            modifier = Modifier.size(12.dp),
                                            colorFilter = ColorFilter.tint(iconTint),
                                        )
                                        Spacer(Modifier.width(3.dp))
                                    }
                                    Text(
                                        "${ex.movementPattern.replace('_', ' ')} · " +
                                          "${muscleIconLabel(ex.primaryMuscle).ifEmpty { ex.primaryMuscle }} · " +
                                          ex.level,
                                        color = muted, fontSize = 11.sp,
                                    )
                                }
                            }
                            // YouTube link — yoga poses ship without
                            // images, so this is the documentation surface.
                            IconButton(
                                onClick = {
                                    val q = java.net.URLEncoder.encode(
                                        ex.youtubeQuery ?: ex.name, "UTF-8",
                                    )
                                    val app = android.content.Intent(
                                        android.content.Intent.ACTION_VIEW,
                                        android.net.Uri.parse(
                                            "vnd.youtube://results?search_query=$q"),
                                    ).setPackage("com.google.android.youtube")
                                    val web = android.content.Intent(
                                        android.content.Intent.ACTION_VIEW,
                                        android.net.Uri.parse(
                                            "https://www.youtube.com/results?search_query=$q"),
                                    )
                                    runCatching { context.startActivity(app) }
                                        .recoverCatching { context.startActivity(web) }
                                },
                                modifier = Modifier.size(36.dp),
                            ) {
                                Icon(
                                    Icons.Filled.PlayArrow,
                                    contentDescription = "Watch on YouTube",
                                    tint = muted,
                                )
                            }
                            ActIcon(
                                icon = Icons.Filled.Star, on = pref == "favorite",
                                onColor = favColor, offColor = muted,
                                onClick = { setPref(ex.id, "favorite") },
                            )
                            ActIcon(
                                icon = Icons.Filled.ThumbDown, on = pref == "avoid",
                                onColor = muted, offColor = muted,
                                onClick = { setPref(ex.id, "avoid") },
                            )
                            ActIcon(
                                icon = Icons.Filled.Block, on = pref == "disabled",
                                onColor = badColor, offColor = muted,
                                onClick = { setPref(ex.id, "disabled") },
                            )
                        }
                    }
                }
            }
        }
    }

    // Detail bottom sheet
    if (detailEx != null) {
        val ex = detailEx!!
        androidx.compose.material3.ModalBottomSheet(
            onDismissRequest = { detailEx = null; detailStats = null },
            containerColor = card,
        ) {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                Text(ex.name, color = ink, fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold)
                Text(
                    "${ex.movementPattern.replace('_', ' ')} · ${ex.equipment.joinToString(" + ")} · ${ex.level}",
                    color = muted, fontSize = 12.sp,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Text(ex.primaryMuscle, color = ink, fontSize = 13.sp,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(top = 6.dp))
                if (ex.secondaryMuscles.isNotEmpty()) {
                    Text("also: ${ex.secondaryMuscles.joinToString(", ")}",
                        color = muted, fontSize = 12.sp,
                        modifier = Modifier.padding(top = 2.dp))
                }
                Spacer(Modifier.height(10.dp))
                androidx.compose.material3.OutlinedButton(
                    onClick = {
                        val q = java.net.URLEncoder.encode(
                            ex.youtubeQuery ?: ex.name, "UTF-8",
                        )
                        val app = android.content.Intent(
                            android.content.Intent.ACTION_VIEW,
                            android.net.Uri.parse(
                                "vnd.youtube://results?search_query=$q"),
                        ).setPackage("com.google.android.youtube")
                        val web = android.content.Intent(
                            android.content.Intent.ACTION_VIEW,
                            android.net.Uri.parse(
                                "https://www.youtube.com/results?search_query=$q"),
                        )
                        runCatching { context.startActivity(app) }
                            .recoverCatching { context.startActivity(web) }
                    },
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = null,
                        modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Watch on YouTube", fontSize = 12.sp)
                }

                Spacer(Modifier.height(16.dp))
                Text("YOUR HISTORY", color = muted,
                    fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    letterSpacing = 1.5.sp)
                Spacer(Modifier.height(6.dp))
                when {
                    detailStatsLoading -> Text("Loading…",
                        color = dim, fontSize = 12.sp)
                    detailStats == null || detailStats!!.timesPerformed == 0 ->
                        Text("Not performed yet.",
                            color = dim, fontSize = 12.sp)
                    else -> {
                        val s = detailStats!!
                        @Composable
                        fun statRow(label: String, value: String) {
                            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                                Text(label, color = muted,
                                    fontSize = 12.sp, modifier = Modifier.weight(1f))
                                Text(value, color = ink,
                                    fontSize = 12.sp, fontWeight = FontWeight.Medium)
                            }
                        }
                        statRow("Sessions", "${s.timesPerformed}")
                        statRow("Last seen", s.lastPerformedDate ?: "—")
                        statRow("Last weight", s.lastWeightLb?.let { "$it lb" } ?: "—")
                        statRow("Max weight", s.maxWeightLb?.let { "$it lb" } ?: "—")
                        statRow("Total reps", "${s.totalReps}")
                        statRow("Volume",
                            "${s.totalVolumeLb.toInt().toString()} lb")
                        s.avgRating?.let { statRow("Avg RPE", "%.1f".format(it)) }
                    }
                }

                if (ex.instructions.isNotEmpty()) {
                    Spacer(Modifier.height(16.dp))
                    Text("HOW TO DO IT", color = muted,
                        fontSize = 10.sp, fontWeight = FontWeight.Bold,
                        letterSpacing = 1.5.sp)
                    Spacer(Modifier.height(6.dp))
                    for ((i, line) in ex.instructions.withIndex()) {
                        Row(Modifier.padding(vertical = 3.dp)) {
                            Text("${i + 1}.", color = muted,
                                fontSize = 12.sp, modifier = Modifier.width(20.dp))
                            Text(line, color = ink, fontSize = 12.sp,
                                lineHeight = 18.sp)
                        }
                    }
                }
                Spacer(Modifier.height(20.dp))
            }
        }
    }
}

@Composable
private fun ActIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    on: Boolean, onColor: Color, offColor: Color = MV.OnSurfaceVariant,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(CircleShape)
            .background(if (on) onColor.copy(alpha = 0.18f) else Color.Transparent)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = null,
            tint = if (on) onColor else offColor)
    }
}
