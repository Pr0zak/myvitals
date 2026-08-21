package app.myvitals.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.data.Units
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DaySnapshot
import app.myvitals.ui.common.DayNav
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * DAY-1 — everything about one calendar day (phone half).
 *
 * Mirrors `frontend/src/views/Day.vue`. Both read the single
 * `GET /summary/day` call, whose sections are independently best-effort
 * server-side: one failing subsystem arrives as null rather than taking
 * the page down.
 *
 * Null is rendered as "couldn't load", never as zero. Showing 0 steps for
 * a day whose step query failed is a lie the reader has no way to detect,
 * and on a health record that matters more than it would elsewhere.
 */
@Composable
fun DayScreen(
    settings: SettingsRepository,
    initialDate: String?,
    onBack: () -> Unit,
    onOpenActivity: (String, String) -> Unit = { _, _ -> },
    onOpenWorkout: () -> Unit = {},
) {
    val neon = settings.neonShellEnabled
    val bg = if (neon) NeonMV.Bg else MV.Bg
    val ink = if (neon) NeonMV.Ink else MV.OnSurface
    val muted = if (neon) NeonMV.Muted else MV.OnSurfaceVariant
    val card = if (neon) NeonMV.Card else MV.SurfaceContainer
    val bad = if (neon) NeonMV.Bad else MV.Red
    val warn = if (neon) NeonMV.Amber else Color(0xFFF59E0B)

    // A malformed or missing route argument resolves to today rather than
    // being forwarded to the API as though it were a date.
    var day by remember {
        mutableStateOf(
            runCatching { LocalDate.parse(initialDate) }.getOrElse { LocalDate.now() },
        )
    }
    var snap by remember { mutableStateOf<DaySnapshot?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(day) {
        loading = true
        error = null
        if (!settings.isConfigured()) { loading = false; return@LaunchedEffect }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            snap = withContext(Dispatchers.IO) { api.summaryDay(day.toString()) }
        } catch (e: Exception) {
            Timber.w(e, "day snapshot failed for %s", day)
            error = e.message?.take(160) ?: "Couldn't load this day."
            snap = null
        } finally {
            loading = false
        }
    }

    val headerFmt = remember { DateTimeFormatter.ofPattern("EEEE, MMM d") }

    Column(Modifier.fillMaxSize().background(bg).padding(horizontal = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = ink)
            }
            Text(
                day.format(headerFmt), color = ink,
                fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
            )
        }

        DayNav(
            selected = day,
            onSelectedChange = { day = it },
            modifier = Modifier.padding(vertical = 8.dp),
        )

        when {
            loading -> Text("Loading…", color = muted, modifier = Modifier.padding(4.dp))
            error != null -> Text(error!!, color = bad, modifier = Modifier.padding(4.dp))
            snap == null -> Text("No data.", color = muted, modifier = Modifier.padding(4.dp))
            else -> {
                val s = snap!!
                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item {
                        DaySection("At a glance", card, muted) {
                            Row(
                                Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                // sumOf over the raw points, not a stored
                                // column: the day view never triggers the
                                // stale-row repair, so the column may be
                                // older than the samples.
                                val stepTotal = s.steps?.points?.sumOf { it.value }?.toLong()
                                DayStat(
                                    stepTotal?.toString() ?: "—", "steps",
                                    ink, muted, warn, failed = s.steps == null,
                                )
                                val night = s.sleep?.lastOrNull()
                                DayStat(
                                    night?.let { fmtDur(it.totalS.toLong()) } ?: "—", "sleep",
                                    ink, muted, warn, failed = s.sleep == null,
                                )
                                DayStat(
                                    (s.activities?.size ?: 0).toString(), "activities",
                                    ink, muted, warn, failed = s.activities == null,
                                )
                                DayStat(
                                    if (s.workout != null) "1" else "0", "workout",
                                    ink, muted, warn, failed = false,
                                )
                            }
                        }
                    }

                    s.tiles?.tiles?.takeIf { it.isNotEmpty() }?.let { tiles ->
                        item {
                            DaySection("Metrics", card, muted) {
                                for (t in tiles) {
                                    Row(
                                        Modifier.fillMaxWidth().padding(vertical = 3.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                    ) {
                                        Text(t.label, color = muted, fontSize = 13.sp)
                                        Text(
                                            buildString {
                                                append(t.value?.toString() ?: "—")
                                                t.unit?.takeIf { it.isNotBlank() }
                                                    ?.let { append(" $it") }
                                            },
                                            color = ink, fontSize = 13.sp,
                                        )
                                    }
                                }
                            }
                        }
                    }

                    s.workout?.let { w ->
                        item {
                            DaySection("Workout", card, muted) {
                                Row(
                                    Modifier.fillMaxWidth().clickable { onOpenWorkout() },
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                ) {
                                    Text(
                                        (w.splitFocus ?: "strength")
                                            .replaceFirstChar { it.uppercase() },
                                        color = ink, fontSize = 14.sp,
                                    )
                                    Text(w.status, color = muted, fontSize = 11.sp)
                                }
                                w.notes?.takeIf { it.isNotBlank() }?.let {
                                    Text(it, color = muted, fontSize = 11.sp,
                                        modifier = Modifier.padding(top = 4.dp))
                                }
                            }
                        }
                    }

                    s.activities?.takeIf { it.isNotEmpty() }?.let { acts ->
                        items(acts) { a ->
                            DaySection(null, card, muted) {
                                Column(
                                    Modifier.fillMaxWidth().clickable {
                                        onOpenActivity(a.source, a.sourceId)
                                    },
                                ) {
                                    Text(a.name ?: a.type, color = ink, fontSize = 14.sp)
                                    Text(
                                        buildString {
                                            append(fmtDur(a.durationS))
                                            a.distanceM?.let {
                                                append(" · ${Units.fmtDistance(it, 1)}")
                                            }
                                        },
                                        color = muted, fontSize = 11.sp,
                                    )
                                }
                            }
                        }
                    }
                    item { Spacer(Modifier.height(16.dp)) }
                }
            }
        }
    }
}

private fun fmtDur(seconds: Long?): String {
    if (seconds == null) return "—"
    val h = seconds / 3600
    val m = ((seconds % 3600) + 30) / 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}

@Composable
private fun DayStat(
    value: String, label: String, ink: Color, muted: Color, warn: Color, failed: Boolean,
) {
    Column {
        Text(value, color = ink, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        Text(label, color = muted, fontSize = 10.sp)
        // A failed section is not an empty one, and the difference is not
        // recoverable from the number alone.
        if (failed) Text("couldn't load", color = warn, fontSize = 9.sp)
    }
}

@Composable
private fun DaySection(
    title: String?, card: Color, muted: Color, content: @Composable () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(card)
            .padding(14.dp),
    ) {
        title?.let {
            Text(it.uppercase(), color = muted, fontSize = 10.sp,
                fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
            Spacer(Modifier.height(8.dp))
        }
        content()
    }
}
