package app.myvitals.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.SettingsRepository
import app.myvitals.sync.BackendClient
import app.myvitals.sync.TrainingLoad
import app.myvitals.ui.neon.NeonMV
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * Weekly training load against a personal target band — phone twin of
 * `WeeklyLoad.vue`.
 *
 * Google Health dropped daily cardio goals for weekly load targets, on the
 * grounds that a daily number punishes an ordinary rest day. This is that idea
 * in the units this app already computes.
 *
 * Nothing is judged here. The band, the verdict and the daily breakdown all
 * arrive from `/summary/training-load`, so this card and the web one cannot
 * disagree about the same week.
 */
@Composable
fun WeeklyLoad(settings: SettingsRepository, modifier: Modifier = Modifier) {
    var data by remember { mutableStateOf<TrainingLoad?>(null) }

    LaunchedEffect(Unit) {
        if (!settings.isConfigured()) return@LaunchedEffect
        runCatching {
            val api = BackendClient.create(settings.backendUrl, settings.bearerToken)
            withContext(Dispatchers.IO) { api.trainingLoad() }
        }.onSuccess { data = it }
            .onFailure { Timber.w(it, "training load load failed") }
    }

    val d = data ?: return
    val tone = when (d.band) {
        "under" -> NeonMV.Cyan
        "optimal" -> NeonMV.Lime
        "overreaching" -> NeonMV.Amber
        else -> NeonMV.Muted
    }
    val verdict = when (d.band) {
        "under" -> "Below your usual load"
        "optimal" -> "In your usual range"
        "overreaching" -> "Above your usual load"
        else -> "Not enough history yet"
    }

    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(NeonMV.Card)
            .border(1.dp, tone.copy(alpha = 0.22f), RoundedCornerShape(20.dp))
            .padding(14.dp),
    ) {
        Text(
            "TRAINING LOAD · THIS WEEK", color = NeonMV.Muted,
            fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp,
        )
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "%.0f".format(d.weekLoad), color = NeonMV.Ink,
                fontSize = 38.sp, fontWeight = FontWeight.Bold, letterSpacing = (-1.6).sp,
            )
            if (d.targetLow != null && d.targetHigh != null) {
                Spacer(Modifier.width(8.dp))
                Text(
                    "of %.0f–%.0f".format(d.targetLow, d.targetHigh),
                    color = NeonMV.Muted, fontSize = 13.sp,
                    modifier = Modifier.padding(bottom = 5.dp),
                )
            }
        }
        Text(verdict, color = tone, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)

        // Per-day bars, scaled to the busiest day so a quiet week still reads.
        val peak = (d.daily.maxOfOrNull { it.load } ?: 0.0).coerceAtLeast(1.0)
        Spacer(Modifier.height(12.dp))
        Canvas(Modifier.fillMaxWidth().height(54.dp)) {
            val n = d.daily.size.coerceAtLeast(1)
            val gap = 4.dp.toPx()
            val w = (size.width - gap * (n - 1)) / n
            d.daily.forEachIndexed { i, day ->
                val h = ((day.load / peak).toFloat() * size.height).coerceAtLeast(3f)
                drawRoundRect(
                    color = if (day.load > 0) tone else tone.copy(alpha = 0.28f),
                    topLeft = Offset(i * (w + gap), size.height - h),
                    size = Size(w, h),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(
                        3.dp.toPx(), 3.dp.toPx(),
                    ),
                )
            }
        }
        Spacer(Modifier.height(4.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            d.daily.forEach { day ->
                Text(
                    dayLetter(day.date), color = NeonMV.Muted, fontSize = 10.sp,
                    modifier = Modifier.weight(1f),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
            }
        }

        if (d.targetLow != null && d.targetHigh != null) {
            Spacer(Modifier.height(12.dp))
            // The band, with a marker for where the week actually sits. Scale
            // runs to 1.6x the top of the band so "over" has somewhere to go.
            val full = (d.targetHigh * 1.6).coerceAtLeast(1.0)
            Canvas(Modifier.fillMaxWidth().height(18.dp)) {
                val trackY = size.height / 2f
                val trackH = 8.dp.toPx()
                drawRoundRect(
                    color = NeonMV.Track,
                    topLeft = Offset(0f, trackY - trackH / 2),
                    size = Size(size.width, trackH),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(999f, 999f),
                )
                val x0 = (d.targetLow / full).toFloat() * size.width
                val x1 = (d.targetHigh / full).toFloat() * size.width
                drawRoundRect(
                    color = NeonMV.Lime.copy(alpha = 0.45f),
                    topLeft = Offset(x0, trackY - trackH / 2),
                    size = Size((x1 - x0).coerceAtLeast(1f), trackH),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(999f, 999f),
                )
                val mx = ((d.weekLoad / full).toFloat().coerceIn(0f, 1f)) * size.width
                drawRoundRect(
                    color = NeonMV.Ink,
                    topLeft = Offset(mx - 1.5.dp.toPx(), 0f),
                    size = Size(3.dp.toPx(), size.height),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(2f, 2f),
                )
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("under", color = NeonMV.Muted, fontSize = 9.sp)
                Text("your usual range", color = NeonMV.Muted, fontSize = 9.sp)
                Text("over", color = NeonMV.Muted, fontSize = 9.sp)
            }
        }
    }
}

private val DOW = listOf("S", "M", "T", "W", "T", "F", "S")

private fun dayLetter(iso: String): String = runCatching {
    DOW[java.time.LocalDate.parse(iso).dayOfWeek.value % 7]
}.getOrDefault("")
