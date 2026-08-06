package app.myvitals.ui.common

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.ui.MV
import app.myvitals.ui.neon.NeonMV
import java.time.LocalDate
import java.time.OffsetDateTime

/**
 * Year-at-a-glance activity calendar, colour-coded by [ActivityCategory].
 *
 * Extracted from ActivitiesScreen so the Refined Train screen can show the
 * same strip without a second copy of the bucketing loop and the palette.
 *
 * Three bugs are fixed by the move:
 *  - The old strip hard-coded `cellSize = 10.dp` across 53 columns — 634 dp
 *    of drawing inside a `fillMaxWidth()` Canvas, so on a ~360 dp phone
 *    roughly half the year was silently clipped off the right edge. Cell
 *    size is now derived from the measured width.
 *  - It always drew all 53 columns, so ~40% of the strip was empty future
 *    weeks. That both read as "the calendar stops in August" and squeezed
 *    cells to 3.8 dp to fit a year that hadn't happened. The current year
 *    now ends at today: 32 columns in August, cells twice the size, strip
 *    fills the width.
 *  - The legend was a hard-coded list of five entries while the canvas
 *    could draw seven categories, so Row and Other rendered with no key.
 *    The legend is now derived from the data actually present.
 */

/**
 * Bucket one calendar year into ISO-date → category.
 *
 * `putIfAbsent` throughout preserves the original precedence: the first
 * activity of a day wins, and a logged activity beats a generated workout
 * on the same date.
 */
fun buildActivityCalendarIndex(
    rows: List<ActivityRow>,
    workouts: List<StrengthWorkoutSummary>,
    year: Int,
): Map<String, ActivityCategory> {
    val m = mutableMapOf<String, ActivityCategory>()
    for (r in rows) {
        val d = runCatching {
            OffsetDateTime.parse(r.startAt).toLocalDate()
        }.getOrNull() ?: continue
        if (d.year != year) continue
        m.putIfAbsent(d.toString(), categoryForActivityType(r.type))
    }
    for (w in workouts) {
        if (w.status != "completed") continue
        val d = runCatching { LocalDate.parse(w.date) }.getOrNull() ?: continue
        if (d.year != year) continue
        m.putIfAbsent(d.toString(), categoryForSplitFocus(w.splitFocus))
    }
    return m.toMap()
}

/**
 * The full card: title, strip, legend. Renders nothing when the year has
 * no logged days, matching the old behaviour.
 *
 * @param showCard false draws the contents bare, for a screen that already
 *   supplies its own card chrome.
 */
@Composable
fun ActivityCalendarCard(
    rows: List<ActivityRow>,
    workouts: List<StrengthWorkoutSummary>,
    neon: Boolean,
    modifier: Modifier = Modifier,
    year: Int = LocalDate.now().year,
    title: String? = null,
    showLegend: Boolean = true,
    showCard: Boolean = true,
) {
    val byDate = remember(rows, workouts, year) {
        buildActivityCalendarIndex(rows, workouts, year)
    }
    if (byDate.isEmpty()) return

    val body: @Composable () -> Unit = {
        Column(modifier = Modifier.padding(12.dp)) {
            if (title != null) {
                Text2(
                    title,
                    color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
                    size = 11, weight = FontWeight.Bold, spacing = 1.5,
                )
                Spacer(Modifier.height(8.dp))
            }
            ActivityCalendarYearGrid(year, byDate, neon)
            if (showLegend) {
                Spacer(Modifier.height(8.dp))
                ActivityCalendarLegend(byDate, neon)
            }
        }
    }

    if (showCard) {
        Box(
            modifier
                .fillMaxWidth()
                .background(
                    if (neon) NeonMV.Card else MV.SurfaceContainer,
                    RoundedCornerShape(if (neon) 15.dp else 12.dp),
                )
                .then(
                    if (neon) Modifier.border(
                        1.dp, NeonMV.Line, RoundedCornerShape(15.dp),
                    ) else Modifier,
                ),
        ) { body() }
    } else {
        Box(modifier.fillMaxWidth()) { body() }
    }
}

