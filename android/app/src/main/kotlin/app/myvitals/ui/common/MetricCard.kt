package app.myvitals.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * The metric card — phone twin of `MetricCard.vue`.
 *
 * ONE card vocabulary for every metric, which is the whole point: the app
 * had five different card styles and that is what made it feel like five
 * apps stitched together. Layout, wording and geometry are kept identical
 * to the web card deliberately.
 *
 *   name          small, quiet
 *   VALUE unit    large, LIGHT weight — a bold value makes a grid of these
 *                 read as a spreadsheet
 *   qualifier     "Today", "Today • 9,038 to go", or the reading's date
 *   chart         7 days, full width, weekday letters with today chipped,
 *                 shaded "your normal" band, dotted goal line
 *   chip          filled "In range" / "Goal not met" / "No data"
 *
 * Missing data renders LARGE in the value slot rather than as a dash, so
 * absence reads as a state instead of a failed render.
 *
 * Nothing is judged here — status, baseline and target all arrive from
 * `/summary/tiles`.
 */
@Composable
fun MetricCard(
    name: String,
    value: String?,
    unit: String,
    qualifier: String,
    series: List<Double?>,
    dayLetters: List<String>,
    modifier: Modifier = Modifier,
    status: String? = null,
    statusLabel: String? = null,
    bandLow: Double? = null,
    bandHigh: Double? = null,
    target: Double? = null,
    bars: Boolean = false,
    /** Trailing points to plot; intermittent metrics pass 14. */
    span: Int = WEEK,
    accent: Color = Color(0xFF7EE2A8),
    onClick: (() -> Unit)? = null,
) {
    val hasData = value != null
    val chip = chipFor(hasData, status, statusLabel)

    Column(
        modifier
            .fillMaxWidth()
            .background(Color(0xFF1B1C1F), RoundedCornerShape(20.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 12.dp),
    ) {
        Text(
            name, color = Color(0xFFB9BEC6), fontSize = 12.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.height(6.dp))

        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                value ?: "No data",
                color = Color(0xFFE9EDF2),
                // Light weight is the reference's most recognisable trait.
                fontWeight = FontWeight.Light,
                fontSize = if (hasData) 30.sp else 23.sp,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            if (hasData && unit.isNotBlank()) {
                Spacer(Modifier.width(4.dp))
                Text(
                    unit, color = Color(0xFFB9BEC6), fontSize = 13.sp,
                    modifier = Modifier.padding(bottom = 3.dp),
                )
            }
        }

        if (qualifier.isNotBlank()) {
            Text(qualifier, color = Color(0xFF8D949D), fontSize = 11.sp,
                maxLines = 2, overflow = TextOverflow.Ellipsis)
        }

        Spacer(Modifier.height(10.dp))
        WeekChart(
            points = series.takeLast(span),
            accent = accent,
            bandLow = bandLow,
            bandHigh = bandHigh,
            target = target,
            bars = bars,
            modifier = Modifier.fillMaxWidth().height(40.dp),
        )
        Spacer(Modifier.height(3.dp))
        WeekAxis(dayLetters.takeLast(span))

        if (chip != null) {
            Spacer(Modifier.height(10.dp))
            Box(
                Modifier
                    .background(chip.bg, RoundedCornerShape(999.dp))
                    .padding(horizontal = 9.dp, vertical = 3.dp),
            ) {
                Text(chip.text, color = chip.fg, fontSize = 10.sp,
                    fontWeight = FontWeight.Medium)
            }
        }
    }
}

private const val WEEK = 7

private data class Chip(val fg: Color, val bg: Color, val text: String)

/** Every card carries a chip; an empty metric shows "No data" rather than
 *  nothing, matching the reference. */
private fun chipFor(hasData: Boolean, status: String?, label: String?): Chip? {
    if (!hasData) {
        return Chip(Color(0xFF8D949D), Color(0x1F8D949D), "No data")
    }
    return when (status) {
        "good" -> Chip(Color(0xFF7EE2A8), Color(0x247EE2A8), label ?: "In range")
        "typical" -> Chip(Color(0xFFC7CBD1), Color(0x1FC7CBD1), label ?: "In range")
        "watch" -> Chip(Color(0xFFE8B661), Color(0x24E8B661), label ?: "Out of range")
        else -> null
    }
}

