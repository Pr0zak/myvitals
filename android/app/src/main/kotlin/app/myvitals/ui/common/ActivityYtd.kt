package app.myvitals.ui.common

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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.ActivityYtd
import app.myvitals.sync.YtdMetric
import app.myvitals.ui.activities.deltaText
import app.myvitals.ui.activities.fmtMetric
import app.myvitals.ui.activities.metricOf
import app.myvitals.ui.activities.metricUnit
import app.myvitals.ui.activities.toneColor
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonNumber

/**
 * Year-to-date headline pair for a hub screen (sessions · distance), drawn
 * from the server's `GET /activities/ytd` — the same response the Activities
 * hero renders (UI-F3).
 *
 * This file used to hold `computeYtdComparison`, a client-side port of the
 * year-to-date loop, which the Train tab ran while Activities read the
 * server. Two surfaces answering "how much have I done this year" from two
 * implementations is the disagreement the architecture rule forbids — and
 * the port had drifted: it invented "+100%" when last year was zero, and
 * painted every drop in the crisis rose. Both come from the server now
 * (`note == "new"`, and `tone`, which is amber for a shortfall).
 */
@Composable
fun YtdServerPair(
    ytd: ActivityYtd,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        metricOf(ytd, "sessions")?.let {
            YtdCell(it, label = "ACTIVITIES", onClick = onClick, modifier = Modifier.weight(1f))
        }
        metricOf(ytd, "distance_m")?.let {
            YtdCell(it, label = "DISTANCE", onClick = onClick, modifier = Modifier.weight(1f))
        }
    }
}

@Composable
private fun YtdCell(
    m: YtdMetric,
    label: String,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, RoundedCornerShape(18.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(label, color = NeonMV.Muted, fontSize = 10.sp,
            fontWeight = FontWeight.Bold, letterSpacing = 1.4.sp)
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            NeonNumber(fmtMetric(m, m.current), size = 22, color = NeonMV.Ink)
            val unit = metricUnit(m)
            if (unit.isNotBlank()) {
                Spacer(Modifier.padding(horizontal = 2.dp))
                Text(unit, color = NeonMV.Muted, fontSize = 12.sp)
            }
        }
        Spacer(Modifier.height(4.dp))
        Text(
            deltaText(m) + " vs last year",
            color = toneColor(m.tone),
            fontSize = 11.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}
