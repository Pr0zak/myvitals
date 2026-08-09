package app.myvitals.ui.neon

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.sync.TrendBadge

/**
 * "What's notable today" — the answer the app already computed and threw away.
 *
 * `GET /ai/badges` runs pure spike / streak / slope detection over the last 30
 * days of daily summaries. No LLM, no cost, no quota. It existed on the
 * backend and was rendered by neither client: the phone had no call for it,
 * and the web's TrendBadges.vue was imported by no view.
 *
 * Deliberately chips, not prose. Google Health shipped narration on its home
 * screen and is still walking it back — "make messages more concise" was still
 * an open roadmap item as of July 2026. A badge is a statistic with a colour;
 * it earns its 56dp because it can be read in one glance.
 *
 * Renders NOTHING when there are no badges — no reserved-but-empty block.
 */
@Composable
fun FocusStrip(
    badges: List<TrendBadge>,
    modifier: Modifier = Modifier,
    onClick: ((TrendBadge) -> Unit)? = null,
) {
    if (badges.isEmpty()) return
    Column(modifier.fillMaxWidth().padding(bottom = 14.dp)) {
        Text(
            "FOCUS",
            color = NeonMV.Muted,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 1.4.sp,
        )
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            badges.take(3).forEach { b -> FocusChip(b, onClick) }
        }
    }
}

/** Semantic colour is independent of the shell accent: good/warn/bad only. */
private fun toneColor(tone: String): Color = when (tone.lowercase()) {
    "good" -> NeonMV.Lime
    "warn" -> NeonMV.Amber
    "bad" -> NeonMV.Bad
    else -> NeonMV.Periwinkle
}

private fun arrowFor(direction: String): String = when (direction.lowercase()) {
    "up" -> "▲"
    "down" -> "▼"
    "spike" -> "◆"
    "streak" -> "●"
    else -> "—"
}

@Composable
private fun FocusChip(badge: TrendBadge, onClick: ((TrendBadge) -> Unit)?) {
    val tone = toneColor(badge.tone)
    Row(
        Modifier
            .background(tone.copy(alpha = 0.11f), RoundedCornerShape(13.dp))
            .border(1.dp, tone.copy(alpha = 0.34f), RoundedCornerShape(13.dp))
            .then(
                if (onClick != null) {
                    Modifier.clickable { onClick(badge) }
                } else Modifier,
            )
            .padding(horizontal = 12.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(7.dp),
    ) {
        Text(arrowFor(badge.direction), color = tone, fontSize = 11.sp,
            fontWeight = FontWeight.Bold)
        Column {
            Text(
                badge.label,
                color = NeonMV.Muted, fontSize = 10.sp,
                fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp,
            )
            Spacer(Modifier.height(1.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                NeonNumber(badge.value, size = 15, color = NeonMV.Ink)
                if (badge.subtitle.isNotBlank()) {
                    Spacer(Modifier.padding(horizontal = 3.dp))
                    Text(badge.subtitle, color = NeonMV.Muted, fontSize = 10.sp)
                }
            }
        }
    }
}
