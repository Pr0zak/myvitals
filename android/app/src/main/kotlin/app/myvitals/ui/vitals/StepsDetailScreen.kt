package app.myvitals.ui.vitals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.DailySummary
import app.myvitals.ui.MV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun StepsDetailScreen(
    settings: SettingsRepository,
    onBack: () -> Unit,
    goal: Int = 10_000,
) {
    var rows by remember { mutableStateOf<List<DailySummary>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) { error = "Backend not configured."; loading = false; return@LaunchedEffect }
        try {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            val since = LocalDate.now().minusDays(29).toString()
            rows = withContext(Dispatchers.IO) { api.summaryRange(since = since) }
            Timber.i("steps detail: %d rows", rows.size)
        } catch (e: Exception) {
            Timber.w(e, "steps detail load failed")
            error = e.message?.take(160)
        } finally { loading = false }
    }

    val color = Vital.STEPS.color
    Column(Modifier.fillMaxSize().background(MV.Bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "Back",
                    tint = MV.OnSurface)
            }
            Text("Steps", color = MV.OnSurface, fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        when {
            loading -> Text("Loading…", color = MV.OnSurfaceVariant,
                modifier = Modifier.padding(16.dp))
            error != null -> Text(error!!, color = MV.Red, modifier = Modifier.padding(16.dp))
            else -> LazyColumn(
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item { TodayHero(rows.lastOrNull(), goal, color) }
                item { DailyColumns(rows, goal, color) }
                item { StepsStats(rows, goal) }
            }
        }
    }
}

@Composable
private fun TodayHero(today: DailySummary?, goal: Int, color: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("TODAY", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            val n = today?.stepsTotal ?: 0
            Text("%,d".format(n), color = MV.OnSurface,
                fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
            val pct = (n.toFloat() / goal.toFloat()).coerceAtLeast(0f).coerceAtMost(2f)
            Box(Modifier.fillMaxWidth().height(8.dp)
                .background(color.copy(alpha = 0.15f))) {
                Box(Modifier.fillMaxWidth(fraction = pct.coerceAtMost(1f)).height(8.dp)
                    .background(color))
            }
            Spacer(Modifier.height(4.dp))
            Text("${(pct * 100).toInt()}% of ${"%,d".format(goal)} goal",
                color = MV.OnSurfaceDim, fontSize = 11.sp)
        }
    }
}

@Composable
private fun DailyColumns(rows: List<DailySummary>, goal: Int, color: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("LAST 30 DAYS", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(8.dp))
            if (rows.isEmpty()) {
                Text("No data.", color = MV.OnSurfaceVariant, fontSize = 12.sp); return@Card
            }
            val maxV = (rows.maxOfOrNull { it.stepsTotal ?: 0 }
                ?.coerceAtLeast(goal) ?: goal).toFloat()
            Box(Modifier.fillMaxWidth().height(150.dp)) {
                Canvas(Modifier.fillMaxSize()) {
                    val gap = 2.dp.toPx()
                    val barW = (size.width - gap * (rows.size - 1)) / rows.size
                    // Goal dashed line
                    val gy = size.height - (goal / maxV) * size.height
                    drawLine(
                        color = color.copy(alpha = 0.4f),
                        start = Offset(0f, gy), end = Offset(size.width, gy),
                        strokeWidth = 1.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(
                            floatArrayOf(6.dp.toPx(), 4.dp.toPx())
                        ),
                    )
                    for ((i, r) in rows.withIndex()) {
                        val v = (r.stepsTotal ?: 0).toFloat()
                        val h = (v / maxV) * size.height
                        val barColor = if (v >= goal) color
                                       else color.copy(alpha = 0.55f)
                        drawRect(
                            color = barColor,
                            topLeft = Offset(i * (barW + gap), size.height - h),
                            size = Size(barW, h),
                        )
                    }
                }
            }
            Row(Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                rows.firstOrNull()?.date?.let {
                    Text(shortDay(it), color = MV.OnSurfaceDim, fontSize = 9.sp)
                }
                rows.lastOrNull()?.date?.let {
                    Text(shortDay(it), color = MV.OnSurfaceDim, fontSize = 9.sp)
                }
            }
        }
    }
}

@Composable
private fun StepsStats(rows: List<DailySummary>, goal: Int) {
    val totals = rows.mapNotNull { it.stepsTotal }
    val total = totals.sum()
    val avg = if (totals.isNotEmpty()) totals.average() else 0.0
    val daysHit = totals.count { it >= goal }
    Card(colors = CardDefaults.cardColors(containerColor = MV.SurfaceContainer)) {
        Column(Modifier.padding(14.dp)) {
            Text("STATS", color = MV.OnSurfaceVariant,
                fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                StatPair("Total", "%,d".format(total))
                StatPair("Daily avg", "%,.0f".format(avg))
                StatPair("Days ≥ goal", "$daysHit/${rows.size}")
            }
        }
    }
}

@Composable
private fun StatPair(label: String, value: String) {
    Column {
        Text(label, color = MV.OnSurfaceDim, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = MV.OnSurface, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}

private fun shortDay(iso: String): String =
    runCatching {
        val d = LocalDate.parse(iso)
        DateTimeFormatter.ofPattern("M/d").format(d)
    }.getOrDefault(iso)
