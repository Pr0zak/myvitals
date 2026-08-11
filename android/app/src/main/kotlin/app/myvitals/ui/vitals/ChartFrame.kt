package app.myvitals.ui.vitals

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.pow

/**
 * Shared axis furniture for the hand-rolled Canvas charts on the detail
 * screens.
 *
 * Every one of those charts drew a bare line or bar run edge-to-edge with no
 * gridlines and no labels, so you could see the *shape* of a metric but never
 * read a value off it. Worse, several scaled the y-axis to the data's own
 * min..max, which silently turns a 3 bpm wobble into a chart that looks like a
 * cliff — the axis is what tells you whether a swing is big.
 *
 * This is deliberately a drawing kit rather than a chart component: the
 * existing charts each draw something different (line, bars, hypnogram,
 * histogram) and only need the frame around it to agree.
 *
 * Usage:
 * ```
 * val g = chartGeom(domain, insets = ChartInsets(left = 30.dp.toPx(), ...))
 * drawGrid(g, measurer, tok.onSurfaceDim, tok.onSurface) { "%.0f".format(it) }
 * // ...draw the series against g.y(v) / g.x(i, n)...
 * ```
 */

/** A y-domain rounded outward to human numbers, plus the tick values on it. */
data class ChartDomain(val min: Float, val max: Float, val ticks: List<Float>) {
    val span: Float get() = (max - min).coerceAtLeast(1e-6f)
}

/** Space reserved inside the Canvas for the axis furniture, in px. */
data class ChartInsets(
    val left: Float = 0f,
    val top: Float = 0f,
    val right: Float = 0f,
    val bottom: Float = 0f,
)

/** The plot rectangle plus value→pixel mapping. */
class ChartGeom(
    val left: Float,
    val top: Float,
    val right: Float,
    val bottom: Float,
    val domain: ChartDomain,
) {
    val width: Float get() = (right - left).coerceAtLeast(1f)
    val height: Float get() = (bottom - top).coerceAtLeast(1f)

    /** Value → y pixel, clamped so an out-of-domain value can't draw off-plot. */
    fun y(v: Float): Float =
        bottom - ((v.coerceIn(domain.min, domain.max) - domain.min) / domain.span) * height

    /** Value → y pixel WITHOUT clamping (for band edges you intend to clip). */
    fun yRaw(v: Float): Float = bottom - ((v - domain.min) / domain.span) * height

    /** Index → x pixel for a line series (first point on the left edge). */
    fun x(i: Int, n: Int): Float =
        if (n <= 1) left else left + (i.toFloat() / (n - 1)) * width

    /** Index → x pixel for the CENTRE of a bar in an n-slot bar chart. */
    fun xBar(i: Int, n: Int): Float =
        if (n <= 0) left else left + ((i + 0.5f) / n) * width

    /** Slot width for an n-slot bar chart. */
    fun slot(n: Int): Float = if (n <= 0) width else width / n
}

fun DrawScope.chartGeom(domain: ChartDomain, insets: ChartInsets): ChartGeom =
    ChartGeom(
        left = insets.left,
        top = insets.top,
        right = size.width - insets.right,
        bottom = size.height - insets.bottom,
        domain = domain,
    )

/**
 * Round [lo]..[hi] outward to a "nice" step and place ticks on it.
 *
 * [includeLo] / [includeHi] force extra values inside the domain. That is how
 * the server's normal band gets drawn whole: when the band is wider than the
 * data (common on a 7-day window) an unforced domain clips it, and a band
 * clipped at the top edge reads as "every reading is abnormal" when the truth
 * is the opposite.
 *
 * [zeroAnchored] pins the bottom of the domain at zero — right for counts
 * (steps, sample bins) where the bar length IS the quantity, wrong for
 * physiology (a resting-HR chart from 0 is a flat line at the top).
 */
