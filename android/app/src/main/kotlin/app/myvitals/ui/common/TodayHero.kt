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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import app.myvitals.ui.neon.NeonMV
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.VitalTile
import app.myvitals.sync.WeekProgress

/**
 * Today hero — phone twin of `TodayHero.vue`.
 *
 * A weekly progress ring beside a stack of SATURATED chips, then an action
 * row. The fill is the point: that saturation against the dark ground is
 * what makes the reference's hero read as a hero rather than three more
 * cards, and it lets everything below it stay quiet by comparison.
 *
 * Weekly progress is summed server-side against seven days of the user's
 * own daily goal — not an invented weekly target.
 */
@Composable
fun TodayHero(
    tiles: List<VitalTile>,
    week: WeekProgress?,
    readiness: Double?,
    onOpen: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    fun tile(key: String) = tiles.firstOrNull { it.key == key }

    fun display(key: String): String {
        val t = tile(key) ?: return "—"
        val v = (t.value as? Number)?.toDouble() ?: return t.value?.toString() ?: "—"
        return when (key) {
            "steps" -> "%,d".format(v.toLong())
            "sleep_duration" -> {
                val h = v.toInt()
                val m = Math.round((v - h) * 60).toInt()
                "${h}h ${m}m"
            }
            else -> "%.0f".format(v)
        }
    }

    Column(modifier.fillMaxWidth().padding(bottom = 18.dp)) {
        // IntrinsicSize.Min lets the ring card take the row's height instead of
        // a fixed 168dp. With three chips beside it the chips column is taller,
        // so the ring card stopped short and left a notch of background beside
        // the last chip. The web flexbox already did this via align-self.
        Row(
            Modifier.height(IntrinsicSize.Min),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Ring
            Box(
                Modifier
                    .width(168.dp)
                    .fillMaxHeight()
                    .background(NeonMV.Card, RoundedCornerShape(22.dp))
                    .border(1.dp, NeonMV.Lime.copy(alpha = 0.22f), RoundedCornerShape(22.dp))
                    .clickable { onOpen("vitals/STEPS") },
                contentAlignment = Alignment.Center,
            ) {
                val pct = (week?.pct ?: 0.0).coerceIn(0.0, 100.0)
                // 10dp, not 18: the card now fills the row height, so the arc —
                // sized to min(w,h) — was left floating small with a deep
                // margin above and below it.
                Canvas(Modifier.fillMaxSize().padding(10.dp)) {
                    val stroke = 11.dp.toPx()
                    // Draw into a centred SQUARE. The card now fills the row's
                    // height (taller than it is wide once there are three
                    // chips beside it), and an arc sized to the full canvas
                    // came out as an ellipse.
                    val d = minOf(size.width, size.height) - stroke
                    val left = (size.width - d) / 2f
                    val top = (size.height - d) / 2f
                    val arcSize = Size(d, d)
                    drawArc(
                        color = NeonMV.Track, startAngle = 0f, sweepAngle = 360f,
                        useCenter = false, topLeft = Offset(left, top),
                        size = arcSize, style = Stroke(stroke),
                    )
                    if (pct > 0) {
                        val sweep = (pct / 100.0 * 360.0).toFloat()
                        // Bloom: the same arc drawn wide and faint under the
                        // crisp one. A neon tube is a bright core in a halo,
                        // and a flat stroke on a dark ground reads as plastic.
                        for ((mult, alpha) in listOf(2.6f to 0.10f, 1.7f to 0.18f)) {
                            drawArc(
                                color = NeonMV.Lime.copy(alpha = alpha),
                                startAngle = -90f, sweepAngle = sweep,
                                useCenter = false, topLeft = Offset(left, top),
                                size = arcSize,
                                style = Stroke(stroke * mult, cap = StrokeCap.Round),
                            )
                        }
                        // Lime → cyan along the sweep, so a long week visibly
                        // travels rather than just getting longer.
                        drawArc(
                            brush = Brush.sweepGradient(
                                0.00f to NeonMV.Lime,
                                0.45f to NeonMV.Lime,
                                1.00f to NeonMV.Cyan,
                                center = Offset(left + d / 2f, top + d / 2f),
                            ),
                            startAngle = -90f, sweepAngle = sweep,
                            useCenter = false, topLeft = Offset(left, top),
                            size = arcSize,
                            style = Stroke(stroke, cap = StrokeCap.Round),
                        )
                    }
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(week?.label ?: "Weekly steps",
                        color = NeonMV.Muted, fontSize = 10.sp)
                    Text(
                        "${Math.round(pct)}%", color = NeonMV.Ink,
                        fontSize = 30.sp, fontWeight = FontWeight.Light,
                        style = androidx.compose.ui.text.TextStyle(
                            shadow = androidx.compose.ui.graphics.Shadow(
                                color = NeonMV.Lime.copy(alpha = 0.35f),
                                blurRadius = 22f,
                            ),
                        ),
                    )
                    Text(
                        "%,d of %,d".format(week?.done ?: 0, week?.goal ?: 0),
                        color = NeonMV.Muted, fontSize = 10.sp,
                    )
                }
            }

            // Saturated chips
            // No fixed height: pinning this column to the ring's 168dp left
            // each chip ~50dp for ~61dp of content, and the values were
            // clipped mid-glyph. The chips size to their content and the
            // row takes the taller of the two, as the web flexbox already
            // did.
            Column(
                Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                // Chip tint = the accent of the screen it opens. The old set
                // was hand-picked classic teal/navy/plum, so tapping the green
                // Steps chip landed on a lime chart.
                HeroChip("Steps", display("steps"), NeonMV.Card, NeonMV.Lime) { onOpen("vitals/STEPS") }
                HeroChip(
                    "Readiness",
                    readiness?.let { "%.0f".format(it) } ?: "—",
                    NeonMV.Card, NeonMV.Cyan,
                ) { onOpen("vitals/HR") }
                HeroChip("Sleep", display("sleep_duration"),
                    NeonMV.Card, NeonMV.Magenta) {
                    onOpen("vitals/SLEEP")
                }
            }
        }

    }
}

@Composable
private fun HeroChip(
    label: String, value: String, bg: Color, fg: Color,
    modifier: Modifier = Modifier, onClick: () -> Unit,
) {
    // Dark surface + thin luminous border + luminous label — the idiom the
    // neon shell already uses for the Fasting / Sober cards.
    //
    // A tinted FILL was the obvious first move and it looked wrong: an accent
    // at 16% over the near-black card lands on a muddy mid-tone — measured
    // (30,59,38) for lime, (22,56,72) for cyan — which reads as a washed-out
    // block rather than a neon one. Neon comes from a bright edge against a
    // dark ground, not from diluting the bright colour.
    Column(
        modifier
            .fillMaxWidth()
            .background(NeonMV.Card, RoundedCornerShape(18.dp))
            .border(1.dp, fg.copy(alpha = 0.45f), RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(label, color = fg, fontSize = 12.sp)
        Text(value, color = NeonMV.Ink, fontSize = 19.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

