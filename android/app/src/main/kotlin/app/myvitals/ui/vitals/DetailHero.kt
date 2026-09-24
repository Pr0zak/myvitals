package app.myvitals.ui.vitals

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.ui.common.ShimmerBlock
import app.myvitals.ui.neon.NeonCardShape
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV
import app.myvitals.ui.neon.NeonStatTile

/*
 * UI-4 — the pieces the four metric detail screens (Steps, Heart rate,
 * Sleep, Weight) share on top of the neon kit, so the four read as one
 * design rather than four copies drifting apart:
 *
 *   DetailTitleIcon   the metric's accent icon beside the NeonScreen title
 *   DetailStatusChip  the server's verdict, worded by the server
 *   DetailStatRow     a row of NeonStatTiles fed with server values
 *   DetailCard        a secondary (non-hero) chart card
 *   DetailSkeleton    shimmer shaped like the hero + first chart
 *   DetailLegend      coloured-dot legend, wrapping
 *
 * The web twins live in the four views (Steps.vue, HeartRate.vue, Sleep.vue,
 * Weight.vue) using the components/neon kit.
 */

/** Accent icon in a soft disc, used as NeonScreen's `headerTrailing`. */
@Composable
fun DetailTitleIcon(vital: Vital) {
    Box(
        Modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(vital.accent.copy(alpha = 0.14f))
            .border(1.dp, vital.accent.copy(alpha = 0.35f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Icon(vital.icon, contentDescription = null, tint = vital.accent,
            modifier = Modifier.size(20.dp))
    }
}

/**
 * The server's verdict for this metric (`/summary/tiles` `status` +
 * `status_reason`, or a detail block's `tone`). Colour follows the app's
 * rules: good/positive = Lime, typical/neutral = Muted, watch/caution =
 * Amber. Never rose — this is a chip on an ordinary metric, not a crisis.
 */
@Composable
fun DetailStatusChip(status: String?, text: String?, modifier: Modifier = Modifier) {
    if (text.isNullOrBlank()) return
    val c = when (status) {
        "good", "positive" -> NeonMV.Lime
        "watch", "caution" -> NeonMV.Amber
        else -> NeonMV.Muted
    }
    Row(
        modifier
            .clip(RoundedCornerShape(999.dp))
            .background(c.copy(alpha = 0.12f))
            .border(1.dp, c.copy(alpha = 0.35f), RoundedCornerShape(999.dp))
            .padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(c))
        Spacer(Modifier.width(6.dp))
        Text(text, color = c, fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
            maxLines = 1)
    }
}

/** Server values as a row of stat tiles. `null` values render "—". */
@Composable
fun DetailStatRow(stats: List<Pair<String?, String>>, accentFirst: Color? = null) {
    Row(
        Modifier.fillMaxWidth().padding(bottom = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        stats.forEachIndexed { i, (v, label) ->
            NeonStatTile(
                value = v ?: "—", label = label,
                modifier = Modifier.weight(1f),
                accent = if (i == 0) accentFirst else null,
            )
        }
    }
}

/** A secondary chart card: Card surface, hairline border, eyebrow title. */
@Composable
fun DetailCard(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    NeonEyebrow(title)
    Column(
        modifier
            .fillMaxWidth()
            .clip(NeonCardShape)
            .background(NeonMV.Card)
            .border(1.dp, NeonMV.Line, NeonCardShape)
            .padding(14.dp),
    ) {
        if (subtitle != null) {
            Text(subtitle, color = NeonMV.Muted, fontSize = 11.sp)
            Spacer(Modifier.height(8.dp))
        }
        content()
    }
}

/** Muted one-liner inside a card ("No samples on this day."). */
@Composable
fun DetailNote(text: String) {
    Text(text, color = NeonMV.Muted, fontSize = 12.sp)
}

/**
 * Cold-load placeholder shaped like what is coming: the hero (number, chip,
 * one chart) then a stat row and the first secondary chart. Tinted with the
 * metric accent so the sweep reads on the dark ground.
 */
@Composable
fun DetailSkeleton(accent: Color) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 14.dp)
            .clip(RoundedCornerShape(22.dp))
            .background(NeonMV.CardHigh)
            .border(1.dp, accent.copy(alpha = 0.25f), RoundedCornerShape(22.dp))
            .padding(16.dp),
    ) {
        ShimmerBlock(width = 90.dp, height = 11.dp, accent = accent)
        Spacer(Modifier.height(12.dp))
        ShimmerBlock(width = 170.dp, height = 48.dp, cornerRadius = 10.dp, accent = accent)
        Spacer(Modifier.height(10.dp))
        ShimmerBlock(width = 140.dp, height = 22.dp, cornerRadius = 999.dp, accent = accent)
        Spacer(Modifier.height(16.dp))
        ShimmerBlock(Modifier.fillMaxWidth(), height = 150.dp, cornerRadius = 12.dp, accent = accent)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        repeat(3) {
            ShimmerBlock(Modifier.weight(1f), height = 62.dp, cornerRadius = 18.dp, accent = accent)
        }
    }
    Spacer(Modifier.height(22.dp))
    ShimmerBlock(width = 110.dp, height = 11.dp, accent = accent)
    Spacer(Modifier.height(10.dp))
    ShimmerBlock(Modifier.fillMaxWidth(), height = 170.dp, cornerRadius = 18.dp, accent = accent)
}

/** Coloured-square legend, wrapping so a long stage list never runs off. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DetailLegend(items: List<Pair<Color, String>>, modifier: Modifier = Modifier) {
    FlowRow(
        modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for ((c, label) in items) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(9.dp).clip(RoundedCornerShape(2.dp)).background(c))
                Spacer(Modifier.width(5.dp))
                Text(label, color = NeonMV.Muted, fontSize = 11.sp)
            }
        }
    }
}

/** "4h 12m" / "38m" from seconds. */
fun fmtDurS(s: Int?): String? {
    if (s == null) return null
    val h = s / 3600
    val m = (s % 3600) / 60
    return if (h > 0) "${h}h ${m}m" else "${m}m"
}