fun niceDomain(
    lo: Float,
    hi: Float,
    includeLo: Float? = null,
    includeHi: Float? = null,
    targetTicks: Int = 4,
    zeroAnchored: Boolean = false,
    padFraction: Float = 0.12f,
): ChartDomain {
    var dLo = minOf(lo, includeLo ?: lo)
    var dHi = maxOf(hi, includeHi ?: hi)
    if (dHi < dLo) { val t = dLo; dLo = dHi; dHi = t }

    // A flat series still needs a domain with height, or every point lands on
    // one pixel row and the line vanishes into the axis.
    if (abs(dHi - dLo) < 1e-6f) {
        val bump = if (abs(dHi) < 1e-6f) 1f else abs(dHi) * 0.05f
        dLo -= bump; dHi += bump
    }

    val pad = (dHi - dLo) * padFraction
    var rawLo = if (zeroAnchored) 0f else dLo - pad
    var rawHi = dHi + pad
    if (zeroAnchored && rawHi <= 0f) rawHi = 1f

    val step = niceStep((rawHi - rawLo) / targetTicks.coerceAtLeast(1))
    val min = if (zeroAnchored) 0f else floor(rawLo / step) * step
    val max = ceil(rawHi / step) * step

    val ticks = buildList {
        var t = min
        // Guard the loop on a count as well as the bound: float accumulation
        // over a tiny step can otherwise run away.
        var guard = 0
        while (t <= max + step * 0.001f && guard < 24) {
            add(t); t += step; guard++
        }
    }
    return ChartDomain(min, max, ticks)
}

/** 1 / 2 / 2.5 / 5 × 10^n — the steps people actually read axes in. */
private fun niceStep(rough: Float): Float {
    if (rough <= 0f || !rough.isFinite()) return 1f
    val mag = 10f.pow(floor(log10(rough.toDouble())).toFloat())
    val norm = rough / mag
    val mult = when {
        norm <= 1f -> 1f
        norm <= 2f -> 2f
        norm <= 2.5f -> 2.5f
        norm <= 5f -> 5f
        else -> 10f
    }
    return mult * mag
}

private fun axisStyle(color: Color) = TextStyle(
    color = color, fontSize = 9.sp, fontWeight = FontWeight.Medium,
)

/**
 * Horizontal gridlines with right-aligned value labels in the left gutter.
 *
 * Ticks whose label would collide with the neighbour are skipped rather than
 * overprinted — an unreadable axis is worse than a sparse one.
 */
fun DrawScope.drawGrid(
    g: ChartGeom,
    measurer: TextMeasurer,
    labelColor: Color,
    gridColor: Color,
    maxLabels: Int = 5,
    format: (Float) -> String,
) {
    val ticks = g.domain.ticks
    if (ticks.isEmpty()) return
    // Thin the ticks so labels never touch: keep every k-th.
    val k = ceil(ticks.size / maxLabels.toFloat()).toInt().coerceAtLeast(1)
    val style = axisStyle(labelColor)
    for ((i, t) in ticks.withIndex()) {
        if (t < g.domain.min - 1e-3f || t > g.domain.max + 1e-3f) continue
        // Only labelled ticks get a line. A minor gridline with no number
        // beside it is just a stray rule across the card — at the top of the
        // domain it reads as a rendering artefact rather than a scale.
        val show = i % k == 0
        if (!show) continue
        val y = g.y(t)
        drawLine(
            color = gridColor.copy(alpha = 0.16f),
            start = Offset(g.left, y), end = Offset(g.right, y),
            strokeWidth = 1f,
        )
        if (g.left <= 1f) continue
        val lay: TextLayoutResult = measurer.measure(format(t), style)
        drawText(
            lay,
            topLeft = Offset(
                (g.left - 4f - lay.size.width).coerceAtLeast(0f),
                y - lay.size.height / 2f,
            ),
        )
    }
}

/**
 * The server's "your normal" band, drawn whole with dashed edges.
 *
 * Pair this with [niceDomain]'s include args. Drawn as a soft fill in the
 * series colour rather than grey: grey at low alpha over a dark card reads as
 * a rendering artefact — a tinted band reads as information.
 */
