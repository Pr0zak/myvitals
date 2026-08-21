package app.myvitals.ui.common

import app.myvitals.data.Units
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ActivityRow
import app.myvitals.sync.StrengthWorkoutSummary
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber
import java.time.Duration
import java.time.LocalDate
import java.time.OffsetDateTime

/**
 * Year-to-date totals and the same-point-last-year comparison.
 *
 * The computation lives here rather than inside the Activities card so the
 * Refined Train screen reports the *same* numbers. Two surfaces disagreeing
 * about "activities this year" is the exact bug class the architecture rule
 * in CLAUDE.md calls out, and duplicating this loop is how that starts.
 */
data class YtdTotals(
    var n: Int = 0,
    var distanceM: Double = 0.0,
    var durationS: Long = 0L,
    var elevationM: Double = 0.0,
)

data class YtdComparison(
    val thisYear: Int,
    val lastYear: Int,
    val ytd: YtdTotals,
    val prior: YtdTotals,
) {
    val pctN: Double get() = pct(ytd.n.toDouble(), prior.n.toDouble())
    val pctDistance: Double get() = pct(ytd.distanceM, prior.distanceM)
    val pctDuration: Double get() = pct(ytd.durationS.toDouble(), prior.durationS.toDouble())
    val pctElevation: Double get() = pct(ytd.elevationM, prior.elevationM)

    private fun pct(now: Double, prev: Double): Double {
        if (prev == 0.0) return if (now == 0.0) 0.0 else 100.0
        return ((now - prev) / prev) * 100.0
    }
}

/**
 * Verbatim port of the loop that used to live inside `YtdYoyCard`,
 * including the strength `started_at`/`completed_at` duration fallback and
 * the "same day last year" cutoff so the comparison is like-for-like.
 */
fun computeYtdComparison(
    rows: List<ActivityRow>,
    workouts: List<StrengthWorkoutSummary>,
    today: LocalDate = LocalDate.now(),
): YtdComparison {
    val thisYear = today.year
    val lastYear = thisYear - 1
    val endOfLastYear = runCatching {
        LocalDate.of(lastYear, today.monthValue, today.dayOfMonth)
    }.getOrElse { LocalDate.of(lastYear, today.monthValue, 28) }  // 29 Feb

    val a = YtdTotals()
    val b = YtdTotals()

    for (r in rows) {
        val d = runCatching {
            OffsetDateTime.parse(r.startAt).toLocalDate()
        }.getOrNull() ?: continue
        val t = when {
            d.year == thisYear && !d.isAfter(today) -> a
            d.year == lastYear && !d.isAfter(endOfLastYear) -> b
            else -> null
        } ?: continue
        t.n += 1
        t.distanceM += r.distanceM ?: 0.0
        t.durationS += r.durationS
        t.elevationM += r.elevationGainM ?: 0.0
    }

    for (w in workouts) {
        if (w.status != "completed") continue
        val d = runCatching { LocalDate.parse(w.date) }.getOrNull() ?: continue
        val t = when {
            d.year == thisYear && !d.isAfter(today) -> a
            d.year == lastYear && !d.isAfter(endOfLastYear) -> b
            else -> null
        } ?: continue
        t.n += 1
        val started = w.startedAt
        val completed = w.completedAt
        if (started != null && completed != null) {
            t.durationS += runCatching {
                Duration.between(
                    OffsetDateTime.parse(started).toInstant(),
                    OffsetDateTime.parse(completed).toInstant(),
                ).seconds
            }.getOrDefault(0L)
        }
    }
    return YtdComparison(thisYear, lastYear, a, b)
}

fun ytdMiles(meters: Double): String = "%.0f".format(Units.distance(meters) ?: 0.0)

/**
 * Compact two-cell strip (activities · distance) for a hub screen that
 * only has room for the headline pair. The full four-cell breakdown stays
 * on the Activities screen.
 */
@Composable
fun YtdStatPair(
    cmp: YtdComparison,
    neon: Boolean,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        YtdCompactCell(
            value = "${cmp.ytd.n}", unit = null, label = "ACTIVITIES",
            pct = cmp.pctN, neon = neon, onClick = onClick,
            modifier = Modifier.weight(1f),
        )
        YtdCompactCell(
            value = ytdMiles(cmp.ytd.distanceM), unit = "mi", label = "DISTANCE",
            pct = cmp.pctDistance, neon = neon, onClick = onClick,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun YtdCompactCell(
    value: String,
    unit: String?,
    label: String,
    pct: Double,
    neon: Boolean,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(15.dp))
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, RoundedCornerShape(15.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(
            label,
            color = NeonMV.Muted,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.4.sp,
        )
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = androidx.compose.ui.Alignment.Bottom) {
            NeonNumber(value, size = 22, color = NeonMV.Ink)
            if (unit != null) {
                Spacer(Modifier.padding(horizontal = 2.dp))
                Text(unit, color = NeonMV.Muted, fontSize = 12.sp)
            }
        }
        Spacer(Modifier.height(4.dp))
        val up = pct >= 0
        Text(
            (if (up) "↑ " else "↓ ") + "%.0f%%".format(kotlin.math.abs(pct)),
            color = if (up) NeonMV.Lime else NeonMV.Bad,
            fontSize = 11.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}