/**
 * The 7×N grid. N is the weeks actually elapsed (full 53 for a past year),
 * and cell size is derived from the measured width so it fills the row. If
 * the container is narrow enough that cells would fall below [minCell] the
 * strip scrolls horizontally rather than clipping.
 */
@Composable
fun ActivityCalendarYearGrid(
    year: Int,
    byDate: Map<String, ActivityCategory>,
    neon: Boolean,
    modifier: Modifier = Modifier,
    cellGap: Dp = 2.dp,
    minCell: Dp = 5.dp,
) {
    val firstDay = remember(year) { LocalDate.of(year, 1, 1) }
    val startDow = remember(year) { firstDay.dayOfWeek.value % 7 }  // Sun=0
    // Stop at today for the current year. Drawing all 53 columns meant ~40%
    // of the strip was empty future weeks, which both looked like the
    // calendar had stopped early AND squeezed the cells to 3.8 dp to fit a
    // year that hadn't happened yet. Through-today is 32 columns in August,
    // so cells double in size and the strip actually fills the width.
    val lastDay = remember(year) {
        val today = LocalDate.now()
        if (year == today.year) today else firstDay.plusDays(firstDay.lengthOfYear() - 1L)
    }
    val dayCount = remember(firstDay, lastDay) {
        (java.time.temporal.ChronoUnit.DAYS.between(firstDay, lastDay) + 1).toInt()
    }
    val totalCols = remember(dayCount, startDow) {
        ((dayCount + startDow + 6) / 7).coerceIn(1, 53)
    }
    val empty = activityCategoryEmpty(neon)

    BoxWithConstraints(modifier.fillMaxWidth()) {
        val available = maxWidth - cellGap * (totalCols - 1)
        val fitted = available / totalCols
        val scrolls = fitted < minCell
        val cell = if (scrolls) minCell else fitted
        val stripWidth = cell * totalCols + cellGap * (totalCols - 1)
        val stripHeight = cell * 7 + cellGap * 6

        val canvas: @Composable () -> Unit = {
            Canvas(
                Modifier
                    .width(stripWidth)
                    .height(stripHeight),
            ) {
                val cellPx = cell.toPx()
                val gapPx = cellGap.toPx()
                for (i in 0 until dayCount) {
                    val date = firstDay.plusDays(i.toLong())
                    val col = (i + startDow) / 7
                    val row = (i + startDow) % 7
                    if (col >= totalCols) break
                    val color = byDate[date.toString()]?.color(neon) ?: empty
                    drawRect(
                        color = color,
                        topLeft = Offset(col * (cellPx + gapPx), row * (cellPx + gapPx)),
                        size = Size(cellPx, cellPx),
                    )
                }
            }
        }

        if (scrolls) {
            Box(Modifier.horizontalScroll(rememberScrollState())) { canvas() }
        } else {
            canvas()
        }
    }
}

/**
 * Legend derived from the categories actually present, in enum order, so a
 * colour can never appear on the grid without a key beside it.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ActivityCalendarLegend(
    byDate: Map<String, ActivityCategory>,
    neon: Boolean,
    modifier: Modifier = Modifier,
) {
    val present = remember(byDate) {
        byDate.values.distinct().sortedBy { it.ordinal }
    }
    if (present.isEmpty()) return
    FlowRow(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        present.forEach { LegendDot(it, neon) }
    }
}

@Composable
private fun LegendDot(category: ActivityCategory, neon: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(8.dp)
                .background(category.color(neon), CircleShape),
        )
        Spacer(Modifier.width(3.dp))
        Text2(
            category.label,
            color = if (neon) NeonMV.Muted else MV.OnSurfaceVariant,
            size = 9,
        )
    }
}

/** Thin wrapper so this file doesn't import Material3 Text everywhere. */
@Composable
private fun Text2(
    text: String,
    color: Color,
    size: Int,
    weight: FontWeight = FontWeight.Normal,
    spacing: Double = 0.0,
) {
    androidx.compose.material3.Text(
        text,
        color = color,
        fontSize = size.sp,
        fontWeight = weight,
        letterSpacing = spacing.sp,
    )
}
