package app.myvitals.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.VitalTile

/**
 * A vitals tile with threshold semantics — phone twin of `VitalTiles.vue`.
 *
 * A bare "27 ms" can't be read without knowing the user's own normal and
 * which direction is better. Both arrive from `/summary/tiles`; nothing is
 * judged here, so this tile and the web grid can't tell different stories.
 *
 * When the server withholds a verdict — a reading too old to judge — the
 * value and its age still show, and the tile deliberately renders no pill
 * rather than a neutral-looking one that would imply a current assessment.
 */
@Composable
fun VitalTileCard(
    tile: VitalTile,
    palette: TilePalette,
    onClick: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val tone = statusTone(tile.status, palette)
    Column(
        modifier
            .fillMaxWidth()
            .background(palette.card, RoundedCornerShape(14.dp))
            .border(1.dp, tone.copy(alpha = 0.35f), RoundedCornerShape(14.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(12.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(tile.label, color = palette.muted, fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold)
            tile.status?.let {
                Text(
                    it.uppercase(), color = tone, fontSize = 9.sp,
                    fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp,
                )
            }
        }
        Spacer(Modifier.height(4.dp))

        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                tile.displayValue(), color = palette.ink,
                fontSize = 22.sp, fontWeight = FontWeight.Bold,
            )
            if (tile.unit.isNotBlank()) {
                Spacer(Modifier.width(3.dp))
                Text(tile.unit, color = palette.muted, fontSize = 10.sp,
                    modifier = Modifier.padding(bottom = 2.dp))
            }
        }

        Spacer(Modifier.height(6.dp))
        TileSparkline(
            tile.series.map { it.value },
            tone,
            Modifier.fillMaxWidth().height(30.dp),
        )

        tile.statusReason?.let {
            Spacer(Modifier.height(5.dp))
            Text(it, color = palette.muted, fontSize = 10.sp)
        }
    }
}

/** Card/text colours, so one tile serves the neon shell and the classic one. */
data class TilePalette(
    val card: Color, val line: Color, val ink: Color, val muted: Color,
    val good: Color, val warn: Color, val bad: Color,
)

private fun statusTone(status: String?, p: TilePalette): Color = when (status) {
    "good" -> p.good
    "typical" -> p.warn
    "watch" -> p.bad
    else -> p.muted
}

/**
 * Same geometry rules as the readiness sparkline: nulls are gaps, an
 * isolated reading draws as a dot rather than vanishing, and the whole
 * thing is inset so the endpoint marker isn't clipped.
 */
@Composable
private fun TileSparkline(
    points: List<Double?>,
    accent: Color,
    modifier: Modifier = Modifier,
) {
    val real = points.filterNotNull()
    // Fewer than two real points can't form a line, and drawing a flat one
    // would imply steady values the data doesn't show. Reserve the space so
    // tiles in a row stay the same height.
    if (real.size < 2) {
        Box(modifier)
        return
    }
    val min = real.min()
    val max = real.max()
    val span = (max - min).takeIf { it > 0.0001 } ?: 1.0
    Canvas(modifier) {
        val pad = 3f
        val stepX =
            if (points.size > 1) (size.width - pad * 2) / (points.size - 1) else 0f
        fun at(v: Double, i: Int) = Offset(
            pad + i * stepX,
            size.height - pad - ((v - min) / span).toFloat() * (size.height - pad * 2),
        )
        val path = Path()
        var started = false
        points.forEachIndexed { i, v ->
            if (v == null) { started = false; return@forEachIndexed }
            val o = at(v, i)
            if (points.getOrNull(i - 1) == null && points.getOrNull(i + 1) == null) {
                drawCircle(accent, radius = 2f, center = o)
            }
            if (!started) { path.moveTo(o.x, o.y); started = true } else path.lineTo(o.x, o.y)
        }
        drawPath(path, accent, style = Stroke(width = 2f))
        points.lastOrNull()?.let {
            drawCircle(accent, radius = 2.5f, center = at(it, points.size - 1))
        }
    }
}