/** Weekday initials with today emphasised, so the chart is anchored in real
 *  time instead of being an abstract squiggle. */
@Composable
private fun WeekAxis(days: List<String>) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        // At 14 points the weekday letters collide; label alternate days.
        val every = if (days.size > 8) 2 else 1
        days.forEachIndexed { i, d ->
            val today = i == days.size - 1
            val label = if (i % every == 0 || today) d else ""
            Box(
                Modifier
                    .then(
                        if (today) Modifier.background(
                            Color(0xFFB9BEC6), RoundedCornerShape(999.dp),
                        ) else Modifier,
                    )
                    .padding(horizontal = 4.dp),
            ) {
                Text(
                    label,
                    color = if (today) Color(0xFF0D0F12) else Color(0xFF6F767F),
                    fontSize = 9.sp,
                    fontWeight = if (today) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
        }
    }
}

@Composable
private fun WeekChart(
    points: List<Double?>,
    accent: Color,
    bandLow: Double?,
    bandHigh: Double?,
    target: Double?,
    bars: Boolean,
    modifier: Modifier = Modifier,
) {
    val real = points.filterNotNull()
    val extras = listOfNotNull(bandLow, bandHigh, target)
    if (real.isEmpty() && extras.isEmpty()) {
        // Nothing to draw at all — reserve the space so a metric with no
        // readings still lines up with one that has them.
        Box(modifier)
        return
    }
    // With no readings this week but a band or goal known, the web still
    // paints them; bailing early here made the two cards disagree about
    // whether a metric HAS a normal range.
    val all = real + extras
    var lo = all.min()
    var hi = all.max()
    if (hi - lo < 1e-6) { lo -= 1.0; hi += 1.0 }
    val pad = (hi - lo) * 0.18
    lo -= pad; hi += pad

    Canvas(modifier) {
        // Geometry in dp. Raw DrawScope floats are physical pixels, so on a
        // 2.75x-density phone these strokes came out ~1/3 the weight of the
        // web card's — every other constant in this file is already matched
        // in dp/sp.
        val px = density
        fun y(v: Double) = size.height - ((v - lo) / (hi - lo)).toFloat() * size.height
        val stepX = if (points.size > 1) size.width / (points.size - 1) else size.width

        // Only when there is a series to reference — otherwise the band
        // and the goal line float over an empty chart on a scale nothing
        // grounds, and always land dead centre.
        val plottable = real.isNotEmpty()
        if (plottable && bandLow != null && bandHigh != null) {
            val top = y(bandHigh)
            val bot = y(bandLow)
            drawRect(
                accent.copy(alpha = 0.10f),
                topLeft = Offset(0f, minOf(top, bot)),
                size = Size(size.width, kotlin.math.abs(bot - top)),
            )
        }
        if (plottable) target?.let { t ->
            drawLine(
                accent.copy(alpha = 0.55f),
                Offset(0f, y(t)), Offset(size.width, y(t)),
                strokeWidth = 1f * px,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(2f * px, 3f * px)),
            )
        }

        if (bars) {
            val bw = maxOf(4f * px, size.width / (points.size * 2f))
            points.forEachIndexed { i, v ->
                if (v == null) return@forEachIndexed
                val top = y(v)
                drawRoundRect(
                    accent.copy(alpha = if (i == points.size - 1) 1f else 0.45f),
                    topLeft = Offset(i * stepX - bw / 2, top),
                    size = Size(bw, size.height - top),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(2f * px, 2f * px),
                )
            }
        } else {
            val path = Path()
            var started = false
            points.forEachIndexed { i, v ->
                if (v == null) { started = false; return@forEachIndexed }
                val o = Offset(i * stepX, y(v))
                if (!started) { path.moveTo(o.x, o.y); started = true } else path.lineTo(o.x, o.y)
            }
            drawPath(path, accent, style = Stroke(width = 1.6f * px))
            points.forEachIndexed { i, v ->
                if (v == null) return@forEachIndexed
                val last = i == points.size - 1
                drawCircle(
                    accent.copy(alpha = if (last) 1f else 0.75f),
                    radius = if (last) 3.2f * px else 2.2f * px,
                    center = Offset(i * stepX, y(v)),
                )
            }
        }
    }
}
