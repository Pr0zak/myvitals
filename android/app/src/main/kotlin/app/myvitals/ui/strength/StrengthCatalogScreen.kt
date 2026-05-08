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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.strength.StrengthRepository
import app.myvitals.sync.EquipmentPayload
import app.myvitals.sync.StrengthExerciseInfo
import app.myvitals.ui.MV
import kotlinx.coroutines.launch
import timber.log.Timber

@Composable
fun StrengthCatalogScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = androidx.compose.ui.platform.LocalContext.current
    val repo = remember(settings) { StrengthRepository(context, settings) }

    var catalog by remember { mutableStateOf<List<StrengthExerciseInfo>>(emptyList()) }
    var equipment by remember { mutableStateOf<EquipmentPayload?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var search by remember { mutableStateOf("") }
    val prefs = remember { mutableStateMapOf<String, String>() }
    val activeCategories = remember { mutableStateMapOf<String, Boolean>() }
    var muscleFilter by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        try {
            val cat = repo.catalog()
            catalog = cat.values.sortedBy { it.name }
            val eq = repo.equipment()
            equipment = eq.payload
            prefs.clear()
            prefs.putAll(eq.payload.exercisePrefs)
        } catch (e: Exception) {
            Timber.w(e, "catalog load failed")
            error = e.message?.take(160)
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

    val visible by remember(catalog, equipment, search, activeCategories.toMap(), muscleFilter) {
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
            if (q.isEmpty()) base
            else base.mapNotNull { ex ->
                fuzzyScore(ex, q)?.let { s -> ex to s }
            }.sortedWith(compareByDescending<Pair<StrengthExerciseInfo, Int>> { it.second }
                .thenBy { it.first.name })
                .map { it.first }
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

    Column(modifier = Modifier.fillMaxSize().background(MV.Bg).padding(horizontal = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = MV.OnSurface)
            }
            Text(
                "Workout catalog",
                color = MV.OnSurface, fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            "⭐ favorite · 👎 avoid · 🚫 disabled · tap to toggle",
            color = MV.OnSurfaceDim, fontSize = 11.sp,
            modifier = Modifier.padding(start = 4.dp, bottom = 8.dp),
        )

        androidx.compose.material3.OutlinedTextField(
            value = search,
            onValueChange = { search = it },
            placeholder = { Text("Search by name, muscle, equipment…",
                fontSize = 13.sp, color = MV.OnSurfaceVariant) },
            singleLine = true,
            trailingIcon = if (search.isNotEmpty()) {
                {
                    IconButton(onClick = { search = "" }) {
                        Icon(Icons.Outlined.Close, contentDescription = "Clear",
                            tint = MV.OnSurfaceVariant)
                    }
                }
            } else null,
            modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
            textStyle = androidx.compose.ui.text.TextStyle(
                color = MV.OnSurface, fontSize = 14.sp,
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
                        .background(if (on) MV.BrandRed.copy(alpha = 0.18f) else MV.SurfaceContainer)
                        .border(1.dp,
                            if (on) MV.BrandRed.copy(alpha = 0.5f) else MV.OutlineVariant,
                            RoundedCornerShape(50))
                        .clickable {
                            activeCategories[key] = !(activeCategories[key] ?: false)
                        }
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Text(label,
                        color = if (on) MV.BrandRed else MV.OnSurfaceVariant,
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
                    color = MV.OnSurface, fontSize = 13.sp,
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

        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant)
            error != null -> Text(error!!, color = MV.Red)
            visible.isEmpty() && search.isNotBlank() -> Text(
                "No matches for \"$search\".",
                color = MV.OnSurfaceVariant,
            )
            visible.isEmpty() -> Text(
                "No available exercises — check your equipment in Settings.",
                color = MV.OnSurfaceVariant,
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
                                "favorite" -> MV.SurfaceContainerHigh
                                "disabled" -> MV.SurfaceContainerLow
                                else -> MV.SurfaceContainer
                            },
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .border(
                                width = if (pref != null) 2.dp else 0.dp,
                                color = when (pref) {
                                    "favorite" -> MV.Amber
                                    "disabled" -> MV.Red
                                    "avoid" -> MV.OnSurfaceVariant
                                    else -> Color.Transparent
                                },
                                shape = RoundedCornerShape(12.dp),
                            ),
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(ex.name, color = MV.OnSurface, fontSize = 14.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(
                                    "${ex.movementPattern.replace('_', ' ')} · ${ex.primaryMuscle} · ${ex.level}",
                                    color = MV.OnSurfaceVariant, fontSize = 11.sp,
                                )
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
                                    tint = MV.OnSurfaceVariant,
                                )
                            }
                            ActIcon(
                                icon = Icons.Filled.Star, on = pref == "favorite",
                                onColor = MV.Amber, onClick = { setPref(ex.id, "favorite") },
                            )
                            ActIcon(
                                icon = Icons.Filled.ThumbDown, on = pref == "avoid",
                                onColor = MV.OnSurfaceVariant, onClick = { setPref(ex.id, "avoid") },
                            )
                            ActIcon(
                                icon = Icons.Filled.Block, on = pref == "disabled",
                                onColor = MV.Red, onClick = { setPref(ex.id, "disabled") },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ActIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    on: Boolean, onColor: Color, onClick: () -> Unit,
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
            tint = if (on) onColor else MV.OnSurfaceVariant)
    }
}