fun DrawScope.drawNormalBand(
    g: ChartGeom,
    low: Float,
    high: Float,
    color: Color,
    measurer: TextMeasurer? = null,
    label: String? = null,
    labelColor: Color = color,
) {
    val top = g.y(maxOf(low, high))
    val bot = g.y(minOf(low, high))
    if (bot - top < 0.5f) return
    drawRect(
        color = color.copy(alpha = 0.10f),
        topLeft = Offset(g.left, top),
        size = Size(g.width, bot - top),
    )
    val dash = PathEffect.dashPathEffect(floatArrayOf(px(5f), px(4f)))
    for (y in listOf(top, bot)) {
        drawLine(
            color = color.copy(alpha = 0.30f),
            start = Offset(g.left, y), end = Offset(g.right, y),
            strokeWidth = 1f, pathEffect = dash,
        )
    }
    if (label != null && measurer != null && bot - top > px(14f)) {
        val lay = measurer.measure(
            label, TextStyle(color = labelColor.copy(alpha = 0.75f), fontSize = 8.sp),
        )
        drawText(
            lay,
            topLeft = Offset(g.right - lay.size.width - px(3f), top + px(2f)),
        )
    }
}

/** X labels in the bottom gutter, placed by plot fraction (0 = left edge). */
fun DrawScope.drawXLabels(
    g: ChartGeom,
    measurer: TextMeasurer,
    labelColor: Color,
    labels: List<Pair<Float, String>>,
) {
    if (labels.isEmpty()) return
    val style = axisStyle(labelColor)
    for ((frac, text) in labels) {
        val lay = measurer.measure(text, style)
        // Clamp into the plot so the first/last labels don't hang off the card.
        val x = (g.left + frac * g.width - lay.size.width / 2f)
            .coerceIn(0f, size.width - lay.size.width)
        drawText(lay, topLeft = Offset(x, g.bottom + px(4f)))
    }
}

/**
 * A dashed bridge across a gap in a series.
 *
 * Without it a single missing day splits the line into disconnected fragments
 * — and a lone floating dot for "today" looks like a bug rather than a day
 * that follows a day with no reading.
 */
fun DrawScope.drawGapBridge(from: Offset, to: Offset, color: Color) {
    drawLine(
        color = color.copy(alpha = 0.35f),
        start = from, end = to,
        strokeWidth = px(1.5f),
        pathEffect = PathEffect.dashPathEffect(floatArrayOf(px(3f), px(3f))),
    )
}

/** The latest reading, marked so it reads as "now" rather than "an endpoint". */
fun DrawScope.drawLatestMarker(center: Offset, color: Color, ringColor: Color) {
    drawCircle(color = color.copy(alpha = 0.22f), radius = px(6f), center = center)
    drawCircle(color = ringColor, radius = px(3.6f), center = center)
    drawCircle(color = color, radius = px(2.4f), center = center)
}

/** Rounded-top bar — the shape every bar chart here draws. */
fun DrawScope.drawBar(
    g: ChartGeom,
    centerX: Float,
    barWidth: Float,
    top: Float,
    color: Color,
) {
    val h = (g.bottom - top).coerceAtLeast(0f)
    if (h <= 0f) return
    val r = minOf(barWidth / 2f, px(3f), h)
    drawRoundRect(
        color = color,
        topLeft = Offset(centerX - barWidth / 2f, top),
        size = Size(barWidth, h),
        cornerRadius = androidx.compose.ui.geometry.CornerRadius(r, r),
    )
}

/** A reference line (goal, mean, baseline) with an optional right-edge label. */
fun DrawScope.drawReferenceLine(
    g: ChartGeom,
    value: Float,
    color: Color,
    measurer: TextMeasurer? = null,
    label: String? = null,
) {
    if (value < g.domain.min || value > g.domain.max) return
    val y = g.y(value)
    drawLine(
        color = color.copy(alpha = 0.55f),
        start = Offset(g.left, y), end = Offset(g.right, y),
        strokeWidth = px(1f),
        pathEffect = PathEffect.dashPathEffect(floatArrayOf(px(6f), px(4f))),
    )
    if (label != null && measurer != null) {
        val lay = measurer.measure(
            label, TextStyle(color = color.copy(alpha = 0.9f), fontSize = 8.sp),
        )
        drawText(
            lay,
            topLeft = Offset(
                (g.right - lay.size.width).coerceAtLeast(g.left),
                (y - lay.size.height - px(1f)).coerceAtLeast(g.top),
            ),
        )
    }
}

/** Stroke helper so call sites stay short. */
fun strokeOf(widthPx: Float): Stroke = Stroke(width = widthPx)

/** dp→px inside a DrawScope, without threading a Density through every call. */
private fun DrawScope.px(dp: Float): Float = dp * density
