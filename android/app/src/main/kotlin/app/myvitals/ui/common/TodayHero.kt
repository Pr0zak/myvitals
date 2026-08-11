package app.myvitals.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            // Ring
            Box(
                Modifier
                    .size(168.dp)
                    .background(Color(0xFF1B1C1F), RoundedCornerShape(22.dp))
                    .clickable { onOpen("vitals/STEPS") },
                contentAlignment = Alignment.Center,
            ) {
                val pct = (week?.pct ?: 0.0).coerceIn(0.0, 100.0)
                Canvas(Modifier.fillMaxSize().padding(18.dp)) {
                    val stroke = 11.dp.toPx()
                    val inset = stroke / 2
                    val arcSize = Size(size.width - stroke, size.height - stroke)
                    drawArc(
                        color = Color(0xFF2A2D34), startAngle = 0f, sweepAngle = 360f,
                        useCenter = false, topLeft = Offset(inset, inset),
                        size = arcSize, style = Stroke(stroke),
                    )
                    if (pct > 0) {
                        drawArc(
                            color = Color(0xFF5B8CFF), startAngle = -90f,
                            sweepAngle = (pct / 100.0 * 360.0).toFloat(),
                            useCenter = false, topLeft = Offset(inset, inset),
                            size = arcSize,
                            style = Stroke(stroke, cap = StrokeCap.Round),
                        )
                    }
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(week?.label ?: "Weekly steps",
                        color = Color(0xFFB9BEC6), fontSize = 10.sp)
                    Text("${Math.round(pct)}%", color = Color(0xFFE9EDF2),
                        fontSize = 27.sp, fontWeight = FontWeight.Light)
                    Text(
                        "%,d of %,d".format(week?.done ?: 0, week?.goal ?: 0),
                        color = Color(0xFF8D949D), fontSize = 10.sp,
                    )
                }
            }

            // Saturated chips
            Column(
                Modifier.weight(1f).height(168.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                HeroChip("Steps", display("steps"), Color(0xFF0F4F45),
                    Color(0xFF7FE6D2), Modifier.weight(1f)) { onOpen("vitals/STEPS") }
                HeroChip(
                    "Readiness",
                    readiness?.let { "%.0f".format(it) } ?: "—",
                    Color(0xFF123C56), Color(0xFF8FD0F5), Modifier.weight(1f),
                ) { onOpen("vitals/HR") }
                HeroChip("Sleep", display("sleep_duration"), Color(0xFF3D2A5C),
                    Color(0xFFC9ADF5), Modifier.weight(1f)) { onOpen("vitals/SLEEP") }
            }
        }

        Spacer(Modifier.height(12.dp))
        // Both go somewhere real — no decorative buttons.
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            HeroAction("+ Log", Modifier.weight(1f)) { onOpen("journal") }
            HeroAction("Start", Modifier.weight(1f)) { onOpen("workout/today") }
        }
    }
}

@Composable
private fun HeroChip(
    label: String, value: String, bg: Color, fg: Color,
    modifier: Modifier = Modifier, onClick: () -> Unit,
) {
    Column(
        modifier
            .fillMaxWidth()
            .background(bg, RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(label, color = fg, fontSize = 12.sp)
        Text(value, color = Color.White, fontSize = 19.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun HeroAction(label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Box(
        modifier
            .background(Color(0xFF143A52), RoundedCornerShape(999.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = Color(0xFFCFE6F7), fontSize = 14.sp,
            fontWeight = FontWeight.Medium)
    }
}
