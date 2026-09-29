package app.myvitals.ui.trails

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.myvitals.data.Units
import app.myvitals.sync.Trail
import app.myvitals.sync.TrailSuggestion
import app.myvitals.ui.neon.NeonEyebrow
import app.myvitals.ui.neon.NeonMV

/**
 * The body of both "Link to trail" sheets: the trails the route passed
 * nearest (from the server) first, then every pinned trail A→Z. The
 * suggested trails also stay in the full list, so nothing moves out of its
 * alphabetical place for someone who knows where to look.
 */
@Composable
fun TrailPickerList(
    trails: List<Trail>,
    suggestions: List<TrailSuggestion>,
    currentTrailId: Long?,
    enabled: Boolean,
    rowColor: Color,
    onPick: (Long) -> Unit,
) {
    val pickable = trails.filter { it.latitude != null && it.longitude != null }.sortedBy { it.name }
    LazyColumn(
        Modifier.fillMaxWidth().height(360.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        if (suggestions.isNotEmpty()) {
            item(key = "suggested-header") { NeonEyebrow("Suggested · nearest to this route") }
            items(suggestions, key = { "s${it.trailId}" }) { s ->
                PickRow(
                    name = s.name,
                    trailing = Units.fmtDistance(s.distanceKm * 1000.0) + " away",
                    current = s.trailId == currentTrailId,
                    enabled = enabled,
                    color = NeonMV.Lime.copy(alpha = 0.10f),
                ) { onPick(s.trailId) }
            }
            item(key = "all-header") { NeonEyebrow("All trails") }
        }
        items(pickable, key = { it.id }) { t ->
            PickRow(
                name = t.name,
                trailing = listOfNotNull(t.city, t.state).joinToString(", "),
                current = t.id == currentTrailId,
                enabled = enabled,
                color = rowColor,
            ) { onPick(t.id) }
        }
    }
}

@Composable
private fun PickRow(
    name: String,
    trailing: String,
    current: Boolean,
    enabled: Boolean,
    color: Color,
    onClick: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (current) NeonMV.Cyan.copy(alpha = 0.15f) else color,
        ),
        modifier = Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onClick),
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(name, modifier = Modifier.weight(1f), color = NeonMV.Ink, fontSize = 14.sp)
            if (trailing.isNotEmpty()) Text(trailing, color = NeonMV.Muted, fontSize = 11.sp)
        }
    }
}
